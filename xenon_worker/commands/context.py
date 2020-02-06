class Context:
    def __init__(self, client, msg):
        self.client = client
        self.msg = msg

    def get_channel(self):
        return self.client.get_channel(self.msg.guild_id, self.msg.channel_id)

    async def get_guild(self):
        return self.client.get_guild(self.msg.guild_id)

    def send(self, *args, **kwargs):
        return self.client.http.send_message(self.msg.channel_id, *args, **kwargs)

    def __getattr__(self, item):
        return getattr(self.msg, item)
