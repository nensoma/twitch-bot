"""Custom bot functionality and actual bot execution."""
# pylint: disable=unused-import,unused-argument,redefined-outer-name
from __future__ import annotations
from dataclasses import dataclass, fields
import importlib
import json
from typing import Type

from dotenv import dotenv_values

from bot import BaseConfig, BaseBot
from channel import BaseChannel
from colors import printc, RGB, colorize_type
from command import UserRole, BaseContext, Command, CommandPerm, ArgumentError
from timer_ import Timer

importlib.import_module("default")


# BOT - main operation logic

class Channel(BaseChannel):
    """Handles information for each channel the bot connects to."""

    def __init__(self, bot: Bot, name: str, active_online: bool, active_offline: bool):
        super().__init__(bot, name, active_online, active_offline)
        # custom attributes and function calls


@dataclass
class Config(BaseConfig):
    """Configuration data for the Twitch bot."""
    # custom attributes

    @classmethod
    def from_env(cls) -> Config:
        config_fields = [field.name.upper() for field in fields(cls)]
        config = dict(dotenv_values(".env").items())
        if not set(config_fields).issubset(set(config.keys())):
            raise RuntimeError("One or more configuration fields are missing")
        for key, value in config.copy().items():
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


class Bot(BaseBot):
    """Universal chat bot manager for all connected channels."""

    def __init__(self, config_cls: Type[BaseConfig], active: bool = True):
        super().__init__(config_cls, active)
        self.config: Config
        # custom attributes and function calls

    async def _add_channel(self, channel_name: str, active_online: bool, active_offline: bool):
        self.channels[channel_name] = Channel(self, channel_name, active_online, active_offline)


@dataclass(slots=True)
class Context(BaseContext):
    """Object for passing runtime data to a command."""
    bot: Bot
    channel: Channel


# TIMERS - background management

#@Timer.timer("timer_template", interval=60)
#async def timer_template(bot: Bot):
#    pass


# FUNCTIONS - helpers


# COMMANDS - interactivity

#@Command.command("command_template", None, "Command description.")
#async def command_template(ctx: Context):
#    pass


if __name__ == "__main__":
    bot = Bot(Config, active=True)
    bot.event_loop.run_until_complete(bot.start())
