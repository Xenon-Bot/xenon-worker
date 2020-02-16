from inspect import cleandoc, getdoc, Parameter, signature, ismethod, isawaitable
from abc import ABC

from .checks import Check
from .errors import *


class BaseCommand(ABC):
    def __init__(self, *commands):
        self.commands = list(commands)

    def add_command(self, command):
        self.commands.append(command)

    def remove_command(self, command):
        self.commands.remove(command)

    def command(self, *args, **kwargs):
        def _predicate(callback):
            cmd = Command(callback, *args, **kwargs)
            self.commands.append(cmd)
            return cmd

        return _predicate

    def filter_commands(self, parts):
        if len(parts) == 0:
            return []

        for command in self.commands:
            if isinstance(command, Command):
                if command.name == parts[0] or parts[0] in command.aliases:
                    yield command

            else:
                yield command

    def find_command(self, parts):
        for cmd in self.filter_commands(parts):
            try:
                parts, res = cmd.find_command(parts[1:])
            except ValueError:
                continue

            else:
                return parts, res

        if self.can_execute(parts):
            return parts, self

        raise ValueError

    def can_execute(self, parts):
        pass

    async def execute(self, ctx, parts):
        pass


class CommandTable(BaseCommand):
    def can_execute(self, parts):
        return False

    def extend(self, table):
        for cmd in table.commands:
            self.add_command(cmd)


class CommandParameter:
    def __init__(self, name, kind, default=Parameter.empty, converter=None):
        self.name = name
        self.kind = kind
        self.default = default

        self.converter = converter
        if converter is bool:
            def _bool_converter(a):
                a = str(a).lower()
                return a == "y" or a == "yes" or a == "true"

            self.converter = _bool_converter

    @classmethod
    def from_parameter(cls, p):
        return cls(
            p.name,
            p.kind,
            p.default,
            p.annotation if p.annotation != Parameter.empty else None
        )

    def parse(self, args):
        if len(args) == 0:
            if self.default != Parameter.empty:
                return self.default

            raise NotEnoughArguments(self)

        if self.kind == Parameter.VAR_POSITIONAL:
            converter = self.converter or list
            result = converter(args)
            args.clear()
            return result

        if self.kind == Parameter.KEYWORD_ONLY:
            converter = self.converter or str
            result = converter(" ".join(args))
            args.clear()
            return result

        if self.kind == Parameter.VAR_KEYWORD:
            converter = self.converter or dict
            result = converter({
                a: b
                for a, b in map(lambda ab: ab.split("="), args)
            })
            args.clear()
            return result

        converter = self.converter or str
        arg = args.pop(0)
        try:
            return converter(arg)
        except Exception as e:
            raise ConverterFailed(self, arg, e)


class Command(BaseCommand):
    def __init__(self, callback, name=None, description=None, aliases=None, hidden=False):
        super().__init__()

        self.module = None  # Gets filled by bot.add_module if this command belongs to a module
        self.checks = []

        cb = callback
        while isinstance(cb, Check):
            self.checks.append(cb)
            cb = cb.next

        self.callback = cb
        self.name = name or self.callback.__name__
        doc = getdoc(self.callback)
        self.description = description or cleandoc(doc) if doc else ""
        self.aliases = aliases or []
        self.hidden = hidden

        sig = signature(self.callback)
        self.parameters = [
            CommandParameter.from_parameter(p)
            for _, p in list(sig.parameters.items())
            if p.name != "self" and p.name != "ctx"  # Skip self and ctx
        ]

    @property
    def brief(self):
        line = self.description.splitlines()[0]
        if len(line) > 50:
            line = line[:50] + "..."

        return line

    def can_execute(self, parts):
        return True

    async def execute(self, ctx, parts):
        default = {}
        args = []
        kwargs = {}

        for parameter in self.parameters:
            if parameter.kind == Parameter.VAR_POSITIONAL:
                args.extend(parameter.parse(parts))

            elif parameter.kind == Parameter.VAR_KEYWORD:
                kwargs.update(parameter.parse(parts))

            else:
                default[parameter.name] = parameter.parse(parts)

        for check in self.checks:
            await check.run(ctx, *args, **default, **kwargs)

        if self.module is None:
            res = self.callback(ctx, *args, **default, **kwargs)

        else:
            res = self.callback(self.module, ctx, *args, **default, **kwargs)

        if isawaitable(res):
            return await res

        return res
