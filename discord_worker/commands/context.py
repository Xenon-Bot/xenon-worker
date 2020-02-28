class Context:
    def __init__(self, client, shard_id, msg):
        self.client = client
        self.shard_id = shard_id
        self.msg = msg

        self.last_cmd = None  # Filled by cmd.execute

    @property
    def bot(self):
        return self.client

    @property
    def f(self):
        return self.client.f

    async def get_channel(self):
        return await self.client.get_channel(self.msg.channel_id)

    async def get_guild(self):
        return await self.client.get_guild(self.msg.guild_id)

    async def get_full_guild(self, cache=True):
        return await self.client.get_full_guild(self.msg.guild_id)

    async def get_bot_member(self):
        return await self.client.get_bot_member(self.msg.guild_id)

    async def get_guild_channels(self):
        return await self.client.get_guild_channels(self.msg.guild_id)

    async def get_guild_roles(self):
        return await self.client.get_guild_roles(self.msg.guild_id)

    def f_send(self, *args, **kwargs):
        return self.bot.f_send(self.msg.channel_id, *args, **kwargs)

    def send_message(self, *args, **kwargs):
        return self.client.send_message(self.msg.channel_id, *args, **kwargs)

    def send(self, *args, **kwargs):
        return self.send_message(*args, **kwargs)

    def invoke(self, cmd):
        return self.client.invoke(self, cmd)

    def __getattr__(self, item):
        return getattr(self.msg, item)
