from .errors import *
from ..connection.entities import ChannelType
from enum import Enum
from ..connection.errors import *


class Check:
    def __init__(self, check, next=None):
        self.next = next
        self.check = check

    def run(self, ctx, *args, **kwargs):
        return self.check(ctx, *args, **kwargs)


def has_permissions(**required):
    def predicate(callback):
        async def check(ctx, *args, **kwargs):
            # Make sure we are in a guild
            channel = await ctx.client.fetch_channel(ctx.channel_id)
            if channel is None or channel.type == ChannelType.DM or channel.type == ChannelType.GROUP_DM:
                return True

            guild = await ctx.fetch_guild()
            permissions = ctx.author.permissions_for_guild(guild)
            missing = []
            if not permissions.administrator:
                for perm in required.keys():
                    if not getattr(permissions, perm, False):
                        missing.append(perm)

            if len(missing) > 0:
                raise MissingPermissions(missing)

            return True

        return Check(check, callback)

    return predicate


def bot_has_permissions(**required):
    def predicate(callback):
        async def check(ctx, *args, **kwargs):
            # Make sure we are in a guild
            channel = await ctx.client.fetch_channel(ctx.channel_id)
            if channel is None or channel.type == ChannelType.DM or channel.type == ChannelType.GROUP_DM:
                return True

            try:
                bot_member = await ctx.fetch_bot_member()
            except NotFound:
                raise BotMissingPermissions(required.keys())

            guild = await ctx.fetch_guild()
            permissions = bot_member.permissions_for_guild(guild)
            missing = []
            if not permissions.administrator:
                for perm in required.keys():
                    if not getattr(permissions, perm, False):
                        missing.append(perm)

            if len(missing) > 0:
                raise BotMissingPermissions(missing)

            return True

        return Check(check, callback)

    return predicate


def is_owner(callback):
    async def check(ctx, *args, **kwargs):
        try:
            guild = await ctx.fetch_guild()
        except NotFound:
            raise NotOwner()

        if ctx.author.id != guild.owner_id:
            raise NotOwner()

        return True

    return Check(check, callback)


def is_bot_owner(callback):
    async def check(ctx, *args, **kwargs):
        app = await ctx.client.http.application_info()

        if ctx.author.id != app["owner"]["id"]:
            team = app.get("team")
            if team is not None:
                members = [tm["user"]["id"] for tm in team["members"]]
                if ctx.author.id in members:
                    return True

            raise NotBotOwner()

        return True

    return Check(check, callback)


def guild_only(callback):
    async def check(ctx, *args, **kwargs):
        channel = await ctx.client.fetch_channel(ctx.channel_id)
        if channel is None:
            # Probably a DM channel
            raise NotAGuildChannel()

        if channel.type not in (ChannelType.GUILD_TEXT, ChannelType.GUILD_NEWS):
            raise NotAGuildChannel()

        return True

    return Check(check, callback)


def dm_only(callback):
    async def check(ctx, *args, **kwargs):
        try:
            channel = await ctx.client.fetch_channel(ctx.channel_id)
        except NotFound:
            return True

        if channel.type != ChannelType.DM:
            raise NotADMChannel()

        return True

    return Check(check, callback)


class CooldownType(Enum):
    GLOBAL = 0
    GUILD = 1
    CHANNEL = 2
    AUTHOR = 3


class Cooldown(Check):
    def __init__(self, rate: int, per: float, bucket=CooldownType.AUTHOR, next=None):
        super().__init__(self.check, next)
        self.rate = rate
        self.per = per
        self.bucket = bucket

    def get_key(self, ctx):
        if self.bucket == CooldownType.GUILD:
            if ctx.guild_id is not None:
                key = ctx.guild_id

            else:
                key = ctx.channel_id

        elif self.bucket == CooldownType.CHANNEL:
            key = ctx.channel_id

        elif self.bucket == CooldownType.AUTHOR:
            key = ctx.author.id

        else:
            key = "*"

        return "cooldown:" + ctx.last_cmd.full_name.replace(" ", "") + ":" + key

    async def check(self, ctx, *args, **kwargs):
        key = self.get_key(ctx)
        current = int(await ctx.bot.redis.get(key) or 0)
        if current >= self.rate:
            remaining = await ctx.bot.redis.ttl(key)
            # warned key must include the user id even if the cooldown is global
            warned_key = f"{key}:{ctx.author.id}:warned"
            already_warned = await ctx.bot.redis.get(warned_key)
            if already_warned is not None:
                raise CommandOnCooldown(self.rate, self.per, self.bucket, remaining, warned=True)

            await ctx.bot.redis.setex(warned_key, self.per, 1)
            raise CommandOnCooldown(self.rate, self.per, self.bucket, remaining)

        await ctx.bot.redis.setex(key, self.per, current + 1)

    async def reset(self, ctx):
        key = self.get_key(ctx)
        await ctx.bot.redis.delete(key)


def cooldown(*args, **kwargs):
    def predicate(callback):
        return Cooldown(*args, **kwargs, next=callback)

    return predicate
