from .command import Command
from datetime import timedelta, datetime
import traceback
import asyncio


class Task:
    def __init__(self, callback, delta=True, **units):
        self.delta = delta
        self.callback = callback
        self.units = units
        self.module = None  # Gets filled by bot.add_module

    @property
    def time_to_wait(self):
        if self.delta:
            return timedelta(**self.units).total_seconds()

        now = datetime.utcnow()

        time = datetime.utcnow().replace(
            hour=self.units.get("hour", 0),
            minute=self.units.get("minute", 0),
            second=self.units.get("seconds", 0),
            microsecond=0
        )

        wait = time - now
        if wait.total_seconds() < 0:
            wait += timedelta(days=1)

        return wait.total_seconds()

    def construct(self):
        async def coro():
            while True:
                await asyncio.sleep(self.time_to_wait)
                try:
                    await self.callback(self.module)

                except:
                    traceback.print_exc()

        return coro()


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

    @property
    def tasks(self):
        for name in dir(self):
            attr = getattr(self, name)
            if isinstance(attr, Task):
                yield attr

    @staticmethod
    def command(*args, **kwargs):
        def _predicate(callback):
            return Command(callback, *args, **kwargs)

        return _predicate

    @staticmethod
    def listener(*args, **kwargs):
        def _predicate(callback):
            return Listener(callback, *args, **kwargs)

        return _predicate

    @staticmethod
    def task(*args, **kwargs):
        def _predicate(callback):
            return Task(callback, *args, **kwargs)

        return _predicate
