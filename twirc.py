"""Anything that involves sending IRC messages to Twitch."""
from websockets.legacy.protocol import WebSocketCommonProtocol

from colors import SGR, RGB, colorize


class NullWebsocket:
    """Placeholder for when a websocket is not available."""

    def __init__(self):
        pass

    async def send(self, _: str):
        """Send a message."""
        print("No websocket to send to")

    async def recv(self, _: str):
        """Receive the next message."""
        print("No websocket to receive from")


class TwitchIRCClient:
    """IRC client for communicating with Twitch via websocket."""

    def __init__(self, websocket: WebSocketCommonProtocol | None = None,
                 rich_irc: bool = False):
        self.websocket = websocket or NullWebsocket()
        self.rich_irc = rich_irc

    async def _pass(self, oauth: str):
        """Send password (oauth) to the server for login."""
        await self.websocket.send(f"PASS {oauth}")
        if self.rich_irc:
            print(f">[{colorize('PASS', RGB.ORANGE)}] oauth:***")

    async def _nick(self, username: str):
        """Send username to the server for login."""
        await self.websocket.send(f"NICK {username}")
        if self.rich_irc:
            print(f">[{colorize('NICK', RGB.ORANGE)}] {username}")

    async def login(self, username: str, oauth: str):
        """Send account credentials for login."""
        await self._pass(oauth)
        await self._nick(username)

    async def request_capabilities(self, caps: list[str]):
        """
        Send requests for various Twitch capabilities.
        The three standard capabilities are commands, membership, and tags.
        """
        full_caps = [f"twitch.tv/{cap}" for cap in caps]
        await self.websocket.send(f"CAP REQ :{' '.join(full_caps)}\r\n")
        if self.rich_irc:
            print(f'>[{colorize("CAP REQ", RGB.ORANGE)}] {", ".join(caps)}')

    async def join(self, channel: str):
        """Send a request to join a channel."""
        await self.websocket.send(f"JOIN #{channel}")
        if self.rich_irc:
            print(f'>[{colorize("JOIN", RGB.ORANGE)}] {colorize(f"#{channel}", SGR.BLUE)}')

    async def part(self, channel: str):
        """Send a request to leave a channel."""
        await self.websocket.send(f"PART #{channel}")
        if self.rich_irc:
            print(f'>[{colorize("JOIN", RGB.ORANGE)}] {colorize(f"#{channel}", SGR.BLUE)}')

    async def pong(self):
        """Respond to a ping from the server to keep the bot connected."""
        await self.websocket.send("PONG :tmi.twitch.tv")
        if self.rich_irc:
            print(f">[{colorize('PONG', RGB.ORANGE)}]")

    async def submit(self, channel: str, message: str, show: bool = True):
        """Submit a chat message directly to a channel."""
        await self.websocket.send(f"PRIVMSG #{channel} :{message}")
        if show:
            print(f'[{colorize("BOT", RGB.GREEN)}] <{colorize(f"#{channel}", SGR.BLUE)}> ' \
                  f'{colorize(message, SGR.YELLOW)}')
