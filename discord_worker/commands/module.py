from .command import Command


class Listener:
    def __init__(self, callback, name=None):
        name = name or callback.__name__
        if name.startswith("on_"):
            name = name[3:]

        self.module = None  # Gets filled by bot.add_module
        self.name = name
        self.callback = callback

    async def execute(self, *args, **kwargs):
        if self.module is None:
            await self.callback(*args, **kwargs)

        else:
            await self.callback(self.module, *args, **kwargs)


class Module:
    def __init__(self, client):
        self.client = client
        self.bot = client

    @property
    def commands(self):
        for name in dir(self):
            attr = getattr(self, name)
            # attr.parent is None checks if it is a subcommand
            if isinstance(attr, Command) and attr.parent is None:
                yield attr

    @property
    def listeners(self):
        for name in dir(self):
            attr = getattr(self, name)
            if isinstance(attr, Listener):
                yield attr

    def command(*args, **kwargs):
        def _predicate(callback):
            return Command(callback, *args, **kwargs)

        return _predicate

    def listener(*args, **kwargs):
        def _predicate(callback):
            return Listener(callback, *args, **kwargs)

        return _predicate
