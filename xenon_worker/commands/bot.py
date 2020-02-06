from connection.rabbit import RabbitClient
from connection.entities import Message
from .command import CommandTable
from .context import Context
from .module import Listener


class RabbitBot(RabbitClient, CommandTable):
    def __init__(self, prefix, *args, **kwargs):
        RabbitClient.__init__(self, *args, **kwargs)
        CommandTable.__init__(self)
        self.prefix = prefix
        self.static_listeners = {}
        self.modules = []

    def _process_listeners(self, key, data):
        s_listeners = self.static_listeners.get(key.split(".")[1], [])
        for listener in s_listeners:
            pre_ctx = []
            # Add self parameter to module bound callbacks
            for module in self.modules:
                attr = getattr(module, listener.callback.__name__, None)
                if attr is listener:
                    pre_ctx.append(module)
                    break

            self.loop.create_task(listener.callback(*pre_ctx, data))

    async def process_commands(self, msg):
        parts = msg.content[len(self.prefix):].split(" ")
        try:
            cmd = self.find_command(parts)
        except ValueError:
            return

        pre_ctx = []
        # Add self parameter to module bound callbacks
        for module in self.modules:
            attr = getattr(module, cmd.callback.__name__, None)
            if attr is cmd:
                pre_ctx.append(module)
                break

        ctx = Context(self, msg)
        await cmd.execute(pre_ctx, ctx, parts)

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
            self.add_command(cmd)

        for listener in module.listeners:
            self.add_listener(listener)
