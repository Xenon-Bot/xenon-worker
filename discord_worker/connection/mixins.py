from .entities import *
import msgpack
from .httpd import Route


class HttpMixin:
    async def send_message(self, channel, *args, **kwargs):
        result = await self.http.send_message(channel.id, *args, **kwargs)
        return Message(result)

    async def edit_message(self, message, *args, **kwargs):
        result = await self.http.edit_message(message.channel_id, message.id, *args, **kwargs)
        return Message(result)

    async def delete_message(self, message, *args, **kwargs):
        return await self.http.delete_message(message.channel_id, message.id, *args, **kwargs)

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

    async def fetch_message(self, channel, message_id):
        result = await self.http.get_message(channel.id, message_id)
        return Message(result)

    async def fetch_member(self, guild, member_id):
        result = await self.http.get_member(guild.id, member_id)
        return Member(result)

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
        shards = await self.redis.hgetall("shards")
        return {
            k.decode("utf-8"): msgpack.unpackb(v)
            for k, v in shards.items()
        }

    async def guild_shard(self, guild_id):
        state = await self.get_state()
        return (int(guild_id) >> 22) % int(state["shard_count"])
