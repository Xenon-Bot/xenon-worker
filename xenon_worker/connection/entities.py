from datetime import datetime
import re

from .enums import *
from .permissions import Permissions, PermissionOverwrite

DISCORD_EPOCH = 1420070400000
DISCORD_CDN = "https://cdn.discord.com"


def parse_time(timestamp):
    if timestamp:
        return datetime(*map(int, re.split(r'[^\d]', timestamp.replace('+00:00', ''))))

    return None


class Snowflake:
    __slots__ = ("id",)

    def __init__(self, id):
        self.id = id

    def __hash__(self):
        return int(self.id) >> 22

    def __eq__(self, other):
        return isinstance(other, self.__class__) and other.id == self.id

    def __ne__(self, other):
        if isinstance(other, self.__class__):
            return other.id != self.id

        return True

    @property
    def created_at(self):
        return datetime.utcfromtimestamp(((int(self.id) >> 22) + DISCORD_EPOCH) / 1000)


class Entity(Snowflake):
    __slots__ = ("_data",)

    def __init__(self, data: dict):
        self._preprocess(data)
        self._data = data

    def _preprocess(self, data):
        pass

    def __getattr__(self, item):
        return self._data.get(item)

    def update(self, data: dict):
        self._preprocess(data)
        self._data.update(data)

    def to_dict(self):
        return self._data


class Role(Entity):
    def _preprocess(self, data):
        self.permissions = Permissions(data["permissions"])

    def is_default(self):
        return self.position == 0


class Channel(Entity):
    __slots__ = ("type", "guild_id", "position", "permission_overwrites", "name", "topic", "nsfw", "last_message_id",
                 "bitrate", "user_limit", "rate_limit_per_user", "recipients", "icon", "owner_id", "application_id",
                 "parent_id", "last_pin_timestamp")

    def _preprocess(self, data):
        self.type = ChannelType(data["type"])
        self.permission_overwrites = [
            (
                overwrite["id"],
                PermissionOverwrite.from_pair(
                    Permissions(overwrite["allow"]),
                    Permissions(overwrite["deny"])
                )
            )
            for overwrite in data.get("permission_overwrites", [])
        ]

    def sort_overwrites(self, guild_id):
        """
        Move overwrites for @everyone to index 0 because it needs to be treated differently
        """
        everyone_index = 0
        for i, (id, ov) in enumerate(self.permission_overwrites):
            if id == guild_id:
                everyone_index = i

        self.permission_overwrites.insert(0, self.permission_overwrites.pop(everyone_index))

    @property
    def icon_url(self):
        return None


class User(Entity):
    __slots__ = ("username", "discriminator", "avatar", "bot", "system", "mfa_enabled")

    @property
    def name(self):
        return self.username

    @property
    def avatar_url(self):
        if self.avatar:
            return f"{DISCORD_CDN}/avatars/{self.id}/{self.avatar}.png"

        else:
            return f"{DISCORD_CDN}/embed/avatars/{int(self.discriminator) % 5}.png"

    @property
    def mention(self):
        return "<@{0.id}>".format(self)

    def __str__(self):
        return "{0.name}#{0.discriminator}".format(self)


class Member(User):
    __slots__ = ("user", "nick", "deaf", "mute", "roles", "joined_at", "premium_since")

    def _preprocess(self, data):
        self.user = User(data["user"])
        self.joined_at = parse_time(data.get("joined_at"))
        self.premium_since = parse_time(data.get("premium_since"))
        self.roles = data.get("roles", [])

    def __getattr__(self, item):
        user_attr = getattr(self.user, item)
        if user_attr is not None:
            return user_attr

        return self._data.get(item)

    def roles_from_guild(self, guild):
        for role in guild.roles:
            if role.id in self.roles or role.id == guild.id:
                yield role

    def permissions_for_guild(self, guild):
        if self.id == guild.owner_id:
            return Permissions.all()

        roles = list(sorted(self.roles_from_guild(guild), key=lambda r: r.position))
        base = roles.pop(0).permissions  # @everyone
        for role in roles:
            base.value |= role.permissions.value

        return base

    def permissions_for_channel(self, guild, channel):
        if self.id == guild.owner_id:
            return Permissions.all()

        base = self.permissions_for_guild(guild)
        if base.administrator:
            return base

        roles = [r.id for r in self.roles_from_guild(guild)]
        channel.sort_overwrites(guild.id)
        for id, ov in channel.permission_overwrites:
            if id == self.id or id == guild.id or id in roles:
                base.handle_overwrite(allow=ov.allow, deny=ov.deny)

        if not base.send_messages:
            base.send_tts_messages = False
            base.mention_everyone = False
            base.embed_links = False
            base.attach_files = False

        if not base.read_messages:
            denied = Permissions.all_channel()
            base.value &= ~denied.value

        return base


class Guild(Entity):
    __slots__ = ("name", "icon", "splash", "owner", "owner_id", "permissions", "region", "afk_channel_id",
                 "afk_timeout", "embed_enabled", "embed_channel_id", "verification_level",
                 "default_message_notifications", "explicit_content_filter", "roles", "emojis", "features",
                 "mfa_level", "application_id", "widget_enabled", "widget_channel_id", "system_channel_id",
                 "joined_at", "large", "unavailable", "member_count", "voice_states", "members", "channels",
                 "presences", "max_presences", "max_members", "vanity_url_code", "description", "banner",
                 "premium_tier", "premium_subscription_count", "preferred_locale")

    def _preprocess(self, data):
        self.permissions = Permissions(data.get("permissions")) if data.get("permissions") is not None else None
        self.verification_level = VerificationLevel(data["verification_level"])
        self.default_message_notifications = DefaultMessageNotifications(data["default_message_notifications"])
        self.explicit_content_filter = ExplicitContentFilter(data["explicit_content_filter"])
        self.mfa_level = MFALevel(data["mfa_level"])
        self.roles = [Role(d) for d in data.get("roles", [])]
        # self.emojis =
        self.members = [Member(d) for d in data.get("members", [])]
        self.channels = [Channel(d) for d in data.get("channels", [])]

    @property
    def icon_animated(self):
        return bool(self.icon and self.icon.startswith('a_'))

    @property
    def icon_url(self):
        return self.icon_url_as()

    def icon_url_as(self, *, format=None, static_format='webp', size=1024):
        if self.icon is None:
            return None

        if format is None:
            if self.icon_animated:
                format = "gif"

            else:
                format = static_format

        return DISCORD_CDN + "/icons/{0.id}/{0.icon}.{1}?size={2}".format(self, format, size)

    @property
    def splash_url(self):
        return None

    @property
    def default_role(self):
        fit = [r for r in self.roles if r.is_default()]
        if len(fit) > 0:
            return fit[0]

        else:
            return None


class Message(Entity):
    def _preprocess(self, data):
        self.type = MessageType(data["type"])
        self.timestamp = parse_time(data["timestamp"])
        # self.mentions
        # self.mention_roles
        # self.mention_everyone
        self.author = Member({"user": data["author"], **data.get("member", {})})
        self.edited_timestamp = parse_time(data["edited_timestamp"])
        self.attachments = data.get("attachments", [])

    @property
    def member(self):
        return self.author


class Webhook(Entity):
    def _preprocess(self, data):
        self.user = User(data.get("user"))
        self.type = WebhookType(data["type"])
