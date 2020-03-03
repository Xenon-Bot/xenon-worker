from ..connection.rabbit import RabbitClient
from ..connection.entities import Message
from .command import CommandTable
from .context import Context
from .module import Listener
from .formatter import Formatter, FormatRaise
import traceback
from .errors import *
import sys


class RabbitBot(RabbitClient, CommandTable):
    def __init__(self, prefix, *args, **kwargs):
        RabbitClient.__init__(self, *args, **kwargs)
        CommandTable.__init__(self)
        self.prefix = prefix
        self.static_listeners = {}
        self.modules = []
        self.f = Formatter()

    def f_send(self, channel, *args, **kwargs):
        return self.send_message(channel, **self.f.format(*args, **kwargs))

    def _process_listeners(self, event, *args, **kwargs):
        s_listeners = self.static_listeners.get(event.name, [])
        for listener in s_listeners:
            self.loop.create_task(listener.execute(event.shard_id, *args, **kwargs))

        super()._process_listeners(event, *args, **kwargs)

    async def process_commands(self, shard_id, msg):
        parts = msg.content.split(" ")
        try:
            parts, cmd = self.find_command(parts)
        except CommandNotFound:
            return

        ctx = Context(self, shard_id, msg)
        try:
            await cmd.execute(ctx, parts)
        except Exception as e:
            self.dispatch("command_error", cmd, ctx, e)

    async def invoke(self, ctx, cmd):
        parts = cmd.split(" ")
        try:
            parts, cmd = self.find_command(parts)
        except CommandNotFound:
            return

        await cmd.execute(ctx, parts)

    async def on_command_error(self, _, cmd, ctx, e):
        if isinstance(e, FormatRaise):
            await ctx.f_send(*e.args, **e.kwargs, f=e.f)

        elif isinstance(e, CommandNotFound):
            pass

        elif isinstance(e, NotEnoughArguments):
            await ctx.f_send(
                f"The command `{cmd.full_name}` is **missing the `{e.parameter.name}` argument**.\n"
                f"Use `{self.prefix}help {cmd.full_name}` to get more information.",
                f=self.f.ERROR
            )

        elif isinstance(e, ConverterFailed):
            pass

        elif isinstance(e, MissingPermissions):
            await ctx.f_send(
                f"You are **missing** the following **permissions**: `{', '.join(e.missing)}`.",
                f=self.f.ERROR
            )

        elif isinstance(e, BotMissingPermissions):
            await ctx.f_send(
                f"The bot is **missing** the following **permissions**: `{', '.join(e.missing)}`.",
                f=self.f.ERROR
            )

        elif isinstance(e, NotOwner):
            await ctx.f_send(
                "This command can **only** be used by the **server owner**.",
                f=self.f.ERROR
            )

        elif isinstance(e, NotBotOwner):
            await ctx.f_send(
                "This command can **only** be used by the **bot owner**.",
                f=self.f.ERROR
            )

        elif isinstance(e, NotAGuildChannel):
            await ctx.f_send(
                "This command can **only** be used **inside a guild**.",
                f=self.f.ERROR
            )

        elif isinstance(e, NotADMChannel):
            await ctx.f_send(
                "This command can **only** be used in **direct messages**.",
                f=self.f.ERROR
            )

        elif isinstance(e, CommandOnCooldown):
            await ctx.f_send(
                f"This **command** is currently on **cooldown**.\n"
                f"You have to **wait `{e.remaining}` seconds** until you can use it again.",
                f=self.f.ERROR
            )

        else:
            traceback.print_exception(type(e), e, e.__traceback__, file=sys.stderr)
            await ctx.f_send(f"```py\n{e.__class__.__name__}:\n{str(e)}\n```", f=self.f.ERROR)

    async def on_command(self, shard_id, data):
        msg = Message(data)
        await self.process_commands(shard_id, msg)

    def add_listener(self, listener):
        if listener.name not in self.static_listeners.keys():
            self.static_listeners[listener.name] = []

        listeners = self.static_listeners[listener.name]
        listeners.append(listener)

    def listener(self, *args, **kwargs):
        def _predicate(callback):
            listener = Listener(callback, *args, **kwargs)
            self.add_listener(listener)
            return listener

        return _predicate

    def add_module(self, module):
        self.modules.append(module)
        for cmd in module.commands:
            cmd.fill_module(module)
            self.add_command(cmd)

        for listener in module.listeners:
            listener.module = module
            self.add_listener(listener)

        for task in module.tasks:
            task.module = module
            self.schedule(task.construct())

    def schedule(self, coro):
        return self.loop.create_task(coro)

    async def start(self, *subscriptions):
        subscriptions = set(subscriptions)
        subscriptions.add("command")

        await super().start(*subscriptions)
        self.dispatch("load")

    async def close(self):
        await super().close()
