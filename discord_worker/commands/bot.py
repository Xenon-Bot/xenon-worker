from ..connection.rabbit import RabbitClient
from ..connection.entities import Message
from .command import CommandTable
from .context import Context
from .module import Listener
from .formatter import Formatter
from .errors import *


class RabbitBot(RabbitClient, CommandTable):
    def __init__(self, prefix, *args, **kwargs):
        RabbitClient.__init__(self, *args, **kwargs)
        CommandTable.__init__(self)
        self.prefix = prefix
        self.static_listeners = {}
        self.modules = []
        self.f = Formatter()

    async def f_send(self, channel_id, *args, **kwargs):
        await self.http.send_message(channel_id, **self.f.format(*args, **kwargs))

    def _process_listeners(self, key, *args, **kwargs):
        s_listeners = self.static_listeners.get(key.split(".")[-1], [])
        for listener in s_listeners:
            self.loop.create_task(listener.execute(*args, **kwargs))

    async def process_commands(self, msg):
        parts = msg.content[len(self.prefix):].split(" ")
        try:
            parts, cmd = self.find_command(parts)
        except CommandNotFound:
            return

        ctx = Context(self, msg)
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

    async def on_command_error(self, cmd, ctx, e):
        print(type(e).__name__, e)

    async def on_message_create(self, data):
        msg = Message(data)
        await self.process_commands(msg)

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
