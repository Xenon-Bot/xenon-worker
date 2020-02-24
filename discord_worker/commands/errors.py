class CommandError(Exception):
    pass


class CommandNotFound(CommandError):
    pass


class NotEnoughArguments(CommandError):
    def __init__(self, parameter):
        self.parameter = parameter


class ConverterFailed(CommandError):
    def __init__(self, parameter, value, error):
        self.parameter = parameter
        self.value = value
        self.error = error


class CheckFailed(CommandError):
    pass


class MissingPermissions(CheckFailed):
    def __init__(self, missing):
        self.missing = missing


class BotMissingPermissions(CheckFailed):
    def __init__(self, missing):
        self.missing = missing


class NotOwner(CheckFailed):
    pass


class NotBotOwner(CheckFailed):
    pass


class NotAGuildChannel(CheckFailed):
    pass


class NotADMChannel(CheckFailed):
    pass
