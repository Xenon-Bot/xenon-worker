from .entities import *


class HttpMixin:
    async def send_message(self, channel, *args, **kwargs):
        if isinstance(channel, Channel):
            channel = channel.id

        result = await self.http.send_message(channel, *args, **kwargs)
        return Message(result)

    async def edit_message(self, message, *args, **kwargs):
        result = await self.http.edit_message(message.channel_id, message.id, *args, **kwargs)
        return Message(result)

    async def delete_message(self, message, *args, **kwargs):
        return await self.http.delete_message(message.channel_id, message.id, *args, **kwargs)

    async def add_reaction(self, message, *args, **kwargs):
        return await self.http.add_reaction(message.channel_id, message.id, *args, **kwargs)

    async def remove_reaction(self, message, *args, **kwargs):
        return await self.http.remove_reaction(message.channel_id, message.id, *args, **kwargs)

    async def clear_reactions(self, message):
        return await self.http.clear_reactions(message.channel_id, message.id)


class CacheMixin:
    async def get_guild(self, guild_id):
        guild = await self.cache.guilds.find_one({"_id": guild_id})
        channels = self.cache.channels.find({"guild_id": guild_id})
        roles = self.cache.roles.find({"guild_id": guild_id})
        data = {
            **guild,
            "channels": [c async for c in channels],
            "roles": [r async for r in roles]
        }
        return Guild(data)

    async def get_channels(self, guild_id, **filter_):
        async for channel in self.cache.channels.find({"guild_id": guild_id, **filter_}):
            yield Channel(channel)

    async def get_channel(self, channel_id):
        channel = await self.cache.channels.find_one({"_id": channel_id})
        if channel is None:
            return None

        return Channel(channel) if channel is not None else None

    async def get_roles(self, guild_id, **filter_):
        async for role in self.cache.roles.find({"guild_id": guild_id, **filter_}):
            yield Role(role)

    async def get_role(self, role_id):
        role = await self.cache.roles.find_one({"_id": role_id})
        if role is None:
            return None

        return Role(role)

    async def get_member(self, guild_id, member_id):
        member = await self.cache.members.find_one({"guild_id": guild_id, "user.id": member_id})
        if member is None:
            return None

        return Member(member)

    def get_bot_member(self, guild_id):
        return self.get_member(guild_id, self.user.id)
