from ..connection.entities import Snowflake


class Context:
    def __init__(self, client, shard_id, msg):
        self.client = client
        self.shard_id = shard_id
        self.msg = msg

        self.last_cmd = None  # Filled by cmd.execute

        self._guild = None
        self._full_guild = None

    @property
    def bot(self):
        return self.client

    @property
    def f(self):
        return self.client.f

    async def get_channel(self):
        return await self.client.get_channel(self.msg.channel_id)

    async def fetch_channel(self):
        return await self.client.fetch_channel(self.msg.channel_id)

    async def get_guild(self, cache=True):
        if cache and self._guild:
            return self._guild

        self._guild = await self.client.get_guild(self.msg.guild_id)
        return self._guild

    async def fetch_guild(self, cache=True):
        if cache and self._guild:
            return self._guild

        self._guild = await self.client.fetch_guild(self.msg.guild_id)
        return self._guild

    async def get_full_guild(self, cache=True):
        if cache and self._full_guild:
            return self._full_guild

        self._full_guild = await self.client.get_full_guild(self.msg.guild_id)
        return self._full_guild

    async def fetch_full_guild(self, cache=True):
        if cache and self._full_guild:
            return self._full_guild

        self._full_guild = await self.client.fetch_full_guild(self.msg.guild_id)
        return self._full_guild

    async def get_bot_member(self):
        return await self.client.get_bot_member(self.msg.guild_id)

    async def fetch_bot_member(self):
        return await self.client.fetch_bot_member(Snowflake(self.msg.guild_id))

    async def get_guild_channels(self):
        return await self.client.get_guild_channels(self.msg.guild_id)

    async def get_guild_roles(self):
        return await self.client.get_guild_roles(self.msg.guild_id)

    def f_send(self, *args, **kwargs):
        return self.bot.f_send(Snowflake(self.msg.channel_id), *args, **kwargs)

    def send_message(self, *args, **kwargs):
        return self.client.send_message(Snowflake(self.msg.channel_id), *args, **kwargs)

    def send(self, *args, **kwargs):
        return self.send_message(*args, **kwargs)

    def invoke(self, cmd):
        return self.client.invoke(self, cmd)

    def __getattr__(self, item):
        return getattr(self.msg, item)
