from .entities import *
import msgpack
from .httpd import Route
import asyncio


class MemberIterator:
    def __init__(self, client, guild, limit=None, after=None):
        self.client = client
        self.guild = guild
        self.limit = limit or 1000
        self.after = after or Snowflake("0")

        self.members = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.next()

    async def next(self):
        if self.members.empty():
            await self.fill_members()

        try:
            return self.members.get_nowait()
        except asyncio.QueueEmpty:
            raise StopAsyncIteration

    async def fill_members(self):
        if self.limit <= 0:
            return

        members = await self.client.fetch_members(self.guild, min(self.limit, 1000), self.after)
        if not members:
            return

        self.after = members[-1]
        for member in reversed(members):
            await self.members.put(member)

        self.limit -= 1000


class MessageIterator:
    def __init__(self, client, channel, limit=None, before=None, after=None, around=None):
        self.client = client
        self.channel = channel
        self.limit = limit or 100
        self.before = before
        self.after = after or Snowflake("0")
        self.around = around

        self.messages = asyncio.Queue()

        if after:
            self._retrieve_messages = self._retrieve_messages_after

        elif around:
            self._retrieve_messages = self._retrieve_messages_around

        else:
            self._retrieve_messages = self._retrieve_messages_before

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.next()

    async def next(self):
        if self.messages.empty():
            await self.fill_messages()

        try:
            return self.messages.get_nowait()
        except asyncio.QueueEmpty:
            raise StopAsyncIteration

    async def fill_messages(self):
        if self.limit <= 0:
            return

        messages = await self._retrieve_messages()
        for message in messages:
            await self.messages.put(message)

        self.limit -= 100

    async def _retrieve_messages(self):
        pass

    async def _retrieve_messages_after(self):
        pass

    async def _retrieve_messages_before(self):
        messages = await self.client.fetch_messages(self.channel, min(self.limit, 100), before=self.before)
        if not messages:
            return []

        self.before = messages[-1]
        return messages

    async def _retrieve_messages_around(self):
        pass


class HttpMixin:
    async def send_message(self, channel, *args, **kwargs):
        result = await self.http.send_message(channel.id, *args, **kwargs)
        return Message(result)

    async def send_files(self, channel, *args, **kwargs):
        result = await self.http.send_files(channel.id, *args, **kwargs)
        return Message(result)

    async def edit_message(self, message, *args, **kwargs):
        result = await self.http.edit_message(message.channel_id, message.id, *args, **kwargs)
        return Message(result)

    async def delete_message(self, message, *args, **kwargs):
        return await self.http.delete_message(message.channel_id, message.id, *args, **kwargs)

    async def fetch_message(self, channel, message_id):
        result = await self.http.get_message(channel.id, message_id)
        return Message(result)

    async def fetch_messages(self, channel, limit=100, before=None, after=None, around=None):
        # Only works for up to 100 messages. See iter_messages
        before = before.id if before else None
        after = after.id if after else None
        around = around.id if around else None
        result = await self.http.logs_from(channel, limit, before, after, around)
        return [Message(r) for r in result]

    def iter_messages(self, channel, limit=100, before=None, after=None, around=None):
        return MessageIterator(self, channel.id, limit, before, after, around)

    async def fetch_pins(self, channel):
        result = await self.http.pins_from(channel.id)
        return [Message(r) for r in result]

    async def pin_message(self, message):
        return await self.http.pin_message(message.channel_id, message.id)

    async def start_dm(self, user):
        result = await self.http.start_private_message(user.id)
        return Channel(result)

    async def add_reaction(self, message, *args, **kwargs):
        return await self.http.add_reaction(message.channel_id, message.id, *args, **kwargs)

    async def remove_reaction(self, message, *args, **kwargs):
        return await self.http.remove_reaction(message.channel_id, message.id, *args, **kwargs)

    async def clear_reactions(self, message, *args, **kwargs):
        return await self.http.clear_reactions(message.channel_id, message.id, *args, **kwargs)

    async def fetch_user(self, user_id):
        result = await self.http.get_user(user_id)
        return User(result)

    async def fetch_member(self, guild, member_id):
        result = await self.http.get_member(guild.id, member_id)
        return Member(result)

    async def fetch_members(self, guild, limit=1000, after=None):
        """
        Only works for up to 1000 members. See iter_members
        """
        after = after.id if after else None
        result = await self.http.get_members(guild.id, limit, after)
        return [Member(r) for r in result]

    async def edit_member(self, guild, member, *args, **kwargs):
        return await self.http.edit_member(guild.id, member.id, *args, **kwargs)

    async def add_role(self, guild, member, role, **kwargs):
        return await self.http.add_role(guild.id, member.id, role.id, **kwargs)

    async def remove_role(self, guild, member, role, **kwargs):
        return await self.http.remove_role(guild.id, member.id, role.id, **kwargs)

    def iter_members(self, guild, limit=1000, after=None):
        return MemberIterator(self, guild, limit, after)

    async def fetch_roles(self, guild):
        result = await self.http.get_roles(guild.id)
        return [Role(r) for r in result]

    async def fetch_guild(self, guild_id):
        result = await self.http.get_guild(guild_id)
        return Channel(result)

    async def fetch_bans(self, guild):
        return await self.http.get_bans(guild.id)

    async def fetch_ban(self, guild, user):
        return await self.http.get_ban(user.id, guild.id)

    async def ban_user(self, guild, user, *args, **kwargs):
        return await self.http.ban(user.id, guild.id, *args, **kwargs)

    async def unban_user(self, guild, user, *args, **kwargs):
        return await self.http.unban(user.id, guild.id, *args, **kwargs)

    async def fetch_channel(self, channel_id):
        result = await self.http.get_channel(channel_id)
        return Channel(result)

    async def create_webhook(self, channel, *args, **kwargs):
        result = await self.http.create_webhook(channel.id, *args, **kwargs)
        return Webhook(result)

    async def delete_webhook(self, webhook):
        return await self.http.delete_webhook(webhook.id, webhook.token)

    async def execute_webhook(self, webhook, *args, **kwargs):
        result = await self.http.execute_webhook(webhook.id, webhook.token, *args, **kwargs)
        if isinstance(result, dict):
            return Message(result)

        else:
            return None

    async def delete_webhook_message(self, webhook, *args, **kwargs):
        return await self.http.delete_webhook_message(webhook.id, webhook.token, *args, **kwargs)

    async def create_channel(self, guild, *args, **kwargs):
        result = await self.http.create_channel(guild.id, *args, **kwargs)
        return Channel(result)

    async def delete_channel(self, channel, *args, **kwargs):
        return await self.http.delete_channel(channel.id, *args, **kwargs)

    async def create_role(self, guild, *args, **kwargs):
        result = await self.http.create_role(guild.id, *args, **kwargs)
        return Role(result)

    async def edit_role(self, role, *args, **kwargs):
        result = await self.http.edit_role(role.guild_id, role.id, *args, **kwargs)
        return Role(result)

    async def delete_role(self, role, *args, **kwargs):
        return await self.http.delete_role(role.guild_id, role.id, *args, **kwargs)

    async def leave_guild(self, guild):
        return await self.http.leave_guild(guild.id)

    async def app_info(self):
        return await self.http.application_info()

    async def edit_guild(self, guild, *args, **kwargs):
        return await self.http.edit_guild(guild.id, *args, **kwargs)

    async def bot_gateway(self):
        return await self.http.request(Route('GET', '/gateway/bot'))

    async def create_invite(self, channel, **kwargs):
        return await self.http.create_invite(channel.id, **kwargs)


class CacheMixin:
    async def get_full_guild(self, guild_id):
        data = await self.redis.hget(f"guilds", guild_id)
        if data is None:
            return None

        data = {
            **msgpack.unpackb(data),
            "channels": [c.to_dict() for c in await self.get_guild_channels(guild_id)],
            "roles": [r.to_dict() for r in await self.get_guild_roles(guild_id)]
        }
        return Guild(data)

    async def get_guild(self, guild_id):
        data = await self.redis.hget(f"guilds", guild_id)
        if data is None:
            return None

        return Guild(msgpack.unpackb(data))

    async def get_guild_channels(self, guild_id):
        channel_ids = await self.redis.smembers(f"guilds:{guild_id}:channels")
        return await self.get_channels(*channel_ids)

    async def get_channels(self, *channel_ids):
        return [c async for c in self.iter_channels(*channel_ids)]

    async def iter_channels(self, *channel_ids):
        raw = await self.redis.hmget('channels', *channel_ids)
        for data in raw:
            if data is not None:
                yield Channel(msgpack.unpackb(data))

    async def get_channel(self, channel_id):
        data = await self.redis.hget(f"channels", channel_id)
        if data is None:
            return None

        return Channel(msgpack.unpackb(data))

    async def get_guild_roles(self, guild_id):
        role_ids = await self.redis.smembers(f"guilds:{guild_id}:roles")
        return await self.get_roles(*role_ids)

    async def get_roles(self, *role_ids):
        return [r async for r in self.iter_roles(*role_ids)]

    async def iter_roles(self, *role_ids):
        raw = await self.redis.hmget('roles', *role_ids)
        for data in raw:
            if data is not None:
                yield Role(msgpack.unpackb(data))

    async def get_role(self, role_id):
        data = await self.redis.hget(f"roles", role_id)
        if data is None:
            return None

        return Role(msgpack.unpackb(data))

    async def get_member(self, guild_id, member_id):
        data = await self.redis.hget(f"guilds:{guild_id}:members", member_id)
        if data is None:
            return None

        return Member(msgpack.unpackb(data))

    def get_bot_member(self, guild_id):
        return self.get_member(guild_id, self.user.id)

    async def get_state(self):
        state = await self.redis.hgetall("state")
        return {
            k.decode("utf-8"): msgpack.unpackb(v)
            for k, v in state.items()
        }

    async def get_shards(self):
        state = await self.get_state()
        shard_count = state.get("shard_count", 1)

        shards = await self.redis.mget(*[f"shards:{i}" for i in range(shard_count)])
        return {
            str(i): msgpack.unpackb(v)
            for i, v in enumerate(shards)
            if v is not None
        }

    async def guild_shard(self, guild_id):
        state = await self.get_state()
        return (int(guild_id) >> 22) % int(state["shard_count"])
