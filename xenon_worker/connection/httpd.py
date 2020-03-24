import asyncio
import logging
from urllib.parse import quote as _uriquote
from . import utils
import sys

import aiohttp

from .errors import HTTPException, Forbidden, NotFound, LoginFailure, GatewayNotFound
from .utils import json_or_text

log = logging.getLogger(__name__)


class Route:
    BASE = 'https://discordapp.com/api/v7'

    def __init__(self, method, path, **parameters):
        self.path = path
        self.method = method
        url = (self.BASE + self.path)
        if parameters:
            self.url = url.format(**{k: _uriquote(v) if isinstance(v, str) else v for k, v in parameters.items()})
        else:
            self.url = url

        # major parameters:
        self.channel_id = parameters.get('channel_id')
        self.guild_id = parameters.get('guild_id')
        self.webhook_id = parameters.get('webhook_id')

    @property
    def bucket(self):
        # the bucket is just method + path w/ major parameters
        if self.webhook_id is not None:
            return '{0.channel_id}:{0.guild_id}:{0.webhook_id}:{0.path}'.format(self)

        else:
            return '{0.channel_id}:{0.guild_id}:{0.path}'.format(self)


class MaybeUnlock:
    def __init__(self, lock):
        self.lock = lock
        self._unlock = True

    async def __aenter__(self):
        return self

    def defer(self):
        self._unlock = False

    async def __aexit__(self, type, value, traceback):
        if self._unlock:
            await self.lock.release()


class RatelimitLock:
    def __init__(self, redis, bucket):
        self.redis = redis
        self.bucket = bucket

    @property
    def key(self):
        return "ratelimit:" + self.bucket

    async def acquire(self):
        while True:
            delta = await self.redis.pttl(self.key)
            if delta == -2:  # Key does not exist
                # 10 second ttl to avoid deadlock
                return await self.redis.setex(self.key, 3, 1)

            else:
                await asyncio.sleep(delta / 1000)

    async def release_in(self, delta):
        return await self.redis.setex(self.key, delta, 1)

    async def release(self):
        return await self.redis.delete(self.key)


class HTTPClient:
    """Represents an HTTP client sending HTTP requests to the Discord API."""

    SUCCESS_LOG = '{method} {url} has received {text}'
    REQUEST_LOG = '{method} {url} with {json} has returned {status}'

    def __init__(self, connector=None, *, proxy=None, proxy_auth=None, loop=None, unsync_clock=True):
        self.loop = asyncio.get_event_loop() if loop is None else loop
        self.connector = connector
        self.__session = None  # filled in static_login
        self.proxy = proxy
        self.proxy_auth = proxy_auth
        self.use_clock = not unsync_clock
        self.token = None
        self.redis = None

        user_agent = 'DiscordBot (https://github.com/Magic-Bots/xenon-worker) Python/{0[0]}.{0[1]} aiohttp/{1}'
        self.user_agent = user_agent.format(sys.version_info, aiohttp.__version__)

    def recreate(self):
        if self.__session.closed:
            self.__session = aiohttp.ClientSession(connector=self.connector)

    async def request(self, route, *, files=None, **kwargs):
        bucket = route.bucket
        method = route.method
        url = route.url

        lock = RatelimitLock(self.redis, bucket)

        # header creation
        headers = {
            'User-Agent': self.user_agent,
            'X-Ratelimit-Precision': 'millisecond',
            'Authorization': 'Bot ' + self.token
        }

        # some checking if it's a JSON request
        if 'json' in kwargs:
            headers['Content-Type'] = 'application/json'
            kwargs['data'] = utils.to_json(kwargs.pop('json'))

        try:
            reason = kwargs.pop('reason')
        except KeyError:
            pass
        else:
            if reason:
                headers['X-Audit-Log-Reason'] = _uriquote(reason, safe='/ ')

        kwargs['headers'] = headers

        # Proxy support
        if self.proxy is not None:
            kwargs['proxy'] = self.proxy
        if self.proxy_auth is not None:
            kwargs['proxy_auth'] = self.proxy_auth

        # Check if global rate limit was hit
        while True:
            delta = await self.redis.pttl("ratelimit:global")
            if delta < 0:
                # Key does not exist or key has no ttl
                break

            await asyncio.sleep(delta / 1000)

        # Check if bucket ratelimit was hit and acquire the lock
        await lock.acquire()
        async with MaybeUnlock(lock) as maybe_lock:
            for tries in range(5):
                if files:
                    for f in files:
                        f.reset(seek=tries)

                async with self.__session.request(method, url, **kwargs) as r:
                    log.debug('%s %s with %s has returned %s', method, url, kwargs.get('data'), r.status)

                    # even errors have text involved in them so this is safe to call
                    data = await json_or_text(r)

                    # check if we have rate limit header information
                    remaining = r.headers.get('X-Ratelimit-Remaining')
                    if remaining == '0' and r.status != 429:
                        # we've depleted our current bucket
                        delta = utils._parse_ratelimit_header(r, use_clock=self.use_clock)
                        log.info('A rate limit bucket has been exhausted (bucket: %s, retry: %s).', bucket, delta)
                        maybe_lock.defer()
                        await lock.release_in(delta)

                    # the request was successful so just return the text/json
                    if 300 > r.status >= 200:
                        log.debug('%s %s has received %s', method, url, data)
                        return data

                    # we are being rate limited
                    if r.status == 429:
                        if not r.headers.get('Via'):
                            # Banned by Cloudflare more than likely.
                            raise HTTPException(r, data)

                        fmt = 'We are being rate limited. Retrying in %.2f seconds. Handled under the bucket "%s"'

                        # sleep a bit
                        retry_after = data['retry_after'] / 1000.0
                        log.warning(fmt, retry_after, bucket)
                        await lock.release_in(retry_after)

                        # check if it's a global rate limit
                        is_global = data.get('global', False)
                        if is_global:
                            log.warning('Global rate limit has been hit. Retrying in %.2f seconds.', retry_after)
                            await self.redis.setex("ratelimit:global", retry_after, 1)

                        await asyncio.sleep(retry_after)
                        log.debug('Done sleeping for the rate limit. Retrying...')

                        continue

                    # we've received a 500 or 502, unconditional retry
                    if r.status in {500, 502}:
                        await asyncio.sleep(1 + tries * 2)
                        continue

                    # the usual error cases
                    if r.status == 403:
                        raise Forbidden(r, data)
                    elif r.status == 404:
                        raise NotFound(r, data)
                    else:
                        raise HTTPException(r, data)

            # We've run out of retries, raise.
            raise HTTPException(r, data)

    async def get_from_cdn(self, url):
        async with self.__session.get(url) as resp:
            if resp.status == 200:
                return await resp.read()
            elif resp.status == 404:
                raise NotFound(resp, 'asset not found')
            elif resp.status == 403:
                raise Forbidden(resp, 'cannot retrieve asset')
            else:
                raise HTTPException(resp, 'failed to get asset')

    # state management

    async def close(self):
        if self.__session:
            await self.__session.close()

    def _token(self, token, *, bot=True):
        self.token = token
        self.bot_token = bot
        self._ack_token = None

    # login management

    async def static_login(self, token=False, *, bot=True):
        # Necessary to get aiohttp to stop complaining about session creation
        self.__session = aiohttp.ClientSession(connector=self.connector)
        self._token(token, bot=bot)

        try:
            data = await self.request(Route('GET', '/users/@me'))
        except HTTPException as exc:
            if exc.response.status == 401:
                raise LoginFailure('Improper token has been passed.') from exc
            raise

        return data

    def logout(self):
        return self.request(Route('POST', '/auth/logout'))

    # Group functionality

    def start_group(self, user_id, recipients):
        payload = {
            'recipients': recipients
        }

        return self.request(Route('POST', '/users/{user_id}/channels', user_id=user_id), json=payload)

    def leave_group(self, channel_id):
        return self.request(Route('DELETE', '/channels/{channel_id}', channel_id=channel_id))

    def add_group_recipient(self, channel_id, user_id):
        r = Route('PUT', '/channels/{channel_id}/recipients/{user_id}', channel_id=channel_id, user_id=user_id)
        return self.request(r)

    def remove_group_recipient(self, channel_id, user_id):
        r = Route('DELETE', '/channels/{channel_id}/recipients/{user_id}', channel_id=channel_id, user_id=user_id)
        return self.request(r)

    def edit_group(self, channel_id, **options):
        valid_keys = ('name', 'icon')
        payload = {
            k: v for k, v in options.items() if k in valid_keys
        }

        return self.request(Route('PATCH', '/channels/{channel_id}', channel_id=channel_id), json=payload)

    def convert_group(self, channel_id):
        return self.request(Route('POST', '/channels/{channel_id}/convert', channel_id=channel_id))

    # Message management

    def start_private_message(self, user_id):
        payload = {
            'recipient_id': user_id
        }

        return self.request(Route('POST', '/users/@me/channels'), json=payload)

    def send_message(self, channel_id, content="", *, tts=False, embed=None, nonce=None):
        r = Route('POST', '/channels/{channel_id}/messages', channel_id=channel_id)
        payload = {}

        if content:
            payload['content'] = content

        if tts:
            payload['tts'] = True

        if embed:
            payload['embed'] = embed

        if nonce:
            payload['nonce'] = nonce

        return self.request(r, json=payload)

    def send_typing(self, channel_id):
        return self.request(Route('POST', '/channels/{channel_id}/typing', channel_id=channel_id))

    def send_files(self, channel_id, *, files, content=None, tts=False, embed=None, nonce=None):
        r = Route('POST', '/channels/{channel_id}/messages', channel_id=channel_id)
        form = aiohttp.FormData()

        payload = {'tts': tts}
        if content:
            payload['content'] = content
        if embed:
            payload['embed'] = embed
        if nonce:
            payload['nonce'] = nonce

        form.add_field('payload_json', utils.to_json(payload))
        if len(files) == 1:
            file = files[0]
            form.add_field('file', file.fp, filename=file.filename, content_type='application/octet-stream')
        else:
            for index, file in enumerate(files):
                form.add_field('file%s' % index, file.fp, filename=file.filename,
                               content_type='application/octet-stream')

        return self.request(r, data=form, files=files)

    async def ack_message(self, channel_id, message_id):
        r = Route('POST', '/channels/{channel_id}/messages/{message_id}/ack', channel_id=channel_id,
                  message_id=message_id)
        data = await self.request(r, json={'token': self._ack_token})
        self._ack_token = data['token']

    def ack_guild(self, guild_id):
        return self.request(Route('POST', '/guilds/{guild_id}/ack', guild_id=guild_id))

    def delete_message(self, channel_id, message_id, *, reason=None):
        r = Route('DELETE', '/channels/{channel_id}/messages/{message_id}', channel_id=channel_id,
                  message_id=message_id)
        return self.request(r, reason=reason)

    def delete_messages(self, channel_id, message_ids, *, reason=None):
        r = Route('POST', '/channels/{channel_id}/messages/bulk_delete', channel_id=channel_id)
        payload = {
            'messages': message_ids
        }

        return self.request(r, json=payload, reason=reason)

    def edit_message(self, channel_id, message_id, **fields):
        r = Route('PATCH', '/channels/{channel_id}/messages/{message_id}', channel_id=channel_id, message_id=message_id)
        return self.request(r, json=fields)

    def add_reaction(self, channel_id, message_id, emoji):
        r = Route('PUT', '/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me',
                  channel_id=channel_id, message_id=message_id, emoji=emoji)
        return self.request(r)

    def remove_reaction(self, channel_id, message_id, emoji, member_id):
        r = Route('DELETE', '/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/{member_id}',
                  channel_id=channel_id, message_id=message_id, member_id=member_id, emoji=emoji)
        return self.request(r)

    def remove_own_reaction(self, channel_id, message_id, emoji):
        r = Route('DELETE', '/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me',
                  channel_id=channel_id, message_id=message_id, emoji=emoji)
        return self.request(r)

    def get_reaction_users(self, channel_id, message_id, emoji, limit, after=None):
        r = Route('GET', '/channels/{channel_id}/messages/{message_id}/reactions/{emoji}',
                  channel_id=channel_id, message_id=message_id, emoji=emoji)

        params = {'limit': limit}
        if after:
            params['after'] = after
        return self.request(r, params=params)

    def clear_reactions(self, channel_id, message_id):
        r = Route('DELETE', '/channels/{channel_id}/messages/{message_id}/reactions',
                  channel_id=channel_id, message_id=message_id)

        return self.request(r)

    def clear_single_reaction(self, channel_id, message_id, emoji):
        r = Route('DELETE', '/channels/{channel_id}/messages/{message_id}/reactions/{emoji}',
                  channel_id=channel_id, message_id=message_id, emoji=emoji)
        return self.request(r)

    def get_message(self, channel_id, message_id):
        r = Route('GET', '/channels/{channel_id}/messages/{message_id}', channel_id=channel_id, message_id=message_id)
        return self.request(r)

    def get_channel(self, channel_id):
        r = Route('GET', '/channels/{channel_id}', channel_id=channel_id)
        return self.request(r)

    def logs_from(self, channel_id, limit, before=None, after=None, around=None):
        params = {
            'limit': limit
        }

        if before is not None:
            params['before'] = before
        if after is not None:
            params['after'] = after
        if around is not None:
            params['around'] = around

        return self.request(Route('GET', '/channels/{channel_id}/messages', channel_id=channel_id), params=params)

    def publish_message(self, channel_id, message_id):
        return self.request(Route('POST', '/channels/{channel_id}/messages/{message_id}/crosspost',
                                  channel_id=channel_id, message_id=message_id))

    def pin_message(self, channel_id, message_id):
        return self.request(Route('PUT', '/channels/{channel_id}/pins/{message_id}',
                                  channel_id=channel_id, message_id=message_id))

    def unpin_message(self, channel_id, message_id):
        return self.request(Route('DELETE', '/channels/{channel_id}/pins/{message_id}',
                                  channel_id=channel_id, message_id=message_id))

    def pins_from(self, channel_id):
        return self.request(Route('GET', '/channels/{channel_id}/pins', channel_id=channel_id))

    # Member management

    def kick(self, user_id, guild_id, reason=None):
        r = Route('DELETE', '/guilds/{guild_id}/members/{user_id}', guild_id=guild_id, user_id=user_id)
        if reason:
            # thanks aiohttp
            r.url = '{0.url}?reason={1}'.format(r, _uriquote(reason))

        return self.request(r)

    def ban(self, user_id, guild_id, delete_message_days=1, reason=None):
        r = Route('PUT', '/guilds/{guild_id}/bans/{user_id}', guild_id=guild_id, user_id=user_id)
        params = {
            'delete-message-days': delete_message_days,
        }

        if reason:
            # thanks aiohttp
            r.url = '{0.url}?reason={1}'.format(r, _uriquote(reason))

        return self.request(r, params=params)

    def unban(self, user_id, guild_id, *, reason=None):
        r = Route('DELETE', '/guilds/{guild_id}/bans/{user_id}', guild_id=guild_id, user_id=user_id)
        return self.request(r, reason=reason)

    def guild_voice_state(self, user_id, guild_id, *, mute=None, deafen=None, reason=None):
        r = Route('PATCH', '/guilds/{guild_id}/members/{user_id}', guild_id=guild_id, user_id=user_id)
        payload = {}
        if mute is not None:
            payload['mute'] = mute

        if deafen is not None:
            payload['deaf'] = deafen

        return self.request(r, json=payload, reason=reason)

    def edit_profile(self, password, username, avatar, **fields):
        payload = {
            'password': password,
            'username': username,
            'avatar': avatar
        }

        if 'email' in fields:
            payload['email'] = fields['email']

        if 'new_password' in fields:
            payload['new_password'] = fields['new_password']

        return self.request(Route('PATCH', '/users/@me'), json=payload)

    def change_my_nickname(self, guild_id, nickname, *, reason=None):
        r = Route('PATCH', '/guilds/{guild_id}/members/@me/nick', guild_id=guild_id)
        payload = {
            'nick': nickname
        }
        return self.request(r, json=payload, reason=reason)

    def change_nickname(self, guild_id, user_id, nickname, *, reason=None):
        r = Route('PATCH', '/guilds/{guild_id}/members/{user_id}', guild_id=guild_id, user_id=user_id)
        payload = {
            'nick': nickname
        }
        return self.request(r, json=payload, reason=reason)

    def edit_member(self, guild_id, user_id, *, reason=None, **fields):
        r = Route('PATCH', '/guilds/{guild_id}/members/{user_id}', guild_id=guild_id, user_id=user_id)
        return self.request(r, json=fields, reason=reason)

    # Channel management

    def edit_channel(self, channel_id, *, reason=None, **options):
        r = Route('PATCH', '/channels/{channel_id}', channel_id=channel_id)
        valid_keys = ('name', 'parent_id', 'topic', 'bitrate', 'nsfw',
                      'user_limit', 'position', 'permission_overwrites', 'rate_limit_per_user')
        payload = {
            k: v for k, v in options.items() if k in valid_keys
        }

        return self.request(r, reason=reason, json=payload)

    def bulk_channel_update(self, guild_id, data, *, reason=None):
        r = Route('PATCH', '/guilds/{guild_id}/channels', guild_id=guild_id)
        return self.request(r, json=data, reason=reason)

    def create_channel(self, guild_id, *, reason=None, **options):
        valid_keys = ('type', 'name', 'parent_id', 'topic', 'bitrate', 'nsfw',
                      'user_limit', 'position', 'permission_overwrites', 'rate_limit_per_user')
        payload = {
            k: v for k, v in options.items() if k in valid_keys and v is not None
        }

        return self.request(Route('POST', '/guilds/{guild_id}/channels', guild_id=guild_id), json=payload,
                            reason=reason)

    def delete_channel(self, channel_id, *, reason=None):
        return self.request(Route('DELETE', '/channels/{channel_id}', channel_id=channel_id), reason=reason)

    # Webhook management

    def create_webhook(self, channel_id, *, name, avatar=None, reason=None):
        payload = {
            'name': name
        }
        if avatar is not None:
            payload['avatar'] = avatar

        r = Route('POST', '/channels/{channel_id}/webhooks', channel_id=channel_id)
        return self.request(r, json=payload, reason=reason)

    def delete_webhook(self, webhook_id, webhook_token):
        return self.request(Route(
            'DELETE',
            '/webhooks/{webhook_id}/{webhook_token}',
            webhook_id=webhook_id,
            webhook_token=webhook_token
        ))

    def channel_webhooks(self, channel_id):
        return self.request(Route('GET', '/channels/{channel_id}/webhooks', channel_id=channel_id))

    def guild_webhooks(self, guild_id):
        return self.request(Route('GET', '/guilds/{guild_id}/webhooks', guild_id=guild_id))

    def get_webhook(self, webhook_id):
        return self.request(Route('GET', '/webhooks/{webhook_id}', webhook_id=webhook_id))

    def follow_webhook(self, channel_id, webhook_channel_id):
        payload = {
            'webhook_channel_id': str(webhook_channel_id)
        }
        return self.request(Route('POST', '/channels/{channel_id}/followers', channel_id=channel_id), json=payload)

    def execute_webhook(self, webhook_id, webhook_token, wait=False, **options):
        r = Route('POST', '/webhooks/{webhook_id}/{webhook_token}', webhook_id=webhook_id, webhook_token=webhook_token)
        valid_keys = ("content", "username", "avatar_url", "tts", "file", "embeds")
        payload = {
            k: v for k, v in options.items() if k in valid_keys
        }
        return self.request(r, json=payload, params={"wait": 'true' if wait else 'false'})

    # Guild management

    def get_guilds(self, limit, before=None, after=None):
        params = {
            'limit': limit
        }

        if before:
            params['before'] = before
        if after:
            params['after'] = after

        return self.request(Route('GET', '/users/@me/guilds'), params=params)

    def leave_guild(self, guild_id):
        return self.request(Route('DELETE', '/users/@me/guilds/{guild_id}', guild_id=guild_id))

    def get_guild(self, guild_id):
        return self.request(Route('GET', '/guilds/{guild_id}', guild_id=guild_id))

    def delete_guild(self, guild_id):
        return self.request(Route('DELETE', '/guilds/{guild_id}', guild_id=guild_id))

    def create_guild(self, name, region, icon):
        payload = {
            'name': name,
            'icon': icon,
            'region': region
        }

        return self.request(Route('POST', '/guilds'), json=payload)

    def edit_guild(self, guild_id, *, reason=None, **fields):
        valid_keys = ('name', 'region', 'icon', 'afk_timeout', 'owner_id',
                      'afk_channel_id', 'splash', 'verification_level',
                      'system_channel_id', 'default_message_notifications',
                      'description', 'explicit_content_filter', 'banner',
                      'system_channel_flags')

        payload = {
            k: v for k, v in fields.items() if k in valid_keys
        }

        return self.request(Route('PATCH', '/guilds/{guild_id}', guild_id=guild_id), json=payload, reason=reason)

    def get_bans(self, guild_id):
        return self.request(Route('GET', '/guilds/{guild_id}/bans', guild_id=guild_id))

    def get_ban(self, user_id, guild_id):
        return self.request(Route('GET', '/guilds/{guild_id}/bans/{user_id}', guild_id=guild_id, user_id=user_id))

    def get_vanity_code(self, guild_id):
        return self.request(Route('GET', '/guilds/{guild_id}/vanity-url', guild_id=guild_id))

    def change_vanity_code(self, guild_id, code, *, reason=None):
        payload = {'code': code}
        return self.request(Route('PATCH', '/guilds/{guild_id}/vanity-url', guild_id=guild_id), json=payload,
                            reason=reason)

    def get_all_guild_channels(self, guild_id):
        return self.request(Route('GET', '/guilds/{guild_id}/channels', guild_id=guild_id))

    def get_members(self, guild_id, limit, after):
        params = {
            'limit': limit,
        }
        if after:
            params['after'] = after

        r = Route('GET', '/guilds/{guild_id}/members', guild_id=guild_id)
        return self.request(r, params=params)

    def get_member(self, guild_id, member_id):
        return self.request(
            Route('GET', '/guilds/{guild_id}/members/{member_id}', guild_id=guild_id, member_id=member_id))

    def prune_members(self, guild_id, days, compute_prune_count, *, reason=None):
        params = {
            'days': days,
            'compute_prune_count': 'true' if compute_prune_count else 'false'
        }
        return self.request(Route('POST', '/guilds/{guild_id}/prune', guild_id=guild_id), params=params, reason=reason)

    def estimate_pruned_members(self, guild_id, days):
        params = {
            'days': days
        }
        return self.request(Route('GET', '/guilds/{guild_id}/prune', guild_id=guild_id), params=params)

    def get_all_custom_emojis(self, guild_id):
        return self.request(Route('GET', '/guilds/{guild_id}/emojis', guild_id=guild_id))

    def get_custom_emoji(self, guild_id, emoji_id):
        return self.request(Route('GET', '/guilds/{guild_id}/emojis/{emoji_id}', guild_id=guild_id, emoji_id=emoji_id))

    def create_custom_emoji(self, guild_id, name, image, *, roles=None, reason=None):
        payload = {
            'name': name,
            'image': image,
            'roles': roles or []
        }

        r = Route('POST', '/guilds/{guild_id}/emojis', guild_id=guild_id)
        return self.request(r, json=payload, reason=reason)

    def delete_custom_emoji(self, guild_id, emoji_id, *, reason=None):
        r = Route('DELETE', '/guilds/{guild_id}/emojis/{emoji_id}', guild_id=guild_id, emoji_id=emoji_id)
        return self.request(r, reason=reason)

    def edit_custom_emoji(self, guild_id, emoji_id, *, name, roles=None, reason=None):
        payload = {
            'name': name,
            'roles': roles or []
        }
        r = Route('PATCH', '/guilds/{guild_id}/emojis/{emoji_id}', guild_id=guild_id, emoji_id=emoji_id)
        return self.request(r, json=payload, reason=reason)

    def get_audit_logs(self, guild_id, limit=100, before=None, after=None, user_id=None, action_type=None):
        params = {'limit': limit}
        if before:
            params['before'] = before
        if after:
            params['after'] = after
        if user_id:
            params['user_id'] = user_id
        if action_type:
            params['action_type'] = action_type

        r = Route('GET', '/guilds/{guild_id}/audit-logs', guild_id=guild_id)
        return self.request(r, params=params)

    def get_widget(self, guild_id):
        return self.request(Route('GET', '/guilds/{guild_id}/widget.json', guild_id=guild_id))

    # Invite management

    def create_invite(self, channel_id, *, reason=None, **options):
        r = Route('POST', '/channels/{channel_id}/invites', channel_id=channel_id)
        payload = {
            'max_age': options.get('max_age', 0),
            'max_uses': options.get('max_uses', 0),
            'temporary': options.get('temporary', False),
            'unique': options.get('unique', True)
        }

        return self.request(r, reason=reason, json=payload)

    def get_invite(self, invite_id, *, with_counts=True):
        params = {
            'with_counts': int(with_counts)
        }
        return self.request(Route('GET', '/invite/{invite_id}', invite_id=invite_id), params=params)

    def invites_from(self, guild_id):
        return self.request(Route('GET', '/guilds/{guild_id}/invites', guild_id=guild_id))

    def invites_from_channel(self, channel_id):
        return self.request(Route('GET', '/channels/{channel_id}/invites', channel_id=channel_id))

    def delete_invite(self, invite_id, *, reason=None):
        return self.request(Route('DELETE', '/invite/{invite_id}', invite_id=invite_id), reason=reason)

    # Role management

    def get_roles(self, guild_id):
        return self.request(Route('GET', '/guilds/{guild_id}/roles', guild_id=guild_id))

    def edit_role(self, guild_id, role_id, *, reason=None, **fields):
        r = Route('PATCH', '/guilds/{guild_id}/roles/{role_id}', guild_id=guild_id, role_id=role_id)
        valid_keys = ('name', 'permissions', 'color', 'hoist', 'mentionable')
        payload = {
            k: v for k, v in fields.items() if k in valid_keys
        }
        return self.request(r, json=payload, reason=reason)

    def delete_role(self, guild_id, role_id, *, reason=None):
        r = Route('DELETE', '/guilds/{guild_id}/roles/{role_id}', guild_id=guild_id, role_id=role_id)
        return self.request(r, reason=reason)

    def replace_roles(self, user_id, guild_id, role_ids, *, reason=None):
        return self.edit_member(guild_id=guild_id, user_id=user_id, roles=role_ids, reason=reason)

    def create_role(self, guild_id, *, reason=None, **fields):
        r = Route('POST', '/guilds/{guild_id}/roles', guild_id=guild_id)
        return self.request(r, json=fields, reason=reason)

    def move_role_position(self, guild_id, positions, *, reason=None):
        r = Route('PATCH', '/guilds/{guild_id}/roles', guild_id=guild_id)
        return self.request(r, json=positions, reason=reason)

    def add_role(self, guild_id, user_id, role_id, *, reason=None):
        r = Route('PUT', '/guilds/{guild_id}/members/{user_id}/roles/{role_id}',
                  guild_id=guild_id, user_id=user_id, role_id=role_id)
        return self.request(r, reason=reason)

    def remove_role(self, guild_id, user_id, role_id, *, reason=None):
        r = Route('DELETE', '/guilds/{guild_id}/members/{user_id}/roles/{role_id}',
                  guild_id=guild_id, user_id=user_id, role_id=role_id)
        return self.request(r, reason=reason)

    def edit_channel_permissions(self, channel_id, target, allow, deny, type, *, reason=None):
        payload = {
            'id': target,
            'allow': allow,
            'deny': deny,
            'type': type
        }
        r = Route('PUT', '/channels/{channel_id}/permissions/{target}', channel_id=channel_id, target=target)
        return self.request(r, json=payload, reason=reason)

    def delete_channel_permissions(self, channel_id, target, *, reason=None):
        r = Route('DELETE', '/channels/{channel_id}/permissions/{target}', channel_id=channel_id, target=target)
        return self.request(r, reason=reason)

    # Voice management

    def move_member(self, user_id, guild_id, channel_id, *, reason=None):
        return self.edit_member(guild_id=guild_id, user_id=user_id, channel_id=channel_id, reason=reason)

    # Relationship related

    def remove_relationship(self, user_id):
        r = Route('DELETE', '/users/@me/relationships/{user_id}', user_id=user_id)
        return self.request(r)

    def add_relationship(self, user_id, type=None):
        r = Route('PUT', '/users/@me/relationships/{user_id}', user_id=user_id)
        payload = {}
        if type is not None:
            payload['type'] = type

        return self.request(r, json=payload)

    def send_friend_request(self, username, discriminator):
        r = Route('POST', '/users/@me/relationships')
        payload = {
            'username': username,
            'discriminator': int(discriminator)
        }
        return self.request(r, json=payload)

    # Misc

    def application_info(self):
        return self.request(Route('GET', '/oauth2/applications/@me'))

    async def get_gateway(self, *, encoding='json', v=6, zlib=True):
        try:
            data = await self.request(Route('GET', '/gateway'))
        except HTTPException as exc:
            raise GatewayNotFound() from exc
        if zlib:
            value = '{0}?encoding={1}&v={2}&compress=zlib-stream'
        else:
            value = '{0}?encoding={1}&v={2}'
        return value.format(data['url'], encoding, v)

    async def get_bot_gateway(self, *, encoding='json', v=6, zlib=True):
        try:
            data = await self.request(Route('GET', '/gateway/bot'))
        except HTTPException as exc:
            raise GatewayNotFound() from exc

        if zlib:
            value = '{0}?encoding={1}&v={2}&compress=zlib-stream'
        else:
            value = '{0}?encoding={1}&v={2}'
        return data['shards'], value.format(data['url'], encoding, v)

    def get_user(self, user_id):
        return self.request(Route('GET', '/users/{user_id}', user_id=user_id))

    def get_user_profile(self, user_id):
        return self.request(Route('GET', '/users/{user_id}/profile', user_id=user_id))

    def get_mutual_friends(self, user_id):
        return self.request(Route('GET', '/users/{user_id}/relationships', user_id=user_id))

    def change_hypesquad_house(self, house_id):
        payload = {'house_id': house_id}
        return self.request(Route('POST', '/hypesquad/online'), json=payload)

    def leave_hypesquad_house(self):
        return self.request(Route('DELETE', '/hypesquad/online'))

    def edit_settings(self, **payload):
        return self.request(Route('PATCH', '/users/@me/settings'), json=payload)
