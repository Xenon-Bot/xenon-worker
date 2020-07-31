import aiormq
import msgpack
import asyncio
import traceback
from motor.motor_asyncio import AsyncIOMotorClient
import aioredis
import aiohttp

from .httpd import HTTPClient
from .entities import User
from .mixins import HttpMixin, CacheMixin


class Event:
    def __init__(self, name, shard_id="*"):
        self.shard_id = shard_id
        self.name = name

    def __str__(self):
        return f"{self.shard_id}.{self.name}"


class RabbitClient(CacheMixin, HttpMixin):
    def __init__(self, rabbit_url, mongo_url, redis_url, loop=None):
        super().__init__()
        self.url = rabbit_url
        self.user = None
        self.loop = loop or asyncio.get_event_loop()
        self.connection = None
        self.channel = None
        self.queue = None
        self.s_queue = None
        self.redis_url = redis_url
        self.redis = None
        self.listeners = {}
        self.static_subscriptions = set()
        self.session = None

        self.http = HTTPClient(loop=loop)
        self.mongo = AsyncIOMotorClient(host=mongo_url)

    def _process_listeners(self, event, *args, **kwargs):
        listeners = self.listeners.get(str(event), [])
        # Process wildcards too
        listeners += self.listeners.get(str(Event(event.name)), [])
        to_remove = []
        for i, (future, check) in enumerate(listeners):
            if future.cancelled():
                to_remove.append(i)

            try:
                result = check(*args, **kwargs)
            except Exception as e:
                future.set_exception(e)
                to_remove.append(i)

            else:
                if result:
                    future.set_result((*args, *kwargs.values()))
                    to_remove.append(i)

        for i in sorted(to_remove, reverse=True):
            del listeners[i]

        res = self._unsubscribe_dyn(str(event))
        if res:
            self.loop.create_task(res)

    def dispatch(self, event, *args, **kwargs):
        if not isinstance(event, Event):
            event = Event(event)

        self._process_listeners(event, *args, **kwargs)
        self._dispatch(event, *args, **kwargs)

    def _dispatch(self, event, *args, **kwargs):
        try:
            coro = getattr(self, "on_" + event.name)
        except AttributeError:
            pass

        else:
            self.loop.create_task(coro(event.shard_id, *args, **kwargs))

    def has_listener(self, key):
        return len(self.listeners.get(key, [])) > 0

    async def _message_received(self, msg):
        payload = msgpack.unpackb(msg.body)
        shard_id, event, data = payload["shard_id"], payload["event"], payload["data"]
        ev = event.lower()
        self._process_listeners(Event(ev, shard_id), data)
        self._dispatch(Event(ev, shard_id), data)

    def _subscribe_dyn(self, routing_key):
        return self.channel.queue_bind(self.queue.queue, "events", routing_key)

    def _unsubscribe_dyn(self, routing_key, force=False):
        if routing_key in self.static_subscriptions:
            return False

        return self.unsubscribe(routing_key, force)

    def subscribe(self, routing_key, shared=False):
        if shared:
            return self.channel.queue_bind(self.s_queue.queue, "events", routing_key)

        self.static_subscriptions.add(routing_key)
        return self.channel.queue_bind(self.queue.queue, "events", routing_key)

    def unsubscribe(self, routing_key, force=False, shared=False):
        if shared:
            return self.channel.queue_unbind(self.s_queue.queue, "events", routing_key)

        if self.has_listener(routing_key) and not force:
            return False

        try:
            self.static_subscriptions.remove(routing_key)
        except KeyError:
            pass

        return self.channel.queue_unbind(self.queue.queue, "events", routing_key)

    async def wait_for(self, event, shard_id="*", check=None, timeout=None):
        future = self.loop.create_future()
        if check is None:
            def _check(*args):
                return True

            check = _check

        key = "%s.%s" % (shard_id, event.lower())
        if key not in self.listeners.keys():
            self.listeners[key] = []

        listeners = self.listeners[key]

        listeners.append((future, check))
        await self._subscribe_dyn(key)
        return await asyncio.wait_for(future, timeout)

    async def start(self, token, shared_queue, *shared_subs):
        try:
            self.session = aiohttp.ClientSession(loop=self.loop)
            self.http.redis = self.redis = await aioredis.create_redis_pool(self.redis_url)

            user_data = await self.http.static_login(token)
            self.user = User(user_data)

            self.connection = await aiormq.connect(self.url)
            self.channel = await self.connection.channel()

            # The shared queue is used for commands and other events that should be shared between replicated workers
            self.s_queue = await self.channel.queue_declare(queue=shared_queue, arguments={"x-message-ttl": 10000})

            # The exclusive queue is used for wait_for and other events that an individual worker has to receive
            self.queue = await self.channel.queue_declare(queue='', arguments={"x-max-length": 1000}, exclusive=True)

            await self.channel.basic_consume(self.s_queue.queue, self._message_received, no_ack=True)
            for sub in shared_subs or []:
                await self.channel.queue_bind(self.s_queue.queue, "events", sub)

            await self.channel.basic_consume(self.queue.queue, self._message_received, no_ack=True)

        except ConnectionError:
            traceback.print_exc()
            await asyncio.sleep(5)
            return await self.start(token, shared_queue, *shared_subs)

    def run(self, *args, **kwargs):
        self.loop.create_task(self.start(*args, **kwargs))
        self.loop.run_forever()

    async def close(self):
        await self.channel.close()
        await self.connection.close()
