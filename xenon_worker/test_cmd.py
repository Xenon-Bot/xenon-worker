import asyncio
import config
from commands.bot import RabbitBot
from commands.module import Module


bot = RabbitBot("x!", "amqp://guest:guest@localhost/")
# Permissions class & Overwrites


@bot.command()
async def jan(ctx):
    await ctx.send("Ich bin ein Jan!")


@jan.command()
async def mueller(ctx):
    await ctx.send("Ich bin ein Jan Müller!")


class TestModule(Module):
    @Module.command()
    async def yeet(self, ctx):
        await ctx.send("YEET!")

    @Module.listener()
    async def on_message_create(self, data):
        print(data)


async def test():
    bot.add_module(TestModule(bot))
    await bot.start(config.token, "command.normal")


loop = asyncio.get_event_loop()
loop.create_task(test())
loop.run_forever()
