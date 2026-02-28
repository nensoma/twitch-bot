"""Logic for implementing commands for a Twitch bot."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag, Flag
from string import printable as PRINTABLE
import time
from typing import Callable, TYPE_CHECKING

from channel import BaseChannel
from colors import RGB, printc
from message import ChatMessage

if TYPE_CHECKING:
    from bot import BaseBot, Ranks


class UserRole(IntFlag):
    """Roles for command permissions."""
    NONE = 0
    SUB = 1 << 0
    VIP = 1 << 1
    MOD = 1 << 2
    ADMIN = 1 << 3
    OWNER = 1 << 4

    def __str__(self):
        output = [role.name.lower() for role in reversed(UserRole)
                  if role and role.name and self & role]
        return '+'.join(output)

    @classmethod
    def from_message(cls, ranks: Ranks, msg: ChatMessage) -> UserRole:
        """Get user role from a message."""
        role = cls.NONE
        if msg.user == ranks.owner:
            role |= cls.OWNER
        if msg.user in ranks.admins:
            role |= cls.ADMIN
        if msg.tags["mod"] == '1':
            role |= cls.MOD
        elif msg.tags["user-type"] == "vip":
            role |= cls.VIP
        if msg.tags["subscriber"] == '1':
            role |= cls.SUB
        return role


class DenialReason(Flag):
    """Reasons for denied command execution."""
    NONE = 0
    GLOBAL_COOLDOWN = 1 << 0
    USER_COOLDOWN = 1 << 1
    PERMISSION = 1 << 2
    BLACKLIST = 1 << 3


class CommandPerm(IntEnum):
    """Permissions for user roles."""
    NONE = 0
    SUB = 1 << 0
    VIP = 1 << 1
    MOD = 1 << 2
    ADMIN = 1 << 3
    OWNER = 1 << 4

    def __str__(self):
        return self.name.lower()

    def check_role(self, role: UserRole) -> DenialReason:
        """Check if a user has permission to trigger a command."""
        if role & UserRole.OWNER:
            return DenialReason.NONE
        allowed = role & UserRole.SUB if self == CommandPerm.SUB else role >= self
        return DenialReason.NONE if allowed else DenialReason.PERMISSION


@dataclass(slots=True)
class BaseContext:
    """Object for passing runtime data to a command."""
    bot: BaseBot
    msg: ChatMessage
    channel: BaseChannel
    args: dict[str, str] = field(default_factory=dict)

    @property
    def user(self) -> str:
        """Shorthand access to the user associated with a message."""
        return self.msg.user


@dataclass(slots=True)
class Parameter:
    """A parameter for a command with various customization options."""
    name: str = ''
    required: bool = True
    perm: CommandPerm = CommandPerm.NONE
    options: set[str] | None = None
    remainder: bool = False


class Parameters:
    """Handler for multiple command parameters."""

    def __init__(self, entries: list[Parameter | str]):
        self.entries = entries

    def parse_args(self, arg_string: str | None, role: UserRole) -> dict[str, str]:
        """Parse matched command arguments into a dictionary."""
        matched = {}
        if not self.entries:
            return matched
        if not arg_string:
            if not any(param.required if isinstance(param, Parameter) else True
                       for param in self.entries):
                return matched
            raise ArgumentError("No argument(s) provided")
        if isinstance(self.entries[-1], Parameter) and self.entries[-1].remainder:
            args = arg_string.strip().split(' ', len(self.entries)-1)
        else:
            args = arg_string.strip().split(' ')
        min_args = len(tuple(param for param in self.entries
                             if (isinstance(param, Parameter) and param.required)
                             or isinstance(param, str)))
        max_args = len(self.entries)
        if len(args) not in range(min_args, max_args+1):
            arg_range = str(min_args) if min_args == max_args else f"{min_args}-{max_args}"
            raise ArgumentError(f"Too few/many arguments ({arg_range} required)")
        for i, arg in enumerate(args):
            param = self.entries[i]
            if isinstance(param, str):
                if arg != param:
                    raise ArgumentError("Format error in arguments")
            elif isinstance(param, Parameter):
                if param.options and arg not in param.options:
                    raise ArgumentError(f'Argument "{arg}" not in {param.options}')
                if role < param.perm:
                    if param.required:
                        raise ArgumentError(f'Insufficient perms for parameter ' \
                                            f'"{param.name}": {param.perm}')
                    continue
                matched[param.name] = arg
        return matched

    @classmethod
    def from_syntax(cls, syntax: str | None) -> Parameters:
        """Generate parameters from a syntax string."""
        params: list[Parameter | str] = []
        if not syntax:
            return Parameters(params)
        # <required> [optional] <perm:parameter> <option=this|that> <remainder+>
        roles = {str(perm): perm for perm in CommandPerm}
        for i, clause in enumerate(syntax.split()):
            if clause.startswith(('<', '[')) and clause.endswith(('>', ']')):
                parameter = Parameter()
                if clause.startswith('<'):
                    if any(not param.required for param in params if isinstance(param, Parameter)):
                        raise ParameterError("Optional parameter before required parameter")
                else:
                    parameter.required = False
                tag = clause[1:-1]
                if ':' in tag:
                    perm_name, tag = tag.split(':', 1)
                    parameter.perm = roles[perm_name]
                if '=' in tag:
                    parameter.name, tag = tag.split('=', 1)
                    parameter.options = set(tag.split('|'))
                elif tag.endswith('+'):
                    if i != len(syntax.split()) - 1:
                        raise ParameterError("Remainder parameter must be last in the syntax")
                    parameter.remainder, parameter.name = True, tag[:-1]
                else:
                    parameter.name = tag
                params.append(parameter)
            else:
                params.append(clause)
        if len({param.name for param in params if isinstance(param, Parameter)}) != len(params):
            raise ParameterError("Duplicate parameter(s)")
        return Parameters(params)


class Command:
    """
    Convert a function into a full-featured chat command.\n
    The function can still be run independently of the
    command by awaiting `Command.commands[name]()`.
    """
    commands: dict[str, Command] = {}
    default_prefix: str = '!'

    def __init__(self, func: Callable, name: str, syntax: str | None, desc: str,
                 perm: CommandPerm, prefix: str | None, aliases: list[str] | None,
                 global_cd: int, user_cd: int, hide: bool, active: bool):
        self.func = func
        self.name = name
        self.syntax = syntax
        self.desc = desc
        self.perm = perm
        self.prefix = prefix
        self.aliases = aliases or []
        self.global_cd = global_cd
        self.user_cd = 0 if user_cd <= global_cd else user_cd
        self.hide = hide
        self.active = active
        self.params: Parameters = Parameters.from_syntax(syntax)
        self.disabled_channels: set[str] = set()

        Command.commands[self.name] = self
        for alias in self.aliases:
            Command.commands[alias] = self

    def __str__(self):
        syntax = f" {self.syntax}" if self.syntax else ''
        perm = f" ({self.perm})" if self.perm else ''
        aliases = f" (Aliases: {', '.join(self.aliases)})" if self.aliases else ''
        return f'[CMD] {self.trigger}{syntax}{perm} - {self.desc}{aliases}'

    async def __call__(self, *args, **kwargs):
        await self.func(*args, **kwargs)

    def toggle(self, active: bool, channel: str | None = None):
        """Toggles a command globally or per-channel."""
        if channel is None:
            self.active = active
        elif active:
            self.disabled_channels.discard(channel)
        else:
            self.disabled_channels.add(channel)

    def apply_cooldown(self, channel: BaseChannel, msg: ChatMessage,
                       global_cd: int | None = None,
                       user_cd: int | None = None):
        """
        Apply a cooldown to a command, i.e. it cannot be
        triggered again for a certain amount of time.\n
        Inherits lengths from the command by default, but
        can be overridden using `global_cd` and `user_cd`.
        """
        if self.global_cd or global_cd:
            channel.set_cooldown(
                self.name, time.perf_counter() + (global_cd or self.global_cd))
        if (self.user_cd
            or (user_cd and (global_cd and user_cd > global_cd
                             or user_cd > self.global_cd))):
            channel.set_cooldown(
                self.name, time.perf_counter() + (user_cd or self.user_cd), msg.user)

    def check_cooldowns(self, channel: BaseChannel, msg: ChatMessage) -> DenialReason:
        """Check if a command has any cooldown currently active."""
        reason = DenialReason.NONE
        if self.name in channel.cooldowns:
            reason |= DenialReason.GLOBAL_COOLDOWN
        if (msg.user in channel.userdata.cooldowns
            and self.name in channel.userdata.cooldowns[msg.user]):
            reason |= DenialReason.USER_COOLDOWN
        return reason

    async def handle_denial(self, channel: BaseChannel, username: str, reason: DenialReason):
        """Handle various reasons for the execution of a command being rejected."""
        if reason & DenialReason.BLACKLIST:
            return
        if reason & DenialReason.GLOBAL_COOLDOWN:
            cooldown = int(channel.cooldowns[self.name] - time.perf_counter())
            printc(f'Command "{self.name}" still on cooldown ' \
                   f'for {cooldown} seconds.', RGB.YELLOW)
        if reason & DenialReason.USER_COOLDOWN:
            cooldown = int(channel.userdata.cooldowns[username][self.name] - time.perf_counter())
            printc(f'Command "{self.name}" still on cooldown ' \
                   f'for user "{username}" for {cooldown} seconds.', RGB.YELLOW)
        if reason & DenialReason.PERMISSION and not self.hide:
            await channel.send(f"@{username} Insufficient perms ({self.perm})")

    async def execute(self, bot: BaseBot, msg: ChatMessage,
                      channel: BaseChannel, arg_string: str | None):
        """Execute the code in the command's function, handling arguments and exceptions."""
        if arg_string is not None:
            arg_string = ''.join(filter(lambda x: x in PRINTABLE, arg_string)).strip()
        role = UserRole.from_message(bot.ranks, msg)
        try:
            args = self.params.parse_args(arg_string, role)
            await self(BaseContext(bot, msg, channel, args))
        except Exception as e:  # pylint: disable=broad-except
            printc(repr(e), RGB.RED)
            if bot.config.settings.show_errors:
                await channel.send(f"Error: {str(e)}")
        else:
            if role < UserRole.MOD:
                self.apply_cooldown(channel, msg)

    @classmethod
    def set_prefix(cls, prefix: str):
        """Change the default prefix for all commands without custom prefixes."""
        cls.default_prefix = prefix

    @classmethod
    def get_by_name(cls, name: str) -> Command | None:
        """
        Get Command instance from command name.
        If the command doesn't exist, return `None`.
        """
        return cls.commands.get(name)

    @classmethod
    def get_by_trigger(cls, trigger: str) -> Command | None:
        """
        Get Command instance from command trigger.
        If the command doesn't exist, return `None`.
        """
        return next((cmd for cmd in Command.commands.values()
                     if cmd.trigger == trigger), None)

    @classmethod
    def command(cls, name: str, syntax: str | None = None,
                desc: str = "No description.", perm: CommandPerm = CommandPerm.NONE,
                prefix: str | None = None, aliases: list[str] | None = None,
                global_cd: int = 0, user_cd: int = 0,
                hide: bool = False, active: bool = True):
        """Instantiate a command."""
        def wrapper(func):
            return cls(func, name, syntax, desc, perm, prefix,
                       aliases, global_cd, user_cd, hide, active)
        return wrapper

    @classmethod
    async def check_command(cls, bot: BaseBot, msg: ChatMessage):
        """
        Parse a message to determine if any command
        should be triggered, and if so, handle that command.
        """
        channel = bot.channels[msg.channel]
        parts = msg.message.split(' ', 1)
        start, arg_string = parts if len(parts) == 2 else (parts[0], None)
        if ((cmd := Command.get_by_trigger(start)) and cmd.active
            and msg.channel not in cmd.disabled_channels):
            role = UserRole.from_message(bot.ranks, msg)
            if (reason := (cmd.check_cooldowns(channel, msg)
                           | cmd.perm.check_role(role)
                           | bot.ranks.check_blacklist(msg.user))):
                await cmd.handle_denial(channel, msg.user, reason)
            else:
                await cmd.execute(bot, msg, channel, arg_string)

    @property
    def trigger(self) -> str:
        """The string used to call a function in a chat message."""
        prefix = self.prefix if self.prefix is not None else Command.default_prefix
        return f"{prefix}{self.name}"


class ParameterError(Exception):
    """Command has malformed parameters."""


class ArgumentError(Exception):
    """Command received malformed or invalid arguments."""
