import functools

from .errors import *


class Check:
    def __init__(self, callback, check):
        self.next = callback
        self.check = check

    def run(self, ctx, *args, **kwargs):
        return self.check(ctx, *args, **kwargs)


def has_permissions(**required):
    def predicate(callback):
        @functools.wraps(callback)
        async def check(ctx, *args, **kwargs):
            guild = await ctx.get_guild()
            permissions = ctx.author.permissions_for_guild(guild)
            missing = []
            for perm in required.keys():
                if not getattr(permissions, perm, False):
                    missing.append(perm)

            if len(missing) > 0:
                raise MissingPermissions(missing)

            return True

        return Check(callback, check)

    return predicate


def bot_has_permissions(**required):
    def predicate(callback):
        @functools.wraps(callback)
        async def check(ctx, *args, **kwargs):
            bot_member = await ctx.get_bot_member()
            if bot_member is None:
                raise BotMissingPermissions(required.keys())

            guild = await ctx.get_guild()
            permissions = bot_member.permissions_for_guild(guild)
            missing = []
            for perm in required.keys():
                if not getattr(permissions, perm, False):
                    missing.append(perm)

            if len(missing) > 0:
                raise BotMissingPermissions(missing)

            return True

        return Check(callback, check)

    return predicate


def is_owner(callback):
    pass


def is_staff(level=1):
    pass
