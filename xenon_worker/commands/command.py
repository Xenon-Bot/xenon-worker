from inspect import cleandoc, getdoc, Parameter, signature, isclass, isawaitable
from abc import ABC

from .checks import Check, Cooldown
from .errors import *
from .converters import Converter


class BaseCommand(ABC):
    def __init__(self, *commands, keep_checks=True):
        self.parent = None  # Gets filled up by BaseCommand.add_command if this command is not the top level one
        self._checks = []
        self._cooldown = None
        self.commands = list(commands)
        self.keep_checks = keep_checks

    def set_cooldown(self, cooldown: Cooldown):
        self._cooldown = cooldown

    async def reset_cooldown(self):
        if self._cooldown is not None:
            await self._cooldown.reset()

    def add_check(self, check: Check):
        self._checks.append(check)

    @property
    def checks(self):
        # Include checks from the parent
        if self.parent is not None and self.keep_checks:
            yield from self.parent.checks

        yield from self._checks

    @property
    def full_name(self):
        return ""

    def add_command(self, command):
        command.parent = self
        self.commands.append(command)

    def remove_command(self, command):
        self.commands.remove(command)

    def command(self, *args, **kwargs):
        def _predicate(callback):
            cmd = Command(callback, *args, **kwargs)
            self.add_command(cmd)
            return cmd

        return _predicate

    def command_tree(self):
        result = []
        for cmd in self.commands:
            result.append((cmd, cmd.command_tree()))

        return result

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

        raise CommandNotFound()

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
        if self.default == Parameter.empty:
            if self.kind == Parameter.KEYWORD_ONLY:
                self.default = ""

            elif self.kind == Parameter.VAR_POSITIONAL:
                self.default = tuple()

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
            converter = self.converter or tuple
            arg = tuple(args)
            args.clear()

        elif self.kind == Parameter.KEYWORD_ONLY:
            converter = self.converter or str
            arg = " ".join(args)
            args.clear()

        elif self.kind == Parameter.VAR_KEYWORD:
            converter = self.converter or dict
            arg = {
                a: b
                for a, b in map(lambda ab: ab.split("="), args)
            }
            args.clear()

        else:
            converter = self.converter or str
            arg = args.pop(0)

        if isclass(converter) and issubclass(converter, Converter):
            return converter(self, arg)

        else:
            try:
                return converter(arg)
            except Exception as e:
                raise ConverterFailed(self, arg, str(e))


class Command(BaseCommand):
    def __init__(self, callback, name=None, description=None, aliases=None, hidden=False, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.module = None  # Gets filled by fill_module in Bot.add_module if this commands belongs to a module

        cb = callback
        # Go through all decorators until we reach the actual callback
        while isinstance(cb, Check):
            if isinstance(cb, Cooldown):
                self.set_cooldown(cb)
            else:
                self.add_check(cb)

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
        lines = self.description.splitlines()
        if len(lines) == 0:
            return ""

        line = lines[0]
        if len(line) > 50:
            line = line[:50] + "..."

        return line

    @property
    def full_name(self):
        if self.parent is None:
            return self.name

        else:
            return (self.parent.full_name + " " + self.name).strip()

    @property
    def usage(self):
        result = ""
        for param in self.parameters:
            name = param.name
            if param.kind == Parameter.VAR_POSITIONAL:
                name = "*" + param.name

            elif param.kind == Parameter.KEYWORD_ONLY:
                name = param.name + "..."

            elif param.kind == Parameter.VAR_KEYWORD:
                name = "**" + param.name

            if param.default != Parameter.empty:
                if param.default is None:
                    result += " [%s]" % name

                else:
                    result += " [%s=%s]" % (name, str(param.default))

            else:
                result += " <%s>" % name

        return self.full_name + result

    def fill_module(self, module):
        self.module = module
        for cmd in self.commands:
            cmd.fill_module(module)

    def can_execute(self, parts):
        return True

    async def execute(self, ctx, parts):
        ctx.last_cmd = self
        default = []
        args = []
        kwargs = {}

        for parameter in self.parameters:
            if parameter.kind == Parameter.VAR_POSITIONAL:
                args.extend(parameter.parse(parts))

            elif parameter.kind == Parameter.VAR_KEYWORD:
                kwargs.update(parameter.parse(parts))

            elif parameter.kind == Parameter.KEYWORD_ONLY:
                kwargs[parameter.name] = parameter.parse(parts)

            else:
                default.append(parameter.parse(parts))

        for check in self.checks:
            await check.run(ctx, *default, *args, **kwargs)

        if self._cooldown is not None:
            await self._cooldown.run(ctx, *default, *args, **kwargs)

        if self.module is None:
            res = self.callback(ctx, *default, *args, **kwargs)

        else:
            res = self.callback(self.module, ctx, *default, *args, **kwargs)

        if isawaitable(res):
            return await res

        return res
