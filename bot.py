"""Main bot operation."""
# pylint: disable=missing-function-docstring,broad-exception-caught
from __future__ import annotations
from asyncio import new_event_loop, set_event_loop, run_coroutine_threadsafe, sleep
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime
import json
import os
from time import perf_counter
import traceback
from typing import Literal, Type, Any

from dotenv import dotenv_values, set_key
from websockets.exceptions import ConnectionClosed
from websockets.legacy import client

from channel import BaseChannel
from colors import SGR, RGBColor, RGB, printc, colorize, readable
from command import UserRole, Command, DenialReason, BaseContext
from message import (MessageParser, Message, LoginMessage, CapabilitiesMessage,
                     PingMessage, ReconnectMessage, JoinMessage, PartMessage,
                     NamesMessage, EndOfNamesMessage, NoticeMessage, UserstateMessage,
                     RoomstateMessage, ClearchatMessage, ClearmsgMessage, UsernoticeMessage,
                     WhisperMessage, ChatMessage)
from timer_ import Timer
from twirc import TwitchIRCClient


os.system("color")


def divmods(value: int | float, **divisors) -> dict[str, int | float]:
    """Chain divmod calculations together with multiple divisors."""
    divisors = dict(sorted(divisors.items(), key=lambda item: item[1], reverse=True))
    quotients, remainder = {}, value
    for name, divisor in divisors.items():
        quotient, remainder = divmod(remainder, divisor)
        quotients[name] = int(quotient)
    quotients["remainder"] = remainder
    return quotients

def readable_time(unix: int | float | str, time_type: Literal["stamp", "word"]) -> str:
    """
    Convert time in seconds to a readable format.\n
    `stamp` - timestamp, typical stopwatch counter\n
    `word` - letter indicators for each unit, more reader-friendly
    """
    quotients = divmods(float(unix), day=86400, hour=3600, minute=60, second=1)
    hms_time = (str(quotients["hour"]), str(quotients["minute"]), str(quotients["second"]))
    day, milli = str(quotients["day"]), str(round(quotients["remainder"]*1000))
    if time_type == "stamp":
        hms_time = map(lambda x: x.zfill(2), hms_time)
        return f"{day}:{':'.join(hms_time)}.{milli.zfill(3)}"
    word_time = list(
            filter(lambda x: not x.startswith('0'),
                   [f"{day}d", f"{hms_time[0]}h", f"{hms_time[1]}m", f"{hms_time[2]}s"])
        )
    return ' '.join(word_time) if word_time else "0s"

def get_name_color(hex_string: str) -> RGBColor:
    """Convert username color tag to RGB, and then adjust for readability."""
    return readable(RGBColor.from_hex(hex_string))


@dataclass
class BaseConfig:
    """Configuration data for the Twitch bot."""
    username: str
    online_channels: tuple[str]
    offline_channels: tuple[str]
    usernames_folder: str
    rich_irc: bool
    show_errors: bool
    history_limit: int
    timestamp_format: str
    uri: str
    client_id: str
    client_secret: str
    oauth: str
    capability: tuple[str]

    @classmethod
    def from_env(cls) -> BaseConfig:
        """Create a config instance from a .env file."""
        config_fields = [field.name.upper() for field in fields(cls)]
        config = dict(dotenv_values(".env").items())
        if not set(config_fields).issubset(set(config.keys())):
            raise RuntimeError("One or more configuration fields are missing")
        for key, value in config.items():
            if key in {"ONLINE_CHANNELS", "OFFLINE_CHANNELS", "CAPABILITY"}:
                config[key] = tuple(json.loads(value))  # type: ignore
            elif key in {"RICH_IRC", "SHOW_ERRORS"}:
                config[key] = value == "True"  # type: ignore
            elif key in {"HISTORY_LIMIT"}:
                config[key] = int(value)  # type: ignore
            elif key not in config_fields:
                del config[key]
        config = {key.lower(): value for key, value in config.items()}
        return cls(**config)  # type: ignore

    @staticmethod
    def initialize_env():
        """Create a default .env file."""
        default = {
            "USERNAME": '',
            "ONLINE_CHANNELS": [],
            "OFFLINE_CHANNELS": [],
            "USERNAMES_FOLDER": '',
            "RICH_IRC": True,
            "SHOW_ERRORS": True,
            "HISTORY_LIMIT": 1000,
            "TIMESTAMP_FORMAT": "12h",
            "URI": "ws://irc-ws.chat.twitch.tv:80",
            "CLIENT_ID": '',
            "CLIENT_SECRET": '',
            "OAUTH": '',
            "CAPABILITY": ["commands", "membership", "tags"]
            }
        for key, value in default.items():
            BaseConfig.set_variable(key, value)

    @staticmethod
    def set_variable(key: str, value: Any):
        """Set an environment variable."""
        if isinstance(value, list):
            value = json.dumps(value)
        set_key(".env", key, str(value), quote_mode="never")

    @property
    def is_valid(self) -> bool:
        """Whether the bot has a (mostly) valid configuration."""
        if not self.channels:  # no channels added
            return False
        config_fields = [field.name.upper() for field in fields(self)]
        for field_name in config_fields:
            field_value = getattr(self, field_name.lower())
            if (field_name not in {"ONLINE_CHANNELS", "OFFLINE_CHANNELS"}
                    and not field_value):
                return False
            match field_name:
                case "USERNAMES_FOLDER":
                    if all(separator not in field_value
                           for separator in (os.path.sep, os.path.altsep)):
                        return False
                case "RICH_IRC" | "SHOW_ERRORS":
                    if not isinstance(field_value, bool):
                        return False
                case "HISTORY_LIMIT":
                    if not isinstance(field_value, int):
                        return False
                case "URI":
                    if "://irc" not in field_value:
                        return False
                case "CLIENT_ID" | "CLIENT_SECRET":
                    if not (len(field_value) == 30 and field_value.isalnum()):
                        return False
                case "OAUTH":
                    if not (len(field_value) == 36 and field_value.startswith("oauth:")
                            and field_value[6:].isalnum()):
                        return False
        return True

    @property
    def channels(self) -> set[str]:
        """All channels the bot connects to."""
        return set(self.online_channels) | set(self.offline_channels)


@dataclass(slots=True)
class Ranks:
    """User permission data not provided in messages."""
    owner: str
    admins: list[str] = field(default_factory=list)
    blacklist: list[str] = field(default_factory=list)

    def check_blacklist(self, user: str) -> DenialReason:
        """Check if a user is currently blacklisted from the bot."""
        return DenialReason.BLACKLIST if user in self.blacklist else DenialReason.NONE


SUBSCRIBER_COLOR = RGBColor(145, 70, 255)


class BaseBot:
    """Universal chat bot manager for all connected channels."""

    def __init__(self, config_cls: Type[BaseConfig], active: bool = True):
        assert os.path.exists(".env"), ".env file missing"
        assert issubclass(config_cls, BaseConfig)
        try:
            self.config = config_cls.from_env()
        except Exception as e:
            print(e)
            print("Loading .env failed, generating a default...")
            BaseConfig.initialize_env()
            print("Update the .env file with necessary values and restart the bot.")
        if not self.config or not self.config.is_valid:
            raise RuntimeError("Invalid config file")

        try:
            with open("ranks.json", 'r', encoding="UTF-8") as file:
                ranks = json.loads(file.read())
            self.ranks = Ranks(**ranks)
        except FileNotFoundError:
            print("ranks.json not found, creating one...")
            self.ranks = Ranks(owner=self.config.username)  # default owner is the bot itself
            with open("ranks.json", 'w', encoding="UTF-8") as file:
                file.write(json.dumps(asdict(self.ranks), indent=4, separators=(',', ': ')))
            print("Edit ranks.json and relaunch the bot to update ranks.")

        self.start_time = perf_counter()
        self.running = None
        self.restarts = 0
        self.channels: dict[str, BaseChannel] = {}
        self.active = active
        self.event_loop = new_event_loop()
        set_event_loop(self.event_loop)
        self.irc = TwitchIRCClient(rich_irc=self.config.rich_irc)

    async def poll_irc(self):
        """Poll the Twitch server continuously for incoming messages."""
        while self.running:
            raw_data: str = await self.irc.websocket.recv()  # type: ignore
            messages = raw_data.strip().split("\r\n")
            for line in messages:
                msg = MessageParser.from_raw(line)
                await self.message_handler(msg)

    async def start(self):
        """Start the bot."""
        async with client.Connect(self.config.uri) as websocket:
            self.irc.websocket = websocket
            self.running = True

            try:
                server_poll = run_coroutine_threadsafe(self.poll_irc(), self.event_loop)
                await self.irc.login(self.config.username, self.config.oauth)
                await self.irc.request_capabilities(list(self.config.capability))
                await sleep(2)  # give time for twitch to respond
                await self._set_up_channels()
                # preload live check in case the timer starts late
                await Timer.timers["check_live_status"](self)
                while self.running:
                    for func in Timer.timers.values():
                        await func(self)
                    if server_poll.done():
                        print(server_poll.result())
                        self.running = False
                    await sleep(1)
            except KeyboardInterrupt:
                pass
            except ConnectionClosed:
                self.restarts += 1
                printc(f"Restarting the bot... (Count: {self.restarts})", RGB.ORANGE)
                self.running = False
                await self.start()
            except Exception:
                print(traceback.format_exc())

    async def _set_up_channels(self):
        """Set up channels listed in the config file."""
        self.channels.clear()
        for channel_name in self.config.channels:
            active_online = channel_name in self.config.online_channels
            active_offline = channel_name in self.config.offline_channels
            await self._add_channel(channel_name, active_online, active_offline)
            await self.irc.join(channel_name)  # type: ignore

    async def _add_channel(self, channel_name: str, active_online: bool, active_offline: bool):
        """Add a channel to the bot."""
        self.channels[channel_name] = BaseChannel(
            self, self.config.usernames_folder, channel_name, active_online, active_offline)

    async def message_handler(self, msg: Message):
        """Process every message received from Twitch."""
        if msg.type_ in {"002", "003", "004", "375", "372",  # ignored
                        "376", "GLOBALUSERSTATE", "HOSTTARGET"}:
            return
        handlers = {
            "001": self._handle_001,
            "CAP * ACK": self._handle_cap_ack,
            "PING": self._handle_ping,
            "RECONNECT": self._handle_reconnect,
            "WHISPER": self._handle_whisper,
            "353": self._handle_353,
            "JOIN": self._handle_join,
            "PART": self._handle_part,
            "366": self._handle_366,
            "NOTICE": self._handle_notice,
            "USERSTATE": self._handle_userstate,
            "ROOMSTATE": self._handle_roomstate,
            "CLEARCHAT": self._handle_clearchat,
            "CLEARMSG": self._handle_clearmsg,
            "USERNOTICE": self._handle_usernotice,
            "PRIVMSG": self._handle_privmsg  # any user-sent message
            }
        if (handler := handlers.get(msg.type_)):
            if msg.type_ in {"001", "CAP * ACK", "PING", "RECONNECT", "WHISPER"}:
                await handler(msg)
            else:
                channel = self.channels.get(msg.channel, None)  # type: ignore
                await handler(channel, msg)
        elif self.config.rich_irc:
            print(f"Unhandled IRC type: {msg} {msg.raw}")

    async def _handle_001(self, msg: LoginMessage):
        if not self.config.rich_irc:
            return
        print(f'<[{colorize(msg.type_, RGB.ORANGE)}] {colorize("Login successful!", RGB.GREEN)}')

    async def _handle_cap_ack(self, msg: CapabilitiesMessage):
        if self.config.capability and set(msg.capabilities) != set(self.config.capability):
            raise RuntimeError("Acquired capabilities do not match requested")
        if self.config.rich_irc:
            print(f'<[{colorize(msg.type_, RGB.ORANGE)}] {", ".join(msg.capabilities)}')

    async def _handle_ping(self, msg: PingMessage):
        await self.irc.pong()  # type: ignore
        if self.config.rich_irc:
            print(f'<[{colorize(msg.type_, RGB.ORANGE)}]')

    async def _handle_reconnect(self, msg: ReconnectMessage):
        # server will disconnect for you, just clean up/save
        if self.config.rich_irc:
            print(f'<[{colorize(msg.type_, RGB.ORANGE)}]')

    async def _handle_whisper(self, msg: WhisperMessage):
        print(f'<[{colorize(msg.type_, RGB.ORANGE)}] ' \
              f'{msg.from_} >> {msg.to}: {colorize(msg.message, SGR.YELLOW)}')

    async def _handle_353(self, channel: BaseChannel, msg: NamesMessage):
        channel.userdata.users.update(set(msg.users))

    async def _handle_join(self, channel: BaseChannel, msg: JoinMessage):
        channel.userdata.users.add(msg.user)

    async def _handle_part(self, channel: BaseChannel, msg: PartMessage):
        channel.userdata.users.discard(msg.user)

    async def _handle_366(self, channel: BaseChannel, msg: EndOfNamesMessage):
        # channel connection message (end of connected users list)
        channel.connected = True
        output_366: str = f'Successfully connected to {colorize(f"#{channel.name}", SGR.BLUE)}! ' \
                          f'{len(channel.userdata.users)} users connected.'
        if self.config.rich_irc:
            output_366 = f'<[{colorize(msg.type_, RGB.ORANGE)}] {output_366}'
        print(output_366)
        if not self.irc:
            raise RuntimeError("IRC client not connected")
        # migrated from handle_notice since /mods is no longer usable via irc
        _ = run_coroutine_threadsafe(channel.messenger.message_queue(), self.event_loop)
        if all(channel.connected for channel in self.channels.values()):
            if not (status_cmd := Command.get_by_name("status")):
                raise RuntimeError("status command not found")
            dummy_msg = ChatMessage('', '', '', '', '', {})
            await status_cmd(BaseContext(self, dummy_msg, channel))

    async def _handle_notice(self, channel: BaseChannel, msg: NoticeMessage):
        assert msg.message, f'Expected msg.message from "{msg.type_}"'
        print(f'<[{colorize(msg.type_, RGB.ORANGE)}] ' \
                f'<{colorize(f"#{channel.name}", SGR.BLUE)}> ' \
                f'{msg.message} ({msg.tags["msg-id"]})')

    async def _handle_userstate(self, channel: BaseChannel, msg: UserstateMessage):
        channel.mod = msg.tags["mod"] == "1"

    async def _handle_roomstate(self, channel: BaseChannel, msg: RoomstateMessage):
        if not self.config.rich_irc:
            return
        if (len(msg.tags) > 1
            and all(int(value) != 1 for value in msg.tags.values())
            and int(msg.tags["followers-only"]) == -1):
            print(f'<[{colorize(msg.type_, RGB.ORANGE)}] ' \
                  f'<{colorize(f"#{channel.name}", SGR.BLUE)}> Chat in default state.')
        else:
            output_roomstate: list[str] = []
            if len(msg.tags) == 1:
                output_roomstate.append(f"{tuple(msg.tags.keys())[0]} mode disabled.")
            else:
                for tag, value in msg.tags.items():
                    if tag == "followers-only" and int(value) != -1:
                        mode = f"{value}-minute {tag} mode enabled."
                        output_roomstate.append(mode)
                    elif int(value) == 1:
                        if tag == "slow":
                            mode = f'{readable_time(value, "word")} {tag} mode enabled.'
                        else:
                            mode = f"{tag} mode enabled."
                        output_roomstate.append(mode)
            print(f'<[{colorize(msg.type_, RGB.ORANGE)}] ' \
                  f'<{colorize(f"#{channel.name}", SGR.BLUE)}> ' \
                  f'{" ".join(output_roomstate)}')

    async def _handle_clearchat(self, channel: BaseChannel, msg: ClearchatMessage):
        if msg.user:
            if "ban-duration" in msg.tags:
                output_cc: str = f'User "{msg.user}" timed out for {msg.tags["ban-duration"]}s'
            else:
                output_cc = f'User "{msg.user}" banned'
            print(f'<[{colorize(msg.type_, RGB.ORANGE)}] ' \
                  f'<{colorize(f"#{channel.name}", SGR.BLUE)}> {output_cc}')
            if msg.user == self.config.username:
                if "ban-duration" in msg.tags:
                    channel.messenger.timeout = (
                        channel.messenger.timeout+int(msg.tags["ban-duration"])+1)
                else:
                    channel.messenger.timeout = -1
                print(f'<{colorize(f"#{channel.name}", SGR.BLUE)}> ' \
                      f'Timeout set to {msg.tags["ban-duration"]}.')
        else:
            print(f'<[{colorize(msg.type_, RGB.ORANGE)}] ' \
                  f'<{colorize(f"#{channel.name}", SGR.BLUE)}> ' \
                  f'Chat was cleared by a moderator')

    async def _handle_clearmsg(self, channel: BaseChannel, msg: ClearmsgMessage):
        print(f'<[{colorize(msg.type_, RGB.ORANGE)}] <{colorize(f"#{channel.name}", SGR.BLUE)}> ' \
              f'Message from "{msg.tags["login"]}" deleted: {msg.message}')

    async def _handle_usernotice(self, channel: BaseChannel, msg: UsernoticeMessage):
        system_message = msg.tags["system-msg"].replace(r"\s",' ')
        if system_message:
            system_message += " - "
        login_user = msg.tags["login"] if "login" in msg.tags else ''
        notice_message = f": {msg.message}" if msg.message else ''
        print(f'<[{colorize(msg.type_, RGB.ORANGE)}] <{colorize(f"#{channel.name}", SGR.BLUE)}> ' \
              f'({msg.tags["msg-id"]}) {system_message}{login_user}{notice_message}')

    async def _handle_privmsg(self, channel: BaseChannel, msg: ChatMessage):
        # store/update user_id data
        user_id = msg.tags["user-id"]
        if msg.user not in channel.uid_manager.users[user_id]:
            if channel.uid_manager.users[user_id] and channel.mod:
                previous_names = channel.uid_manager.users[user_id]
                printc(f'Name change detected: ' \
                       f'{", ".join(previous_names)} >> {msg.user}', RGB.PINK)
            channel.uid_manager.users[user_id].append(msg.user)

        # update mod roles
        if msg.tags["mod"] == '1':
            channel.userdata.mods.add(msg.user)
        else:
            channel.userdata.mods.discard(msg.user)

        # log to console
        user_role = UserRole.from_message(self.ranks, msg)
        display_name = msg.tags["display-name"] if "display-name" in msg.tags else msg.user
        name_color = (get_name_color(msg.tags["color"][1:]) if msg.tags["color"] else RGB.GRAY)
        colored_display_name = colorize(display_name, name_color)
        if user_role & UserRole.SUB:
            display_name = f"[SUB] {display_name}"
            colored_display_name = f'[{colorize("SUB", SUBSCRIBER_COLOR)}] {colored_display_name}'
        if user_role & UserRole.MOD:
            display_name = f"[MOD] {display_name}"
            colored_display_name = f'[{colorize("MOD", RGB.GREEN)}] {colored_display_name}'
        elif user_role & UserRole.VIP:
            display_name = f"[VIP] {display_name}"
            colored_display_name = f'[{colorize("VIP", RGB.PINK)}] {colored_display_name}'

        uptime = round(perf_counter()-self.start_time, 3)
        timestamp_format = self.config.timestamp_format
        match timestamp_format:
            case 'uptime':
                timestamp = readable_time(uptime, "stamp")
            case '12h' | '24h':
                date_time = datetime.fromtimestamp(int(msg.tags["tmi-sent-ts"])/1000)
                time_format = "%I:%M:%S %p" if timestamp_format == '12h' else "%H:%M:%S"
                timestamp = datetime.strftime(date_time, time_format)

        if msg.message.startswith("/me"):
            colored_message = f'{colored_display_name} {colorize(msg.message[4:], name_color)}'
        else:
            colored_message = f'{colored_display_name}: {colorize(msg.message, SGR.YELLOW)}'
        print(f'    [{colorize(timestamp, SGR.CYAN)}] ' \
              f'<{colorize(f"#{channel.name}", SGR.BLUE)}> {colored_message}')

        # update chat history
        if len(channel.history) == self.config.history_limit:
            channel.purge_oldest_message()
        channel.history.append({"timestamp": uptime,
                                "display_name": display_name,
                                "username": msg.user,
                                "message": msg.message})
        channel.userdata.history[msg.user].append((uptime, msg.message))

        await Command.check_command(self, msg)
