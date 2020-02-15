import aiormq
import json
import asyncio
import traceback
from motor.motor_asyncio import AsyncIOMotorClient

from .httpd import HTTPClient
from .entities import Guild, Channel, Role, Member, User


class RabbitClient:
    def __init__(self, rabbit_url, mongo_url, loop=None):
        self.url = rabbit_url
        self.user = None
        self.loop = loop or asyncio.get_event_loop()
        self.connection = None
        self.channel = None
        self.queue = None
        self.listeners = {}
        self.static_subscriptions = set()

        self.http = HTTPClient(loop=loop)
        self.mongo = AsyncIOMotorClient(host=mongo_url)
        self.cache = self.mongo.cache

    def _process_listeners(self, key, data):
        listeners = self.listeners.get(key, [])

        # Dispatch shard wildcards too
        parts = key.split(".")
        if len(parts) == 2:
            listeners.extend(self.listeners.get("*." + parts[1], []))

        to_remove = []
        for i, (future, check) in enumerate(listeners):
            if future.cancelled():
                to_remove.append(i)

            try:
                result = check(data)
            except Exception as e:
                future.set_exception(e)
                to_remove.append(i)

            else:
                if result:
                    future.set_result(data)
                    to_remove.append(i)

        for i in sorted(to_remove, reverse=True):
            del listeners[i]

        self.loop.create_task(self.unsubscribe(key))

    def dispatch(self, event, data):
        try:
            coro = getattr(self, "on_" + event)
        except AttributeError:
            pass

        else:
            self.loop.create_task(coro(data))

    def has_listener(self, key):
        return len(self.listeners.get(key, [])) > 0

    async def _message_received(self, msg):
        payload = json.loads(msg.body)
        shard_id, event, data = payload["shard_id"], payload["event"], payload["data"]
        ev = event.lower()
        self._process_listeners("%s.%s" % (shard_id, ev), data)
        self.dispatch(ev, data)

    def _subscribe_dyn(self, routing_key):
        return self.channel.queue_bind(self.queue.queue, "events", routing_key)

    def _unsubscribe_dyn(self, routing_key, force=False):
        if routing_key in self.static_subscriptions:
            return False

        return self.unsubscribe(routing_key, force)

    def subscribe(self, routing_key):
        self.static_subscriptions.add(routing_key)
        return self.channel.queue_bind(self.queue.queue, "events", routing_key)

    def unsubscribe(self, routing_key, force=False):
        if self.has_listener(routing_key) and not force:
            return False

        try:
            self.static_subscriptions.remove(routing_key)
        except KeyError:
            pass

        return self.channel.queue_unbind(self.queue.queue, "events", routing_key)

    async def wait_for(self, shard_id, event, check=None, timeout=None):
        future = self.loop.create_future()
        if check is None:
            def _check(*args):
                return True

            check = _check

        key = "%s.%s" % (shard_id or "*", event.lower())
        if key not in self.listeners.keys():
            self.listeners[key] = []

        listeners = self.listeners[key]

        listeners.append((future, check))
        await self.subscribe(key)
        return await asyncio.wait_for(future, timeout)

    async def get_guild(self, guild_id):
        guild = await self.cache.guilds.find_one({"_id": guild_id})
        channels = self.get_channels(guild_id)
        roles = self.get_roles(guild_id)
        data = {
            **guild,
            "channels": [c async for c in channels],
            "roles": [r async for r in roles]
        }
        return Guild(data)

    def get_channels(self, guild_id, **filter_):
        return self.cache.channels.find({"guild_id": guild_id, **filter_})

    async def get_channel(self, channel_id):
        channel = await self.cache.channels.find_one({"_id": channel_id})
        if channel is None:
            return None

        return Channel(channel) if channel is not None else None

    def get_roles(self, guild_id, **filter_):
        return self.cache.roles.find({"guild_id": guild_id, **filter_})

    async def get_role(self, role_id):
        role = await self.cache.roles.find_one({"_id": role_id})
        if role is None:
            return None

        return Role(role)

    async def get_member(self, guild_id, member_id):
        member = await self.cache.members.find_one({"guild_id": guild_id, "id": member_id})
        if member is None:
            return None

        return Member(member)

    def get_bot_member(self, guild_id):
        return self.get_member(guild_id, self.user.id)

    async def start(self, command_queue, subscriptions=None):
        try:
            user_data = await self.http.static_login()
            self.user = User(user_data)

            self.connection = await aiormq.connect(self.url)
            self.channel = await self.connection.channel()
            self.queue = await self.channel.queue_declare(queue='', arguments={"x-max-length": 1000}, exclusive=True)
            for subscription in subscriptions or []:
                await self.channel.queue_bind(self.queue.queue, "events", subscription)
                self.static_subscriptions.add(subscription)

            await self.channel.basic_consume(self.queue.queue, self._message_received, no_ack=True)
            await self.channel.queue_declare(queue=command_queue, arguments={"x-max-length": 10000})
            await self.channel.basic_consume(command_queue, self._message_received, no_ack=True)

        except ConnectionError:
            traceback.print_exc()
            await asyncio.sleep(5)
            return await self.start(command_queue, subscriptions)

    def run(self, *args, **kwargs):
        self.loop.create_task(self.start(*args, **kwargs))
        self.loop.run_forever()
