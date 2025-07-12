import argparse
import logging
import math
import signal
import sys
import time
from dataclasses import dataclass
from enum import Enum
from os.path import exists
from typing import Any, Callable, NotRequired, TypedDict, Union

import ahk
import keyboard
import pyautogui
from pyautogui import Point

from consts import MONKEYS, PATHS

# TODO: refactor this atrocity
from helper import (
    gamemodes,
    is_btd6_window,
    keybinds,
    maps,
    towers,
)
from instructions_file_manager import get_btd6_instructions_file_name_by_config, parse_btd6_instructions_file, write_btd6_instructions_file
from utils.utils import tuple_to_str

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# TODO: investigate and optimize
class MonkeyType(TypedDict):
    name: str
    type: str  # what is the type vs name?
    pos: tuple[int, int]  # TODO: check if we should use Point instead
    upgrades: list[int]
    value: Union[int, float]  # TODO: what is this for?


@dataclass
class RecordingEventData:
    action: str
    type: str | None = None
    path: str | None = None
    round: int | None = None


class Action(Enum):
    PLACE = 'place'
    UPGRADE = 'upgrade'
    SELECT_MONKEY = 'select_monkey'
    REMOVE_OBSTACLE = 'remove_obstacle'
    RETARGET = 'retarget'
    MONKEY_SPECIAL = 'monkey_special'
    SELL = 'sell'
    AWAIT_ROUND = 'await_round'


class KeypressDispatchEvent(TypedDict):
    action: Action
    placement_type: NotRequired[str]
    upgrade_path: NotRequired[str]


@dataclass
class RecordData:
    pass


class BaseRecorder:
    """
    BaseRecorder provides a framework for handling and dispatching playthrough recording events.
    Use the @BaseRecorder.on(action, ...) decorator to register handler methods for specific actions.
    """

    _handlers: dict[str, Callable[..., None]]

    def __init__(self):
        self._handlers = {}

    @classmethod
    def on(cls, action: Action, requires_selected_monkey: bool = False) -> Callable[[Callable[..., None]], Callable[..., None]]:
        """
        A decorator factory that registers a handler function for a given Action.
        Args:
            action (Action): The action to associate with the handler.
            requires_selected_monkey (bool, optional): If True, the handler requires a selected monkey and will receive it as an argument. Defaults to False.
        """

        def decorator(func: Callable[..., None]) -> Callable[..., None]:
            def wrapper(self, pos: Point, event: RecordingEventData) -> None:
                if requires_selected_monkey:
                    monkey = self.selected_monkey
                    if monkey is None:
                        logging.warning('No monkey selected for action: ' + action.value)
                        return
                    return func(self, pos, event, monkey)
                return func(self, pos, event)

            cls._handlers[action.value] = wrapper
            return wrapper

        return decorator


class PlaythroughRecorder(BaseRecorder):
    def __init__(self, config: dict[str, Any]):  # TODO fix type hint
        self.config = config

        self.monkeys_by_type_count = {'hero': 0}
        for monkey_type in keybinds['monkeys']:
            self.monkeys_by_type_count[monkey_type] = 0

        self.placed_monkeys: dict[str, MonkeyType] = config.get('monkeys', {})
        for monkey_name in self.placed_monkeys:
            self.monkeys_by_type_count[self.placed_monkeys[monkey_name]['type']] += 1

        self.file_name = get_btd6_instructions_file_name_by_config(self.config)

        self.steps: list[dict[str, Any]] = []  # appended to config when recording is finished
        self.selected_monkey = None

    def start_recording(self):
        self._create_keyboard_event_bindings()

        def signal_handler(signum, frame):
            self._finish_recording()
            sys.exit(0)

        logging.info(f'Starting recording for {self.config["map"]} {self.config["gamemode"]} with hero {self.config["hero"]}')
        logging.info('Press Ctrl+C to stop recording.')
        signal.signal(signal.SIGINT, signal_handler)

        while True:
            time.sleep(60)

    def _finish_recording(self):
        keyboard.unhook_all()
        logging.info('Stopping recording!')
        logging.info('Writing playthrough instructions to file: ' + self.file_name)

        self.config['steps'] = self.steps
        write_btd6_instructions_file(self.config)

    def _on_keypress(self, e: KeypressDispatchEvent) -> None:
        pos = pyautogui.position()
        # TODO: check if this can be improved:
        event = RecordingEventData(
            action=e['action'].value,
            type=e.get('placement_type'),
            path=e.get('upgrade_path'),
            round=e.get('round'),
        )
        # if not self._pre_checks(pos):  # TODO uncomment after testing
        #     return

        # dispatch the event to the appropriate handler
        handler = type(self)._handlers.get(event.action, self._handle_unknown)
        handler(self, pos, event)

    def _pre_checks(self, pos: Point) -> bool:
        win = ahk.get_active_window()
        if not win or not is_btd6_window(win.title):
            logging.warning('BTD6 not focused')
            return False
        if not pyautogui.onScreen(pos):
            logging.warning(f'{tuple_to_str(pos)} not on screen')
            return False
        return True

    def _record(self, action: str, **kwargs: Any) -> None:
        entry = {'action': action, **kwargs}
        self.steps.append(entry)
        logging.info(self._format_message(action, **kwargs))

    def _format_message(self, action: str, **kwargs: Any) -> str:
        parts = [action] + [f'{k}={v}' for k, v in kwargs.items()]
        return ' '.join(str(p) for p in parts)

    @BaseRecorder.on(Action.SELECT_MONKEY)
    def _handle_select_monkey(self, pos: Point, e: RecordingEventData) -> None:
        monkey = self._get_closest_monkey(pos)['monkey']
        if monkey is None:
            logging.warning('No monkeys placed yet!')
            return
        self.selected_monkey = monkey
        self._record('select_monkey', name=monkey['name'], pos=pos)

    @BaseRecorder.on(Action.REMOVE_OBSTACLE)
    def _handle_remove_obstacle(self, pos: Point, e: RecordingEventData) -> None:
        self._record('remove', pos=pos)

    @BaseRecorder.on(Action.RETARGET)
    def _handle_retarget(self, pos: Point, e: RecordingEventData) -> None:
        if not self.selected_monkey:
            logging.warning('selectedMonkey unassigned!')
            return
        name = self.selected_monkey['name']
        if keyboard.is_pressed('space'):
            self._record('retarget', name=name, to=pos)
        elif self.selected_monkey['type'] == 'mortar':
            logging.warning('mortar can only be retargeted to a position(tab + space)!')
        else:
            self._record('retarget', name=name)

    @BaseRecorder.on(Action.MONKEY_SPECIAL, requires_selected_monkey=True)
    def _handle_special(self, pos: Point, e: RecordingEventData, selected_monkey: dict[str, str]) -> None:
        self._record('special', name=selected_monkey['name'])

    @BaseRecorder.on(Action.SELL, requires_selected_monkey=True)
    def _handle_sell(self, pos: Point, e: RecordingEventData, selected_monkey: dict[str, str]) -> None:
        name = selected_monkey['name']
        self._record('sell', name=name)
        self.placed_monkeys.pop(name, None)
        self.selected_monkey = None

    @BaseRecorder.on(Action.PLACE)
    def _handle_place(self, pos: Point, e: RecordingEventData) -> None:
        placement_type = e.type or ''
        idx = self.monkeys_by_type_count.get(placement_type, 0)
        name = f'{placement_type}{idx}'
        self.monkeys_by_type_count[placement_type] = idx + 1
        self.placed_monkeys[name] = {'name': name, 'type': placement_type, 'pos': pos}
        if placement_type != 'hero':
            self.selected_monkey = self._get_closest_monkey(pos)['monkey']

        self._record('place', type=placement_type, name=name, pos=pos)

    @BaseRecorder.on(Action.UPGRADE, requires_selected_monkey=True)
    def _handle_upgrade(self, pos: Point, e: RecordingEventData, selected_monkey: dict[str, str]) -> None:
        self._record('upgrade', name=selected_monkey['name'], path=e.path)

    @BaseRecorder.on(Action.AWAIT_ROUND)
    def _handle_await_round(self, pos: Point, e: RecordingEventData) -> None:
        try:
            r = int(input('wait for round: '))
            if r > 0 and not any(step['action'] == 'await_round' and step.get('round', 0) >= r for step in self.steps):
                self._record('await_round', round=r)
                return
        except ValueError:
            pass
        logging.warning('invalid round! aborting entry!')

    def _handle_unknown(self, pos: Point, e: RecordingEventData) -> None:
        # TODO: fix - not working / never called for some reason
        logging.warning(f'unknown action: {e.action}')

    def _get_closest_monkey(self, pos: tuple[int, int]) -> dict:
        closest_monkey, closest_dist = None, float('inf')
        dist = None
        for monkey in self.placed_monkeys:
            dist = math.dist(pos, self.placed_monkeys[monkey]['pos'])
            if dist < closest_dist:
                closest_monkey = self.placed_monkeys[monkey]
                closest_dist = dist

        for name, monkey in self.placed_monkeys.items():
            dist = math.dist(pos, monkey['pos'])
            if dist < closest_dist:
                closest_monkey = monkey
                closest_dist = dist

        return {'monkey': closest_monkey}

    def _create_keyboard_event_bindings(self):
        for monkey in MONKEYS:
            keyboard.on_press_key(keybinds['monkeys'][monkey], lambda _, monkey=monkey: self._on_keypress({'action': Action.PLACE, 'placement_type': monkey}))

        for path in [str(path) for path in PATHS]:
            keyboard.on_press_key(keybinds['path'][path], lambda _, path=path: self._on_keypress({'action': Action.UPGRADE, 'upgrade_path': path}))

        recording_events: dict[str, KeypressDispatchEvent] = {
            **{key.value: {'action': key} for key in [Action.SELECT_MONKEY, Action.REMOVE_OBSTACLE, Action.RETARGET, Action.SELL, Action.MONKEY_SPECIAL, Action.AWAIT_ROUND]},
        }

        for event_name, event_cfg in recording_events.items():
            keyboard.on_press_key(keybinds['recording'][event_name], lambda _, cfg=event_cfg: self._on_keypress(cfg))


def parse_and_get_args() -> tuple[bool, bool, dict[str, str]]:
    parser = argparse.ArgumentParser(description='Record a BTD6 playthrough.')
    parser.add_argument('-e', '--extend', action='store_true', help='Extend an existing recording instead of creating a new one')
    parser.add_argument('-o', '--overwrite', action='store_true', help='Force overwrite existing recording file')
    parser.add_argument('--map', choices=maps)
    parser.add_argument('--gamemode', choices=gamemodes)
    parser.add_argument('--hero', choices=towers['heroes'])
    args = parser.parse_args()
    params = {'map': args.map, 'gamemode': args.gamemode, 'hero': args.hero}

    def gather_input(name: str, options: list[str]) -> str:
        while True:
            value = input(f'{name} > ').replace(' ', '_').lower()
            if value in options:
                return value
            print(f'Invalid {name}. Choose from: {", ".join(options)}')

    for name, options in (('map', maps), ('gamemode', gamemodes), ('hero', towers['heroes'])):
        if not params[name]:
            params[name] = gather_input(name, options)

    return args.extend, args.overwrite, params


def main(extend: bool, overwrite: bool, config: dict[str, str]):
    filename = get_btd6_instructions_file_name_by_config(config)

    if extend:
        if not exists(filename):
            logging.error(f'File {filename} does not exist. Cannot extend.')
            return

        existing_config = parse_btd6_instructions_file(filename)
        config['steps'] = existing_config['steps']
        config['monkeys'] = existing_config['monkeys']
    else:
        if exists(filename) and not overwrite:
            logging.error(f'Recording for {config["map"]} {config["gamemode"]} with hero {config["hero"]} already exists as {filename}.')
            logging.error('Use -e to extend the existing file or delete the file to start a new recording.')
            return

    recorder = PlaythroughRecorder(config)
    recorder.start_recording()


if __name__ == '__main__':
    main(*parse_and_get_args())
