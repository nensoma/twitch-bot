"""Deconstruction of IRC messages into specialized class instances."""
from __future__ import annotations
from dataclasses import dataclass
import re


class MessageParser:
    """Parser for IRC messages."""
    @classmethod
    def from_raw(cls, raw: str) -> Message:
        """Parse a raw IRC message into a usable Message instance."""
        data, tags, type_ = raw.split(" :"), {}, None
        if data[0].startswith('@'):
            raw_tags = data.pop(0)[1:]
            tags = cls._parse_tags(raw_tags)
        if (command := data.pop(0).strip(':')).startswith("PING"):
            type_ = command[:4]
            return PingMessage(raw, type_)
        user = cls._parse_user(command)
        type_ = cls._parse_type(command)
        params = cls._parse_params(command, type_)
        channel = cls._parse_channel(params)
        message = cls._parse_message(data)
        match type_:
            case "001":
                msg = LoginMessage(raw, type_)
            case "CAP * ACK":
                assert message
                msg = CapabilitiesMessage(
                    raw, type_, [word[10:] for word in message.split()])
            case "353":
                assert channel and message
                msg = NamesMessage(raw, type_, channel, message.split())
            case "RECONNECT":
                msg = ReconnectMessage(raw, type_)
            case "JOIN":
                assert channel and user
                msg = JoinMessage(raw, type_, channel, user)
            case "PART":
                assert channel and user
                msg = PartMessage(raw, type_, channel, user)
            case "366":
                assert channel
                msg = EndOfNamesMessage(raw, type_, channel)
            case "NOTICE":
                assert channel and message
                msg = NoticeMessage(raw, type_, channel, message, tags)
            case "USERSTATE":
                assert channel
                msg = UserstateMessage(raw, type_, channel, tags)
            case "ROOMSTATE":
                assert channel
                msg = RoomstateMessage(raw, type_, channel, tags)
            case "CLEARCHAT":
                assert channel
                msg = ClearchatMessage(raw, type_, channel, message, tags)
            case "CLEARMSG":
                assert channel and message
                msg = ClearmsgMessage(raw, type_, channel, message, tags)
            case "USERNOTICE":
                assert channel
                msg = UsernoticeMessage(raw, type_, channel, message, tags)
            case "WHISPER":
                assert user and params and message
                msg = WhisperMessage(raw, type_, user, params, message, tags)
            case "PRIVMSG":
                assert channel and user and message
                msg = ChatMessage(raw, type_, channel, user, message, tags)
            case _:
                msg = Message(raw, type_)
        return msg

    @staticmethod
    def _parse_tags(raw_tags: str) -> dict[str, str]:
        tags: dict[str, str] = {}
        for tag in raw_tags.split(';'):
            if (match := re.fullmatch(r"^(.*)=(.*)$", tag)):
                tags[match[1]] = match[2]
        return tags

    @staticmethod
    def _parse_user(command: str) -> str | None:
        if command.startswith(("jtv ", "tmi.twitch.tv ")):
            return None
        if (match := re.match(r"^([a-z0-9_]+)!(?:\1)@(?:\1)", command)):
            return match[1]
        return None

    @staticmethod
    def _parse_type(command: str) -> str:
        return "CAP * ACK" if "CAP * ACK" in command else command.split()[1]

    @staticmethod
    def _parse_params(command: str, msg_type: str) -> str | None:
        params = command[command.index(msg_type)+1 + len(msg_type) :]
        return params or None

    @staticmethod
    def _parse_channel(params: str | None) -> str | None:
        def get_index(string: str, substring: str, start: int = 0) -> int | None:
            try:
                return string.index(substring, start)
            except ValueError:
                return None

        if params is not None:
            if (channel_index := get_index(params, '#')) is not None:
                return params[channel_index+1 : get_index(params, ' ', channel_index)]

    @staticmethod
    def _parse_message(data: list[str]) -> str | None:
        if data:
            message = " :".join(data)
            if ord(message[0]) == 1 and message[1:7] == "ACTION":
                message = f"/me{message[7:-1]}"
            return message.strip()
        return None


@dataclass
class Message:
    """IRC message received from Twitch."""
    raw: str
    type_: str

    def __str__(self) -> str:
        return f"Message(type={self.type_})"


@dataclass
class LoginMessage(Message):
    """IRC message for a succesful login."""

    def __str__(self) -> str:
        return "LoginMessage"


@dataclass
class CapabilitiesMessage(Message):
    """IRC message for acquired capabilities."""
    capabilities: list[str]

    def __str__(self) -> str:
        return f"CapabilitiesMessage(capabilities={self.capabilities})"


@dataclass
class PingMessage(Message):
    """IRC message for a keepalive ping."""

    def __str__(self) -> str:
        return "PingMessage"


@dataclass
class ReconnectMessage(Message):
    """IRC message for a reconnect signal."""

    def __str__(self) -> str:
        return "ReconnectMessage"


@dataclass
class JoinMessage(Message):
    """IRC message for joining a channel."""
    channel: str
    user: str

    def __str__(self) -> str:
        return f"JoinMessage(channel={self.channel}, user={self.user})"


@dataclass
class PartMessage(Message):
    """IRC message for leaving a channel."""
    channel: str
    user: str

    def __str__(self) -> str:
        return f"PartMessage(channel={self.channel}, user={self.user})"


@dataclass
class NamesMessage(Message):
    """IRC message for a list of connected users."""
    channel: str
    users: list[str]

    def __str__(self) -> str:
        return f"NamesMessage(channel={self.channel}, {len(self.users)} users)"


@dataclass
class EndOfNamesMessage(Message):
    """IRC message for the end of a list of connected users."""
    channel: str

    def __str__(self) -> str:
        return f"EndOfNamesMessage(channel={self.channel})"


@dataclass
class NoticeMessage(Message):
    """IRC message for system messages, often related to commands."""
    channel: str
    message: str
    tags: dict[str, str]

    def __str__(self) -> str:
        return f"NoticeMessage(channel={self.channel}, "\
               f"message={self.message}, {len(self.tags)} tags)"


@dataclass
class UserstateMessage(Message):
    """IRC message for various data about the user."""
    channel: str
    tags: dict[str, str]

    def __str__(self) -> str:
        return f"UserstateMessage(channel={self.channel}, {len(self.tags)} tags)"


@dataclass
class RoomstateMessage(Message):
    """IRC message for various data about the channel."""
    channel: str
    tags: dict[str, str]

    def __str__(self) -> str:
        return f"RoomstateMessage(channel={self.channel}, {len(self.tags)} tags)"


@dataclass
class ClearchatMessage(Message):
    """IRC message for clearing a chat or all of a single user's message."""
    channel: str
    user: str | None
    tags: dict[str, str]

    def __str__(self) -> str:
        return f"ClearchatMessage(channel={self.channel}, " \
               f"user={self.user}, {len(self.tags)} tags)"


@dataclass
class ClearmsgMessage(Message):
    """IRC message for the deletion of a single message."""
    channel: str
    message: str
    tags: dict[str, str]

    def __str__(self) -> str:
        return f"ClearmsgMessage(channel={self.channel}, " \
               f"message={self.message}, {len(self.tags)} tags)"


@dataclass
class UsernoticeMessage(Message):
    """IRC message for any of various chat events."""
    channel: str
    message: str | None
    tags: dict[str, str]

    def __str__(self) -> str:
        return f"UsernoticeMessage(channel={self.channel}, " \
               f"message={self.message}, {len(self.tags)} tags)"


@dataclass
class WhisperMessage(Message):
    """IRC message for a private message."""
    from_: str
    to: str
    message: str
    tags: dict[str, str]

    def __str__(self) -> str:
        return f"WhisperMessage(from={self.from_}, to={self.to}, " \
               f"message={self.message}, {len(self.tags)} tags)"


@dataclass
class ChatMessage(Message):
    """IRC message for a message sent in chat."""
    channel: str
    user: str
    message: str
    tags: dict[str, str]

    def __str__(self) -> str:
        return f"ChatMessage(channel={self.channel}, user={self.user}, " \
               f"message={self.message}, {len(self.tags)} tags)"
