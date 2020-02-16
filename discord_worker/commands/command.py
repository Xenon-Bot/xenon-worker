from inspect import cleandoc, getdoc, Parameter, signature, ismethod, isawaitable
from abc import ABC

from .checks import Check


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
                res = cmd.find_command(parts[1:])
            except ValueError:
                continue

            else:
                parts.pop(0)
                return res

        if self.can_execute(parts):
            return self

        raise ValueError

    def can_execute(self, parts):
        pass

    async def execute(self, args, ctx, parts):
        pass


class CommandTable(BaseCommand):
    def can_execute(self, parts):
        return False

    def extend(self, table):
        for cmd in table.commands:
            self.add_command(cmd)


class CommandParameter:
    def __init__(self, name, kind, converter=None):
        self.name = name
        self.kind = kind

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
            p.annotation if p.annotation != Parameter.empty else None
        )

    def parse(self, args):
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
        return converter(args.pop(0))


class Command(BaseCommand):
    def __init__(self, callback, name=None, description=None, aliases=None, hidden=False):
        super().__init__()
        cb = callback
        if isinstance(cb, Check):
            cb = callback.drill()

        self.callback = callback
        self.name = name or cb.__name__
        doc = getdoc(cb)
        self.description = description or cleandoc(doc) if doc else ""
        self.aliases = aliases or []
        self.hidden = hidden

        sig = signature(cb)
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

    async def execute(self, pre_ctx, ctx, parts):
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

        callback = self.callback
        while isinstance(callback, Check):
            await callback.run(ctx, *args, **default, **kwargs)
            callback = callback.next  # Get the next check or the actual callback

        res = callback(*pre_ctx, ctx, *args, **default, **kwargs)
        if isawaitable(res):
            return await res

        return res
