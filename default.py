"""Default bot functionality that persists across bot applications."""
# pylint: disable=missing-function-docstring
from collections import defaultdict
from time import perf_counter

import requests

from bot import BaseBot
from colors import SGR, RGB, printc, colorize, colorize_type
from command import CommandPerm, Command, ArgumentError, BaseContext
from timer_ import Timer


# TIMERS - background management

@Timer.timer("check_live_status", interval=30)
async def check_live_status(bot: BaseBot):
    """Update live status for all connected channels."""
    for channel in bot.channels.values():
        live_status = requests.get(f"https://beta.decapi.me/twitch/uptime" \
                                   f"/{channel.name}?offline_msg=OFFLINE", timeout=1).text
        channel.live = live_status != "OFFLINE"

@Timer.timer("update_command_cooldowns", interval=1)
async def update_command_cooldowns(bot: BaseBot):
    """Update command cooldowns to remove those that expired."""
    for channel in bot.channels.values():
        channel.cooldowns = {
            k: v for k, v in channel.cooldowns.items() if v-perf_counter() > 0}
        for username, cooldowns in channel.userdata.cooldowns.items():
            channel.userdata.cooldowns[username] = {
                k: v for k, v in cooldowns.items() if v-perf_counter() > 0}
        channel.userdata.cooldowns = defaultdict(dict,
            {k: v for k, v in channel.userdata.cooldowns.items() if v})

@Timer.timer("reset_sent", interval=30)
async def reset_sent(bot: BaseBot):
    """Reset counter for sent messages to refresh rate limit calculation."""
    for channel in bot.channels.values():
        channel.messenger.sent = 0

@Timer.timer("save_uids", interval=5*60)
async def save_uids(bot: BaseBot):
    """Save all username data to file."""
    for channel in bot.channels.values():
        channel.uid_manager.save_users()


# FUNCTIONS - helpers


# COMMANDS - interactivity

@Command.command("bot", "<state=on|off> <scope=global|local>",
                 "Toggle bot responses everywhere or per-channel.", CommandPerm.ADMIN)
async def toggle_bot(ctx: BaseContext):
    active = ctx.args["state"] == "on"
    match ctx.args["scope"]:
        case "global":
            ctx.bot.active = active
            await ctx.channel.send("Global bot responses enabled.")
        case "local":
            ctx.channel.active = active
            await ctx.channel.send("Channel bot responses enabled.")

@Command.command("cmds", None, "List all commands in chat.", global_cd=10)
async def show_commands(ctx: BaseContext):
    command_displays = []
    cmds = list(Command.commands.values())
    for cmd in cmds:
        if cmd.hide:
            continue
        command_display = cmd.trigger
        if not cmd.active:
            command_display = f"~{command_display}"
        if cmd.perm:
            command_display = f"{command_display} ({cmd.perm})"
        command_displays.append(command_display)
    await ctx.channel.send(f'@{ctx.user} Available commands: {", ".join(command_displays)}')

@Command.command("help", "<command>", "Get a description of a command.")
async def command_help(ctx: BaseContext):
    if not (cmd := Command.get_by_name(ctx.args["command"])):
        raise ArgumentError(f'Command {ctx.args["command"]} not found')
    await ctx.channel.send(str(cmd))

@Command.command("status", None,
                 "Display per-channel bot status in the console.", CommandPerm.ADMIN)
async def list_statuses(ctx: BaseContext):
    printc("[BOT STATUS]", RGB.PINK)
    for channel in ctx.bot.channels.values():
        print(f'    <{colorize(f"#{channel.name}", SGR.BLUE)}> - ' \
              f'Live status: {colorize_type(channel.live)}, ' \
              f'Mod status: {colorize_type(channel.mod)}, ' \
              f'Locally active: {colorize_type(channel.active)}')

@Command.command("live", None, "Check if the stream is currently live.", global_cd=10, user_cd=30)
async def show_live_status(ctx: BaseContext):
    await ctx.channel.send(f"Live status: {ctx.channel.live}")

@Command.command("users", None, "List connected users in console.", CommandPerm.ADMIN)
async def list_users(ctx: BaseContext):
    printc(f'Connected users ({len(ctx.channel.userdata.users)}):', RGB.PINK)
    printc(", ".join(ctx.channel.userdata.users), RGB.PINK)

@Command.command("mods", None, "List recognized channel moderators in console.", CommandPerm.ADMIN)
async def list_mods(ctx: BaseContext):
    printc(f'Channel moderators ({len(ctx.channel.userdata.mods)}):', RGB.PINK)
    printc(", ".join(ctx.channel.userdata.mods), RGB.PINK)

@Command.command("say", "<message+>", "Repeat the text given to the bot.", CommandPerm.MOD)
async def repeat_message(ctx: BaseContext):
    await ctx.channel.send(ctx.args["message"])

@Command.command("toggle", "<command> <state=on|off> <scope=global|local>",
                 "Toggle a command everywhere or per-channel.", CommandPerm.ADMIN)
async def toggle_command(ctx: BaseContext):
    if ctx.args["command"] == "toggle":
        raise ArgumentError("Cannot toggle the toggle command")
    if not (cmd := Command.get_by_name(ctx.args["command"])):
        raise ArgumentError(f'Command {ctx.args["command"]} not found')
    active = ctx.args["state"] == "on"
    channel = ctx.channel.name if ctx.args["scope"] == "local" else None
    cmd.toggle(active, channel)
    await ctx.channel.send(
        f'Command "{ctx.args["command"]}" ' \
        f'{"enabled" if active else "disabled"}' \
        f'{"" if channel else " globally"}.'
        )

@Command.command("prefix", "[admin:prefix]",
                 "Show or change the default command prefix.", CommandPerm.ADMIN)
async def default_prefix(ctx: BaseContext):
    if "prefix" not in ctx.args:
        await ctx.channel.send(f'Current command prefix is "{Command.default_prefix}"')
        return
    allowed_prefixes = r"!#$%&'()*+,-:;<=>?@[\]^_`{|}~"
    if ctx.args["prefix"] not in allowed_prefixes:
        raise ArgumentError(rf"Invalid prefix, choose from {allowed_prefixes}")
    Command.set_prefix(ctx.args["prefix"])
    await ctx.channel.send(f'Default command prefix updated to "{ctx.args["prefix"]}".')

@Command.command("@", "<channel> <message>", "Send a message to another channel.",
                 CommandPerm.ADMIN, prefix='', hide=True)
async def cross_chat(ctx: BaseContext):
    if not (channel := ctx.bot.channels.get(ctx.args["channel"])):
        raise RuntimeError(f'Channel "{ctx.args["channel"]}" not found!')
    await channel.send(f'<#{ctx.channel.name}> {ctx.user}: {ctx.args["message"]}')
