class Context:
    def __init__(self, client, msg):
        self.client = client
        self.msg = msg

    async def get_channel(self):
        pass

    async def get_guild(self):
        pass

    def send(self, *args, **kwargs):
        return self.client.http.send_message(self.msg.channel_id, *args, **kwargs)

    def __getattr__(self, item):
        return getattr(self.msg, item)
