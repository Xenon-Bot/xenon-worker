from .command import Command


class Listener:
    def __init__(self, callback, name=None):
        name = name or callback.__name__
        if name.startswith("on_"):
            name = name[3:]

        self.name = name
        self.callback = callback


class Module:
    def __init__(self, client):
        self.client = client

    @property
    def commands(self):
        for name in dir(self):
            attr = getattr(self, name)
            if isinstance(attr, Command):
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
