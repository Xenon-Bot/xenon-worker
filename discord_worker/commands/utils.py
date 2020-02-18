import asyncio


class ListMenu:
    embed_kwargs = {}

    def __init__(self, ctx, msg=None):
        self.ctx = ctx
        self.msg = msg
        self.page = 0

    async def get_items(self):
        return []

    async def update(self):
        items = await self.get_items()
        if len(items) == 0 and self.page > 0:
            self.page -= 1
            await self.update()
            return

        if self.msg is None:
            self.msg = await self.ctx.send_message(embed=self.make_embed(items))

        else:
            await self.ctx.client.edit_message(self.msg, embed=self.make_embed(items))

    def make_embed(self, items):
        return {
            "title": "List",
            "fields": [
                {
                    "name": name,
                    "value": value,
                    "inline": False
                }
                for name, value in items
            ],
            "footer": {
                "text": f"Page {self.page + 1}"
            },
            **self.embed_kwargs
        }

    async def start(self):
        await self.update()
        options = ["◀", "❎", "▶"]
        for option in options:
            await self.ctx.bot.add_reaction(self.msg, option)

        while True:
            try:
                data, = await self.ctx.client.wait_for(
                    event="message_reaction_add",
                    shard_id=self.ctx.shard_id,
                    check=lambda d: d["user_id"] == self.ctx.author.id and
                                    d["message_id"] == self.msg.id and
                                    d["emoji"]["name"] in options,
                    timeout=30,
                )

                emoji = data["emoji"]["name"]
                try:
                    await self.ctx.bot.remove_reaction(self.msg, emoji, data["user_id"])
                except Exception:
                    pass

                if str(emoji) == options[0]:
                    if self.page > 0:
                        self.page -= 1

                elif str(emoji) == options[2]:
                    self.page += 1

                else:
                    raise asyncio.TimeoutError

            except asyncio.TimeoutError:
                await self.ctx.client.clear_reactions(self.msg)
                return

            await self.update()
