from .errors import *
from ..connection.entities import Snowflake
import re


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
            mention = re.match(r"^<@!?(?P<id>\d+)>$", self.arg)
            if mention:
                user_id = mention.group("id")

            else:
                user_id = self.arg

            user = await ctx.bot.fetch_user(user_id)
        except Exception:
            raise ConverterFailed(self.parameter, self.arg, "User not found")

        return user


class MemberConverter(Converter):
    async def _convert(self, ctx):
        try:
            mention = re.match(r"^<@!?(?P<id>\d+)>$", self.arg)
            if mention:
                member_id = mention.group("id")

            else:
                member_id = self.arg

            member = await ctx.bot.fetch_member(Snowflake(ctx.guild_id), member_id)
        except Exception:
            raise ConverterFailed(self.parameter, self.arg, "Member not found")

        return member


class GuildConverter(Converter):
    async def _convert(self, ctx):
        guild = await ctx.bot.get_guild(self.arg)
        if guild is None:
            raise ConverterFailed(self.parameter, self.arg, "Guild not found")

        return guild


class FullGuildConverter(Converter):
    async def _convert(self, ctx):
        guild = await ctx.bot.get_full_guild(self.arg)
        if guild is None:
            raise ConverterFailed(self.parameter, self.arg, "Guild not found")

        return guild


class ChannelConverter(Converter):
    async def _convert(self, ctx):
        mention = re.match(r"^<#(?P<id>\d+)>$", self.arg)
        if mention:
            channel_id = mention.group("id")

        else:
            channel_id = self.arg

        channel = await ctx.bot.get_channel(channel_id)
        if channel is None:
            raise ConverterFailed(self.parameter, self.arg, "Channel not found")

        return channel


class RoleConverter(Converter):
    async def _convert(self, ctx):
        mention = re.match(r"^<@&(?P<id>\d+)>$", self.arg)
        if mention:
            role_id = mention.group("id")

        else:
            role_id = self.arg

        role = await ctx.bot.get_role(role_id)
        if role is None:
            raise ConverterFailed(self.parameter, self.arg, "Role not found")

        return role
