"""Implementation of console colorization via ANSI escape sequences."""
from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum
import os
from typing import Any


os.system("color")


class ANSIColor(ABC):
    """A color implemented via ANSI escape sequence."""

    @abstractmethod
    def __init__(self):
        pass

    @abstractmethod
    def _as_sequence(self, is_background: bool = False) -> str:
        """ANSI escape sequence for a color."""

    def colorize(self, content: Any, is_background: bool = False) -> str:
        """Colorize a string using ANSI escape sequences."""
        return f"{self._as_sequence(is_background)}{str(content)}\33[0m"


class SGRColor(ANSIColor):
    """An ANSI color that uses a preset Select Graphic Rendition (SGR) parameter."""

    def __init__(self, value: int):
        self.value = value

    def _as_sequence(self, is_background: bool = False) -> str:
        return f"\33[{self.value + (10 if is_background else 0)}m"


class RGBColor(ANSIColor):
    """An ANSI color that supports RGB values directly."""

    def __init__(self, red: int, green: int, blue: int):
        self.red = red
        self.green = green
        self.blue = blue

    def __iter__(self):
        return iter(self.tuple)

    def _as_sequence(self, is_background: bool = False) -> str:
        color_strings = tuple(str(value) for value in self)
        method = 38 + (10 if is_background else 0)
        return f"\33[{method};2;{';'.join(color_strings)}m"

    @classmethod
    def from_hex(cls, hex_string: str) -> RGBColor:
        """Convert a hex string to an RGB color."""
        if len(hex_string) not in {3, 6}:
            raise ValueError("Hex string must be 3 or 6 characters long")
        if any(char.upper() not in "0123456789ABCDEF" for char in hex_string):
            raise ValueError("Invalid hex values")
        if len(hex_string) == 3:
            hex_string = ''.join(char*2 for char in hex_string)
        return cls(int(hex_string[0:2], 16),
                   int(hex_string[2:4], 16),
                   int(hex_string[4:6], 16))

    @property
    def tuple(self):
        """A tuple of the color's RGB values."""
        return (self.red, self.green, self.blue)


class Palette(Enum):
    """A collection of colors implementing ANSI escape sequences."""

    def __getitem__(self, index: int | slice):
        return self.value[index]

    def colorize(self, content: Any, is_background: bool = False) -> str:
        """Colorize a string using ANSI escape sequences."""
        return self.value.colorize(content, is_background)


class SGR(Palette):
    """
    Default SGR colors for console colorization.\n
    Dark colors are available but mostly undesirable.
    """

    DARK_RED = SGRColor(31)
    DARK_GREEN = SGRColor(32)
    DARK_BLUE = SGRColor(34)
    DARK_CYAN = SGRColor(36)
    DARK_MAGENTA = SGRColor(35)
    DARK_YELLOW = SGRColor(33)

    RED = SGRColor(91)
    GREEN = SGRColor(92)
    BLUE = SGRColor(94)
    CYAN = SGRColor(96)
    MAGENTA = SGRColor(95)
    YELLOW = SGRColor(93)

    BLACK = SGRColor(30)
    DARK_GRAY = SGRColor(90)
    LIGHT_GRAY = SGRColor(37)
    WHITE = SGRColor(97)


class RGB(Palette):
    """
    Common RGB colors.\n
    Dark colors are available but mostly undesirable.
    """

    DARK_RED = RGBColor(128, 0, 0)
    DARK_ORANGE = RGBColor(128, 64, 0)
    DARK_YELLOW = RGBColor(128, 128, 0)
    DARK_GREEN = RGBColor(0, 128, 0)
    DARK_BLUE = RGBColor(0, 0, 128)
    DARK_PURPLE = RGBColor(128, 0, 128)

    RED = RGBColor(255, 0, 0)
    ORANGE = RGBColor(255, 128, 0)
    YELLOW = RGBColor(255, 255, 0)
    GREEN = RGBColor(0, 255, 0)
    BLUE = RGBColor(0, 0, 255)
    PURPLE = RGBColor(128, 0, 255)
    PINK = RGBColor(255, 0, 255)

    BLACK = RGBColor(0, 0, 0)
    DARK_GRAY = RGBColor(64, 64, 64)
    GRAY = RGBColor(128, 128, 128)
    LIGHT_GRAY = RGBColor(192, 192, 192)
    WHITE = RGBColor(255, 255, 255)


MIN_COLOR, MAX_COLOR = (255, 85, 85), (85, 85, 255)

def colorize(content: Any, fg_color: SGR | RGB | SGRColor | RGBColor,
             bg_color: SGR | RGB | SGRColor | RGBColor | None = None) -> str:
    """Colorize text using ANSI escape sequences via SGR or RGB formats."""
    if bg_color is None:
        return fg_color.colorize(content)
    fg_color = fg_color.value if isinstance(fg_color, (SGR, RGB)) else fg_color
    bg_color = bg_color.value if isinstance(bg_color, (SGR, RGB)) else bg_color
    if type(fg_color) is not type(bg_color):
        raise TypeError("Mismatched color types")
    return bg_color.colorize(fg_color.colorize(content), is_background=True)

def printc(content: str, fg_color: SGR | RGB | RGBColor,
           bg_color: SGR | RGB | RGBColor | None = None):
    """Shorthand for printing a fully-colored string."""
    print(colorize(content, fg_color, bg_color))

def readable(rgb: RGB | RGBColor) -> RGBColor:
    """
    Adjust RGB values to be readable in the terminal. \n
    Higher values increase faster to preserve saturation.
    """
    rgb = rgb.value if isinstance(rgb, RGB) else rgb
    while sum(map(lambda x: x**2, rgb)) <= 50000:
        delta = tuple(255-x for x in rgb)
        converted_delta = map(lambda x: x * 0.01 * ((10**6) / ((x - 100)**2)) / 100, delta)
        intermediate = list(zip(rgb, converted_delta))
        rgb = RGBColor(*map(lambda pair: int(sum(pair)), intermediate))
    return rgb

def colorize_type(value: None | bool | list | tuple | set | dict | int | float, *,
                  invert: bool = False, scale: tuple[int, int] | None = None) -> str:
    """Convert a value to a type-dependent colored string representation."""
    match value:
        case None:
            return "None"
        case bool():
            return colorize(value, RGB.GREEN) if invert ^ value else colorize(value, RGB.RED)
        case list() | tuple() | set() | dict():
            items, original_type = [], type(value)
            (key_color, value_color), delimiter = {
                list: ((RGB.ORANGE, None), ('[', ']')),
                tuple: ((RGB.YELLOW, None), ('(', ')')),
                set: ((RGB.PINK, None), ('{', '}')),
                dict: ((RGB.ORANGE, SGR.BLUE), ('{', '}'))
                }[original_type]
            if isinstance(value, dict):
                value = list(value.items())
            for item in value:
                new_key, new_value = item if isinstance(item, tuple) else (item, None)
                new_key = (colorize(f"'{new_key}'", key_color)
                           if isinstance(new_key, str) else colorize(new_key, key_color))
                if new_value:
                    new_value = (colorize(f"'{new_value}'", value_color)
                                 if isinstance(new_value, str)
                                 else colorize(new_value, value_color))
                items.append(f'{new_key}{f": {new_value}" if new_value else ""}')
            return f"{delimiter[0]}{', '.join(items)}{delimiter[1]}"
        case int() | float():
            if scale is None:
                raise ValueError("Cannot colorize number without range")
            if not (isinstance(scale, tuple) and len(scale) == 2):
                raise ValueError("Range must be tuple of size 2 (min, max) [inclusive]")
            if value not in range(scale[0], scale[1]+1):
                return colorize(value, RGB.LIGHT_GRAY)
            percent = int((value-scale[0]) / (scale[1]-scale[0]) * 100)
            rgb_diff = tuple(x-y for x, y in zip(MAX_COLOR, MIN_COLOR))
            final_color = tuple(x+int(y*(percent/100)) for x, y in zip(MIN_COLOR, rgb_diff))
            return colorize(value, RGBColor(*final_color))
    raise TypeError(f"Colorization of type {type(value).__name__} not supported")
