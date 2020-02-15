import asyncio
from commands import RabbitBot
from commands import Module


bot = RabbitBot("#!", "amqp://guest:guest@localhost/")
# Permissions class & Overwrites


@bot.command()
async def admin(ctx):
    guild = await ctx.get_guild()
    channel = await ctx.get_channel()
    permissions = ctx.author.permissions_for_channel(guild, channel)
    print(permissions)
    if permissions.administrator:
        await ctx.send("You are admin")

    else:
        await ctx.send("You are not admin")


class TestModule(Module):
    @Module.command()
    async def yeet(self, ctx):
        await ctx.send("YEET!")

    @Module.listener()
    async def on_message_create(self, data):
        print(data)


async def test():
    bot.add_module(TestModule(bot))
    await bot.start("main")


loop = asyncio.get_event_loop()
loop.create_task(test())
loop.run_forever()
