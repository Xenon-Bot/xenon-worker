import asyncio
from connection import RabbitClient
from connection import Message


class Client(RabbitClient):
    async def on_message_create(self, data):
        msg = Message(data)
        print(msg.content)
        if msg.content == "x!asdasd":
            guild = await self.get_guild(msg.guild_id)
            await self.http.send_message(msg.channel_id, "The guild name is %s" % guild.name)


async def test():
    client = Client("amqp://guest:guest@localhost/")
    await client.start(open("token.txt").read(), "command.normal")


loop = asyncio.get_event_loop()
loop.create_task(test())
loop.run_forever()
