from .errors import *


class Converter:
    def __init__(self, parameter, arg):
        self.parameter = parameter
        self.arg = arg

    def __call__(self, ctx):
        return self._convert(ctx)

    def _convert(self, ctx):
        return self.arg


class UserConverter(Converter):
    async def _convert(self, ctx):
        try:
            user = await ctx.bot.fetch_user(self.arg)
        except Exception:
            raise ConverterFailed(self.parameter, self.arg, "User not found")

        return user


class GuildConverter(Converter):
    async def _convert(self, ctx):
        guild = await ctx.bot.get_guild(self.arg)
        if guild is None:
            raise ConverterFailed(self.parameter, self.arg, "Guild not found")

        return guild


class ChannelConverter(Converter):
    async def _convert(self, ctx):
        cursor = ctx.bot.get_channels(ctx.guild_id, {"$or": [
            {
                "_id": self.arg
            },
            {
                "name": self.arg
            }
        ]})

        channel = None
        async for ch in cursor:
            channel = ch
            break

        if channel is None:
            raise ConverterFailed(self.parameter, self.arg, "Channel not found")

        return channel


class RoleConverter(Converter):
    async def _convert(self, ctx):
        cursor = ctx.bot.get_roles(ctx.guild_id, {"$or": [
            {
                "_id": self.arg
            },
            {
                "name": self.arg
            }
        ]})

        role = None
        async for r in cursor:
            role = r
            break

        if role is None:
            raise ConverterFailed(self.parameter, self.arg, "Role not found")

        return role
