import json
import re
import time
from os.path import exists

import ahk
import pyautogui


def tuple_to_str(tup: tuple) -> str:
    return '(' + ', '.join(map(str, tup)) + ')'


def create_resolution_string(resolution=pyautogui.size()) -> str:
    return f'{resolution[0]}x{resolution[1]}'


def send_key(key: str | int):
    ahk_key = f'{{sc{hex(key).replace("0x", "")}}}' if isinstance(key, int) else key

    ahk.send(ahk_key, key_delay=15, key_press_duration=30, send_mode='Event')


def scale_string_coordinate_pairs(raw_str: str, native_resolution: tuple[int, int], resolution: tuple[int, int]) -> str:
    """
    Scales all coordinate pairs (formatted as "x, y") in a string from the native to the target resolution.

    Args:
        raw_str (str): The input string containing coordinate pairs.
        native_resolution (tuple[int, int]): The original resolution of the coordinates.
        resolution (tuple[int, int]): The target resolution to scale to.
    """

    def scale(val: int, native: int, target: int) -> int:
        return round(val * target / native)

    def scale_match(match: re.Match) -> str:
        x_scaled = scale(int(match.group('x')), native_resolution[0], resolution[0])
        y_scaled = scale(int(match.group('y')), native_resolution[1], resolution[1])

        return f'{x_scaled}, {y_scaled}'

    return re.sub(r'(?P<x>\d+), (?P<y>\d+)', scale_match, raw_str)


_last_line_rewrite = False


# TODO: I think this functionality is not working as expected
# also only used thrice in the whole codebase - maybe remove?
def custom_print(text, end='\n', rewrite_line=False):
    """
    Prints text to the console with a timestamp, optionally rewriting the current line.

    Args:
        text (str): The text to print.
        end (str, optional): The string appended after the last value, default is a newline.
        rewriteLine (bool, optional): If True, rewrites the current line instead of printing a new one.

    Notes:
        - Uses a global variable 'lastLineRewrite' to track if the last print was a line rewrite.
        - Prepends the current date and time in the format '[YYYY-MM-DD HH:MM:SS]' to the output.
    """
    global _last_line_rewrite
    if _last_line_rewrite and not rewrite_line:
        print()

    print(
        ('\r' if rewrite_line else '') + time.strftime('[%Y-%m-%d %H:%M:%S] ') + str(text),
        end=end,
    )

    _last_line_rewrite = rewrite_line


def load_json_file(file_path: str, check_exists: bool = True, default: dict = {}) -> dict:
    """
    Loads a JSON file from the specified file path.
    Args:
        file_path (str): The path to the JSON file to load.
        check_exists (bool, optional): If True, checks if the file exists before attempting to load. Defaults to True.
        default (dict, optional): The default dictionary to return if the file does not exist and check_exists is True. Defaults to None.
    Returns:
        dict: The contents of the JSON file as a dictionary, or the default value (or empty dict) if the file does not exist.
    """
    if check_exists and not exists(file_path):
        return default

    with open(file_path, 'r') as file:
        return json.load(file)


def save_json_file(file_path: str, data: dict):
    """
    Saves a dictionary to a JSON file at the specified file path.
    Args:
        file_path (str): The path to the JSON file to save.
        data (dict): The dictionary to save to the JSON file.
    """
    with open(file_path, 'w') as file:
        json.dump(data, file, indent=4)
