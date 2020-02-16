class Context:
    def __init__(self, client, msg):
        self.client = client
        self.msg = msg

        self._cache = {}

    @property
    def bot(self):
        return self.client

    async def get_channel(self, cache=True):
        if cache and "channel" in self._cache.keys():
            return self._cache.get("channel")

        return await self.client.get_channel(self.msg.channel_id)

    async def get_guild(self, cache=True):
        if cache and "guild" in self._cache.keys():
            return self._cache.get("guild")

        return await self.client.get_guild(self.msg.guild_id)

    async def get_bot_member(self, cache=True):
        if cache and "bot_member" in self._cache.keys():
            return self._cache.get("bot_member")

        return await self.client.get_bot_member(self.msg.guild_id)

    async def get_guild_channels(self, cache=True):
        if cache and "channels" in self._cache.keys():
            return self._cache.get("channels")

        return await self.client.get_channels(self.msg.guild_id)

    async def get_guild_roles(self, cache=True):
        if cache and "roles" in self._cache.keys():
            return self._cache.get("roles")

        return await self.client.get_roles(self.msg.guild_id)

    def send(self, *args, **kwargs):
        return self.client.http.send_message(self.msg.channel_id, *args, **kwargs)

    def __getattr__(self, item):
        return getattr(self.msg, item)
