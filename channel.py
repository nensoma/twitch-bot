"""Class for encapsulating per-channel operations."""
from __future__ import annotations
from asyncio import Queue, sleep
from collections import defaultdict
from dataclasses import dataclass
import re
from typing import TypedDict, TYPE_CHECKING

from colors import RGB, printc

if TYPE_CHECKING:
    from bot import BaseBot


class Messenger:
    """Manager for sending messages to a channel's chat."""

    def __init__(self, bot: BaseBot, channel: BaseChannel):
        self.bot = bot
        self.channel = channel
        self.sent: int = 0
        self.last_message: str = ''
        self.sendlist: Queue = Queue()
        self.timeout: int = 0

    async def message_queue(self):
        """Process sent messages through a queue to ensure all are handled properly."""
        while self.bot.running:
            if self.timeout < 0:
                await sleep(1)
            else:
                if self.timeout:
                    printc(f"Still timed out for {self.timeout} seconds.", RGB.YELLOW)
                    while self.timeout > 0:
                        self.timeout = max(0, self.timeout-1)
                        await sleep(1)
                    printc("Timeout finished, resuming message queue.", RGB.PINK)
                message = await self.sendlist.get()
                await self._submit(message)
                await sleep(self.buffer)  # abide by rate limits
                self.sendlist.task_done()

    async def send(self, message: str):
        """Enqueue a message to send to a channel."""
        if message:
            await self.sendlist.put(message)

    async def _submit(self, message: str):
        """Submit a chat message directly to a channel."""
        if message == self.last_message:
            message += " \U000E0000"
        if self.bot.active and self.channel.active and self.channel.activity_allowed:
            if self.sent < self.ratelimit:
                await self.bot.irc.submit(self.channel.name, message)
                self.last_message = message
                self.sent += 1
            else:
                printc(f'Exceeding rate limit for #{self.channel.name}, slow down! ' \
                       f'({self.sent}/{self.ratelimit})', RGB.YELLOW)

    @property
    def ratelimit(self) -> int:
        """Maximum messages per 30 seconds before ratelimit applies."""
        return 100 if self.channel.mod else 20  # messages per 30 seconds

    @property
    def buffer(self) -> float:
        """Minimum time between each message to abide by ratelimit."""
        return 30 / self.ratelimit


@dataclass(slots=True)
class UserData:
    """Per-channel data pertaining to users in chat."""

    users: set[str]
    mods: set[str]
    history: dict[str, list[tuple[float, str]]]
    cooldowns: dict[str, dict[str, float]]

    def break_pings(self, message: str) -> str:
        """
        Break any potential username pings in a string.\n
        This is useful for command responses that include usernames other than the sender's.
        """
        words = message.split()
        for i, word in enumerate(words):
            word = word.strip()
            if (match := re.match(r"@?(\w+),?", word)):
                print(word)
                if match[1].lower() in self.users:
                    index = 2 if word.startswith('@') else 1
                    print(index, f'{word[:index]}|{word[index:]}')
                    words[i] = f'{word[:index]}|{word[index:]}'
        return ' '.join(words)


class BaseChannel:
    """Handles information for each channel the bot connects to."""

    def __init__(self, bot: BaseBot, name: str, active_online: bool, active_offline: bool):

        class HistoryMsg(TypedDict):
            """A message in a channel's message history."""
            timestamp: float
            display_name: str
            username: str
            message: str

        self.name = name
        self.active, self.live, self.mod = True, True, False
        self.active_online, self.active_offline = active_online, active_offline
        self.cooldowns: dict[str, float] = {}
        self.history: list[HistoryMsg] = []
        self.messenger = Messenger(bot, self)
        self.userdata = UserData(set(), set(), defaultdict(list), defaultdict(dict))
        self.connected = False

    async def send(self, message: str):
        """Shorthand for sending a message to a channel via its messenger."""
        await self.messenger.send(message)

    def break_pings(self, message: str) -> str:
        """Shorthand for breaking username pings based on active users."""
        return self.userdata.break_pings(message)

    def set_cooldown(self, command_name: str, expiry: float, user: str | None = None):
        """Add a cooldown for a command, optionally for a specific user."""
        if not user:
            self.cooldowns[command_name] = expiry
        else:
            self.userdata.cooldowns[user][command_name] = expiry

    def purge_oldest_message(self):
        """Remove the oldest message and its data completely from the message history."""
        purge_msg = self.history.pop(0)
        self.userdata.history[purge_msg["username"]].pop(0)
        if not self.userdata.history[purge_msg["username"]]:
            del self.userdata.history[purge_msg["username"]]

    @property
    def activity_allowed(self) -> bool:
        """Whether the channel is configured to be active in the current live state."""
        return self.live and self.active_online or not self.live and self.active_offline
