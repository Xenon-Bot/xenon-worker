import aiormq
import json
import asyncio
import aioredis

from httpd import HTTPClient
from entities import Guild, Channel, Role, Member, User


class RabbitClient:
    def __init__(self, url, loop=None):
        self.url = url
        self.user = None
        self.loop = loop or asyncio.get_event_loop()
        self.connection = None
        self.channel = None
        self.queue = None
        self.listeners = {}
        self.static_subscriptions = set()

        self.http = HTTPClient(loop=loop)
        self.redis = None

    def _process_listeners(self, key, data):
        listeners = self.listeners.get(key, [])
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
        guild = await self.redis.hget("guilds", guild_id)
        channels = await self.redis.hgetall("%s.channels" % guild_id)
        roles = await self.redis.hgetall("%s.roles" % guild_id)
        data = {
            **json.loads(guild),
            "channels": [json.loads(c) for c in channels.values()],
            "roles": [json.loads(c) for c in roles.values()]
        }
        return Guild(data)

    async def get_channel(self, guild_id, channel_id):
        channel = await self.redis.hget("%s.channels" % guild_id, channel_id)
        if channel is None:
            return None

        return Channel(json.loads(channel)) if channel is not None else None

    async def get_role(self, guild_id, role_id):
        role = await self.redis.hget("%s.roles" % guild_id, role_id)
        if role is None:
            return None

        return Role(json.loads(role))

    async def get_member(self, guild_id, member_id):
        member = await self.redis.hget("%s.members" % guild_id, member_id)
        if member is None:
            return None

        return Member(json.loads(member))

    def get_bot_member(self, guild_id):
        return self.get_member(guild_id, self.user.id)

    def get_shards(self):
        return self.redis.hgetall("shards")

    async def get_shard_count(self):
        return int(await self.redis.get("shard_count") or 1)

    def get_guild_count(self):
        return self.redis.hlen("guilds")

    async def get_guild_counts(self):
        shard_count = await self.get_shard_count()
        guilds_ids = await self.redis.hkeys("guilds")
        result = {str(si): 0 for si in range(shard_count)}
        for guild_id in guilds_ids:
            shard_id = (int(guild_id) >> 22) % shard_count
            result[str(shard_id)] += 1

        return result

    async def start(self, discord_token, command_queue, subscriptions=None):
        user_data = await self.http.static_login(discord_token, bot=True)
        self.user = User(user_data)

        self.redis = await aioredis.create_redis_pool('redis://localhost')
        self.connection = await aiormq.connect(self.url)
        self.channel = await self.connection.channel()
        self.queue = await self.channel.queue_declare(queue='', arguments={"x-max-length": 1000}, exclusive=True)
        for subscription in subscriptions or []:
            await self.channel.queue_bind(self.queue.queue, "events", subscription)
            self.static_subscriptions.add(subscription)

        await self.channel.basic_consume(self.queue.queue, self._message_received, no_ack=True)
        await self.channel.basic_consume(command_queue, self._message_received, no_ack=True)
