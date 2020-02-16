class CommandError(Exception):
    pass


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


class NotStaff(CheckFailed):
    pass
