import copy
import json
import os
import random
import signal
import sys
import time
from enum import Enum
from os.path import exists
from typing import Any, NotRequired, TypedDict

import ahk
import cv2
import keyboard
import numpy as np
import pyautogui

# TODO: refactor this atrocity
from helper import (
    PlaythroughResult,
    ValidatedPlaythroughs,
    category_pages,
    filter_all_available_playthroughs,
    find_map_for_px_pos,
    gamemodes,
    get_all_available_playthroughs,
    get_highest_value_playthrough,
    get_ingame_ocr_segments,
    get_monkey_knowledge_enabled,
    image_areas,
    is_btd6_window,
    is_sandbox_unlocked,
    keybinds,
    maps,
    maps_by_category,
    playthroughs_to_list,
    set_medal_unlocked,
    set_monkey_knowledge_enabled,
    sort_playthroughs_by_monkey_money_gain,
    sort_playthroughs_by_xp_gain,
    towers,
    update_playthrough_validation_status,
    update_stats_file,
    upgrade_requires_confirmation,
)

# TODO circular imports!
from instructions_file_manager import parse_btd6_instruction_file_name, parse_btd6_instructions_file
from ocr import custom_ocr
from step_types import Step
from utils.image import cut_image, find_image_in_image
from utils.utils import create_resolution_string, custom_print, load_json_file, save_json_file, scale_string_coordinate_pairs, send_key, tuple_to_str

# if gamemodes is None:
# sys.exit('gamemodes is None! did you run setup.py?')

small_action_delay = 0.05
action_delay = 0.2
menu_change_delay = 1


def get_resolution_dependent_data(monitor_resolution=pyautogui.size()) -> dict[str, Any] | None:
    """
    Loads and returns image data and metadata required for screen and game state recognition,
    based on the provided monitor resolution.
    This function attempts to load required and optional images from a directory corresponding
    to the given resolution. It organizes images into categories for comparison and location
    tasks, and determines which game modes are supported based on the presence of required images.

    Returns:
        dict[str, Any] | None: A dictionary containing:
            - 'comparisonImages': dict of categorized comparison images loaded as numpy arrays.
            - 'locateImages': dict of images for locating UI elements, loaded as numpy arrays.
            - 'supportedModes': dict mapping supported mode names to True.
            - 'resolution': The monitor resolution used.
        Returns None if required images or directories are missing.
    """
    ComparisonImage = TypedDict('ComparisonImage', {'category': str, 'name': str, 'for': NotRequired[list[str]]})
    LocateImage = TypedDict('LocateImage', {'name': str, 'for': NotRequired[list[str]]})

    # the next two variables define a similar structure to the 3 after; just to reduce duplication
    required_image_classification_groups = {
        'screens': ['startmenu', 'map_selection', 'difficulty_selection', 'gamemode_selection', 'hero_selection', 'ingame', 'ingame_paused', 'victory_summary', 'victory', 'defeat', 'overwrite_save', 'levelup', 'apopalypse_hint', 'round_100_insta'],
        'game_state': ['game_paused', 'game_playing_slow', 'game_playing_fast'],
    }
    required_comparison_images: list[ComparisonImage] = [{'category': category, 'name': name} for category, names in required_image_classification_groups.items() for name in names]
    optional_comparison_images: list[ComparisonImage] = [{'category': 'screens', 'name': 'collection_claim_chest', 'for': [Mode.CHASE_REWARDS.name]}]

    required_locate_images: list[LocateImage] = [{'name': 'remove_obstacle_confirm_button'}, {'name': 'button_home'}]
    optional_locate_images: list[LocateImage] = [{'name': 'unknown_insta', 'for': [Mode.CHASE_REWARDS.name]}, {'name': 'unknown_insta_mask', 'for': [Mode.CHASE_REWARDS.name]}]

    images_dir = f'images/{create_resolution_string(monitor_resolution)}/'

    comparison_images: dict[str, dict[str, np.ndarray]] = {}
    locate_images: dict[str, np.ndarray | dict[str, np.ndarray | None]] = {}

    if not exists(images_dir):
        return None

    supported_modes = dict.fromkeys([e.name for e in Mode], True)

    def load_images_or_fail(image_meta_list: list[ComparisonImage] | list[LocateImage], target_dict: dict) -> bool:
        for image_info in image_meta_list:
            filename = f'{image_info["name"]}.png'
            full_path = images_dir + filename
            if not exists(full_path):
                # remove modes that are unsupported due to missing images
                if supported_modes is not None and 'for' in image_info:
                    for mode in image_info['for']:
                        supported_modes.pop(mode, None)
                else:
                    print(f'{filename} missing!')
                    return False
            else:
                if 'category' in image_info:
                    target_dict.setdefault(image_info['category'], {})[image_info['name']] = cv2.imread(full_path)
                else:
                    target_dict[image_info['name']] = cv2.imread(full_path)
        return True

    if not load_images_or_fail(required_comparison_images, comparison_images):
        return None

    if not load_images_or_fail(required_locate_images, locate_images):
        return None

    load_images_or_fail(optional_comparison_images, comparison_images)
    load_images_or_fail(optional_locate_images, locate_images)

    dir_path = images_dir + 'collection_events'
    if exists(dir_path):
        locate_images['collection'] = {f.replace('.png', ''): cv2.imread(f'{dir_path}/{f}') for f in os.listdir(dir_path) if f.endswith('.png')}

    return {'comparisonImages': comparison_images, 'locateImages': locate_images, 'supportedModes': supported_modes, 'resolution': monitor_resolution}


class State(Enum):
    UNDEFINED = 0
    IDLE = 1
    INGAME = 2
    GOTO_HOME = 3
    GOTO_INGAME = 4
    SELECT_HERO = 5
    FIND_HARDEST_INCREASED_REWARDS_MAP = 6
    MANAGE_OBJECTIVES = 7
    EXIT = 8


class Screen(Enum):
    UNKNOWN = 0
    STARTMENU = 1
    MAP_SELECTION = 3
    DIFFICULTY_SELECTION = 4
    GAMEMODE_SELECTION = 5
    HERO_SELECTION = 6
    INGAME = 7
    INGAME_PAUSED = 8
    VICTORY_SUMMARY = 9
    VICTORY = 10
    DEFEAT = 11
    OVERWRITE_SAVE = 12
    LEVELUP = 13
    APOPALYPSE_HINT = 14
    ROUND_100_INSTA = 15
    COLLECTION_CLAIM_CHEST = 16
    BTD6_UNFOCUSED = 17


class Mode(Enum):
    ERROR = 0
    SINGLE_MAP = 1
    RANDOM_MAP = 2
    CHASE_REWARDS = 3
    DO_ACHIEVEMENTS = 4
    MISSING_MAPS = 5
    XP_FARMING = 6
    MM_FARMING = 7
    MISSING_STATS = 8
    VALIDATE_PLAYTHROUGHS = 9
    VALIDATE_COSTS = 10


def get_gamemode_position(gamemode: str) -> tuple[int, int]:
    """
    Returns the (x, y) screen coordinates for a given gamemode button.

    If the specified gamemode's "position" is a reference to another gamemode (i.e., a string),
    the function follows the reference chain until it finds the actual coordinates tuple.
    """
    positions = image_areas['click']['gamemode_positions']
    while isinstance(positions[gamemode], str):
        gamemode = positions[gamemode]
    return positions[gamemode]


def get_next_non_sell_action(steps: list[Step]) -> Step:
    for step in steps:
        if step['action'] != 'sell' and step['action'] != 'await_round':
            return step
    return {'action': 'nop', 'cost': 0}


def get_next_costing_action(steps: list[Step]) -> Step:
    for step in steps:
        if step.get('cost', 0) > 0:
            return step
    return {'action': 'nop', 'cost': 0}


def sum_adjacent_sells(steps: list[Step]) -> int:
    gain = 0
    for step in steps:
        if step['action'] != 'sell':
            return gain
        gain += -step.get('cost', 0)
    return gain


exit_after_game = False


def set_exit_after_game():
    global exit_after_game
    active_window = ahk.get_active_window()
    if not active_window or not is_btd6_window(active_window.title):
        return
    custom_print('script will stop after finishing the current game!')
    exit_after_game = True


def on_signal_interrupt(signum, frame):
    custom_print('received SIGINT! exiting!')
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, on_signal_interrupt)

    rd_data = get_resolution_dependent_data()
    if not rd_data:
        print('unsupported resolution! reference images missing!')
        return

    comparison_images = rd_data['comparisonImages']
    locate_images = rd_data['locateImages']
    supported_modes = rd_data['supportedModes']
    resolution = rd_data['resolution']

    all_available_playthroughs = get_all_available_playthroughs(['own_playthroughs'], consider_user_config=True)
    all_available_playthroughs_list = playthroughs_to_list(all_available_playthroughs)

    mode = Mode.ERROR
    log_stats = True
    is_continue = False
    repeat_objectives = False
    do_all_steps_before_start = False
    list_available_playthroughs = False
    handle_playthrough_validation = ValidatedPlaythroughs.EXCLUDE_NON_VALIDATED
    uses_all_available_playthroughs_list = False

    collection_event = None
    value_unit = ''

    original_objectives = []
    objectives = []

    category_restriction = None
    gamemode_restriction = None

    argv = np.array(sys.argv)

    parsed_arguments = []

    # Additional flags:
    # -ns: disable stats logging
    if len(np.where(argv == '-ns')[0]):
        custom_print('stats logging disabled!')
        parsed_arguments.append('-ns')
        log_stats = False
    else:
        custom_print('stats logging enabled!')
    # -r: after finishing all objectives the program restarts with the first objective
    if len(np.where(argv == '-r')[0]):
        custom_print('repeating objective indefinitely! cancel with ctrl + c!')
        parsed_arguments.append('-r')
        repeat_objectives = True

    # -mk: after finishing all objectives the program restarts with the first objective
    if len(np.where(argv == '-mk')[0]):
        custom_print('including playthroughs with monkey knowledge enabled and adjusting prices according to userconfig.json!')
        parsed_arguments.append('-mk')
        set_monkey_knowledge_enabled(True)
    # -nomk: after finishing all objectives the program restarts with the first objective
    elif len(np.where(argv == '-nomk')[0]):
        custom_print('ignoring playthroughs with monkey knowledge enabled!')
        parsed_arguments.append('-nomk')
        set_monkey_knowledge_enabled(False)
    else:
        custom_print('"-mk" (for monkey knowledge enabled) or "-nomk" (for monkey knowledge disabled) must be specified! exiting!')
        return

    # -l: list all available playthroughs(only works with specific modes)
    if len(np.where(argv == '-l')[0]):
        parsed_arguments.append('-l')
        list_available_playthroughs = True

    # -nv: include non validated playthroughs. ignored when mode = validate
    if len(np.where(argv == '-nv')[0]):
        parsed_arguments.append('-nv')
        handle_playthrough_validation = ValidatedPlaythroughs.INCLUDE_ALL

    i_arg = 1
    if len(argv) <= i_arg:
        custom_print('arguments missing! Usage: py replay.py <mode> <mode arguments...> <flags>')
        return
    # py replay.py file <filename> [continue <(int start)|-> [until (int end)]]
    # replays the specified file
    # if continue is specified it is assumed you are already in game. the script starts with instruction start(0 for first instruction)
    #   if the value for continue equals "-" all instructions are executed before the game is started
    # if until is specified the script only executes instructions until instruction end(start=0, end=1 -> only first instruction is executed)
    # the continue option is mainly for creating/debugging playthroughs
    # -r for indefinite playing only works if continue is not set
    elif argv[i_arg] == 'file':
        # run single map, next argument should be the filename
        i_additional_start = i_arg + 2
        i_additional = i_additional_start
        if len(argv) <= i_arg + 1:
            custom_print('requested running a playthrough but no playthrough provided! exiting!')
            return

        parsed_arguments.append(argv[i_arg + 1])
        instruction_offset = -1
        instruction_last = -1
        gamemode = None

        if len(argv) > i_additional and argv[i_additional] in gamemodes:
            gamemode = argv[i_additional]
            parsed_arguments.append(argv[i_additional])
            i_additional += 1

        if len(argv) > i_additional + 1 and argv[i_additional] == 'continue':
            parsed_arguments.append(argv[i_additional])

            is_continue = True

            if str(argv[i_additional + 1]) == '-':
                instruction_offset = 0
                do_all_steps_before_start = True
            elif str(argv[i_additional + 1]).isdigit():
                instruction_offset = int(argv[i_additional + 1])
            else:
                custom_print('continue of playthrough requested but no instruction offset provided!')
                return
            custom_print('stats logging disabled!')
            log_stats = False
            parsed_arguments.append(argv[i_additional + 1])
            i_additional += 2

            if len(argv) >= i_additional + 1 and argv[i_additional] == 'until':
                if str(argv[i_additional + 1]).isdigit():
                    instruction_last = int(argv[i_additional + 1])
                else:
                    custom_print('cutting of instructions for playthrough requested but no index provided!')
                    return
                parsed_arguments.append(argv[i_additional])
                parsed_arguments.append(argv[i_additional + 1])
                i_additional += 2
        if not parse_btd6_instruction_file_name(argv[i_arg + 1]):
            custom_print('"' + str(argv[i_arg + 1]) + '" can\'t be recognized as a playthrough filename! exiting!')
            return
        elif str(argv[i_arg + 1]).count('/') or str(argv[i_arg + 1]).count('\\') and exists(argv[i_arg + 1]):
            filename = argv[i_arg + 1]
        elif exists('own_playthroughs/' + argv[i_arg + 1]):
            filename = 'own_playthroughs/' + argv[i_arg + 1]
        elif exists('playthroughs/' + argv[i_arg + 1]):
            filename = 'playthroughs/' + argv[i_arg + 1]
        elif exists('unvalidated_playthroughs/' + argv[i_arg + 1]):
            filename = 'unvalidated_playthroughs/' + argv[i_arg + 1]
        else:
            custom_print('requested playthrough ' + str(argv[i_arg + 1]) + ' not found! exiting!')
            return
        map_config = parse_btd6_instructions_file(filename, gamemode=gamemode)

        mode = Mode.SINGLE_MAP
        if instruction_offset == -1:
            original_objectives.append({'type': State.GOTO_HOME})
            if 'hero' in map_config:
                original_objectives.append({'type': State.SELECT_HERO, 'mapConfig': map_config})
                original_objectives.append({'type': State.GOTO_HOME})
            original_objectives.append({'type': State.GOTO_INGAME, 'mapConfig': map_config})
        else:
            if instruction_offset >= len(map_config['steps']) or (instruction_last != -1 and instruction_offset >= instruction_last):
                custom_print('instruction offset > last instruction (' + (str(instruction_last) if instruction_last != -1 else str(len(map_config['steps']))) + ')')
                return

            if instruction_last != -1:
                map_config['steps'] = map_config['steps'][(instruction_offset + map_config['extrainstructions']) : instruction_last]
            else:
                map_config['steps'] = map_config['steps'][(instruction_offset + map_config['extrainstructions']) :]
            custom_print('continuing playthrough. first instruction:')
            custom_print(map_config['steps'][0])
        original_objectives.append({'type': State.INGAME, 'mapConfig': map_config})
        original_objectives.append({'type': State.MANAGE_OBJECTIVES})
    # py replay.py random [category] [gamemode]
    # plays a random game from all available playthroughs (which fulfill the category and gamemode requirement if specified)
    elif argv[i_arg] == 'random':
        i_additional = i_arg + 1
        if len(argv) > i_additional and argv[i_additional] in maps_by_category:
            category_restriction = argv[i_additional]
            parsed_arguments.append(argv[i_additional])
            i_additional += 1

        if len(argv) > i_additional and argv[i_additional] in gamemodes:
            gamemode_restriction = argv[i_additional]
            parsed_arguments.append(argv[i_additional])
            i_additional += 1

        custom_print('Mode: playing random games' + (f' on {gamemode_restriction}' if gamemode_restriction else '') + (f' in {category_restriction} category' if category_restriction else '') + '!')

        all_available_playthroughs = filter_all_available_playthroughs(all_available_playthroughs, get_monkey_knowledge_enabled(), handle_playthrough_validation, category_restriction, gamemode_restriction)
        all_available_playthroughs_list = playthroughs_to_list(all_available_playthroughs)

        original_objectives.append({'type': State.MANAGE_OBJECTIVES})
        mode = Mode.RANDOM_MAP
        uses_all_available_playthroughs_list = True
    # py replay.py chase <event> [category] [gamemode]
    # chases increased rewards for the specified event
    # if category is not provided it finds the map with increased rewards in expert category and plays the most valuable available playthrough and downgrades category if no playthrough is available
    # use -r to farm indefinitely
    elif argv[i_arg] == 'chase':
        if len(argv) <= i_arg + 1 or argv[i_arg + 1] not in locate_images['collection']:
            custom_print('requested chasing event rewards but no event specified or unknown event! exiting!')
            return

        collection_event = argv[i_arg + 1]
        parsed_arguments.append(argv[i_arg + 1])

        i_additional = i_arg + 2
        if len(argv) > i_additional and argv[i_additional] in maps_by_category:
            category_restriction = argv[i_additional]
            parsed_arguments.append(argv[i_additional])
            i_additional += 1

        if len(argv) > i_additional and argv[i_additional] in gamemodes:
            gamemode_restriction = argv[i_additional]
            parsed_arguments.append(argv[i_additional])
            i_additional += 1

        if collection_event == 'golden_bloon':
            all_available_playthroughs = filter_all_available_playthroughs(all_available_playthroughs, get_monkey_knowledge_enabled(), handle_playthrough_validation, category_restriction, gamemode_restriction, required_flags=['gB'])
            custom_print('Mode: playing games with golden bloons using special playthroughs' + (f' on {gamemode_restriction}' if gamemode_restriction else '') + (f' in {category_restriction} category' if category_restriction else '') + '!')
        else:
            all_available_playthroughs = filter_all_available_playthroughs(all_available_playthroughs, get_monkey_knowledge_enabled(), handle_playthrough_validation, category_restriction, gamemode_restriction)
            custom_print(f'Mode: playing games with increased {collection_event} collection event rewards' + (f' on {gamemode_restriction}' if gamemode_restriction else '') + (f' in {category_restriction} category' if category_restriction else '') + '!')
        all_available_playthroughs_list = playthroughs_to_list(all_available_playthroughs)

        original_objectives.append({'type': State.MANAGE_OBJECTIVES})
        mode = Mode.CHASE_REWARDS
        uses_all_available_playthroughs_list = True
    # py replay.py achievements [achievement]
    # plays all achievement related playthroughs
    # if achievement is provided it just plays plays until said achievement is unlocked
    # userconfig.json can be used to specify which achievements have already been unlocked or to document progress(e. g. games won only using primary monkeys)
    # refer to userconfig.example.json for an example
    elif argv[i_arg] == 'achievements':
        pass
    # py replay.py missing [category]
    # plays all playthroughs with missing medals
    # if category is not provided from easiest category to hardest
    # if category is provided in said category
    # requires userconfig.json to specify which medals have already been earned
    # unlocking of maps has do be done manually
    elif argv[i_arg] == 'missing':
        pass
    # py replay.py xp [int n=1]
    # plays one of the n most efficient(in terms of xp/hour) playthroughs
    # with -r: plays indefinitely
    elif argv[i_arg] == 'xp':
        all_available_playthroughs_list = sort_playthroughs_by_xp_gain(all_available_playthroughs_list)

        if len(argv) > i_arg + 1 and argv[i_arg + 1].isdigit():
            all_available_playthroughs_list = all_available_playthroughs_list[: int(argv[i_arg + 1])]
            parsed_arguments.append(argv[i_arg + 1])
        else:
            all_available_playthroughs_list = all_available_playthroughs_list[:1]

        original_objectives.append({'type': State.MANAGE_OBJECTIVES})
        mode = Mode.XP_FARMING
        value_unit = 'XP/h'
        uses_all_available_playthroughs_list = True
    # py replay.py mm [int n=1]
    # plays one of the n most efficient(in terms of mm/hour) playthroughs
    # with -r: plays indefinitely
    elif argv[i_arg] == 'mm' or argv[i_arg] == 'monkey_money':
        all_available_playthroughs_list = sort_playthroughs_by_monkey_money_gain(all_available_playthroughs_list)

        if len(argv) > i_arg + 1 and argv[i_arg + 1].isdigit():
            all_available_playthroughs_list = all_available_playthroughs_list[: int(argv[i_arg + 1])]
            parsed_arguments.append(argv[i_arg + 1])
        else:
            all_available_playthroughs_list = all_available_playthroughs_list[:1]

        original_objectives.append({'type': State.MANAGE_OBJECTIVES})
        mode = Mode.MM_FARMING
        value_unit = 'MM/h'
        uses_all_available_playthroughs_list = True
    # py replay.py validate file <filename>
    # or
    # py replay.py validate all [category]
    elif argv[i_arg] == 'validate':
        if len(argv) <= i_arg + 1:
            custom_print('requested validation but arguments missing!')
            return

        parsed_arguments.append(argv[i_arg + 1])

        if get_monkey_knowledge_enabled():
            custom_print('Mode validate only works with monkey knowledge disabled!')
            return

        if argv[i_arg + 1] == 'file':
            if len(argv) <= i_arg + 2:
                custom_print('no filename provided!')
                return

            if not parse_btd6_instruction_file_name(argv[i_arg + 2]):
                custom_print('"' + str(argv[i_arg + 2]) + '" can\'t be recognized as a playthrough filename! exiting!')
                return
            elif str(argv[i_arg + 1]).count('/') or str(argv[i_arg + 2]).count('\\') and exists(argv[i_arg + 2]):
                filename = argv[i_arg + 1]
            elif exists('own_playthroughs/' + argv[i_arg + 2]):
                filename = 'own_playthroughs/' + argv[i_arg + 2]
            elif exists('playthroughs/' + argv[i_arg + 2]):
                filename = 'playthroughs/' + argv[i_arg + 2]
            elif exists('unvalidated_playthroughs/' + argv[i_arg + 2]):
                filename = 'unvalidated_playthroughs/' + argv[i_arg + 2]
            else:
                custom_print('requested playthrough ' + str(argv[i_arg + 2]) + ' not found! exiting!')
                return

            parsed_arguments.append(argv[i_arg + 2])

            file_config = parse_btd6_instruction_file_name(filename)
            all_available_playthroughs_list = [{'filename': filename, 'fileConfig': file_config, 'gamemode': file_config['gamemode'], 'isOriginalGamemode': True}]
        elif argv[i_arg + 1] == 'all':
            i_additional = i_arg + 2

            if len(argv) > i_additional and argv[i_additional] in maps_by_category:
                category_restriction = argv[i_additional]
                parsed_arguments.append(argv[i_additional])
                i_additional += 1

            custom_print('Mode: validating all playthroughs' + (' in ' + category_restriction + ' category' if category_restriction else '') + '!')

            all_available_playthroughs = filter_all_available_playthroughs(
                all_available_playthroughs,
                True,
                ValidatedPlaythroughs.EXCLUDE_VALIDATED if handle_playthrough_validation == ValidatedPlaythroughs.INCLUDE_ALL else ValidatedPlaythroughs.INCLUDE_ALL,
                category_restriction,
                gamemode_restriction,
                only_original_gamemodes=True,
            )
            all_available_playthroughs_list = playthroughs_to_list(all_available_playthroughs)

        original_objectives.append({'type': State.MANAGE_OBJECTIVES})
        uses_all_available_playthroughs_list = True
        mode = Mode.VALIDATE_PLAYTHROUGHS
    # py replay.py costs [+heroes]
    # determines the base cost and cost of each upgrade for each monkey as well as the base cost for each hero if '+heroes' is specified
    elif argv[i_arg] == 'costs':
        if get_monkey_knowledge_enabled():
            custom_print('Mode validate costs only works with monkey knowledge disabled!')
            return

        include_heroes = False

        if len(argv) >= i_arg + 2 and argv[i_arg + 1] == '+heroes':
            include_heroes = True
            parsed_arguments.append(argv[i_arg + 1])

        custom_print('Mode: validating monkey costs' + (' including heroes' if include_heroes else '') + '!')

        all_test_positions = load_json_file('test_positions.json')

        if create_resolution_string() in all_test_positions:
            test_positions = all_test_positions[create_resolution_string()]
        else:
            test_positions = json.loads(scale_string_coordinate_pairs(json.dumps(all_test_positions['2560x1440']), (2560, 1440), pyautogui.size()))

        selected_map = None
        for map_name in test_positions:
            if is_sandbox_unlocked(map_name, ['medium_sandbox']):
                selected_map = map_name
                break

        if selected_map is None:
            custom_print('This mode requires access to medium sandbox for one of the maps in "test_positions.json"!')
            return

        costs = {'monkeys': {}}

        base_map_config = {
            'category': maps[selected_map]['category'],
            'map': selected_map,
            'page': maps[selected_map]['page'],
            'pos': maps[selected_map]['pos'],
            'difficulty': 'medium',
            'gamemode': 'medium_sandbox',
            'steps': [],
            'extrainstructions': 1,
            'filename': None,
        }

        monkey_steps = []
        monkey_steps.append({'action': 'click', 'pos': image_areas['click']['gamemode_deflation_message_confirmation'], 'cost': 0})
        pos = test_positions[selected_map]
        pos['any'] = pos['land']
        for monkey_type in towers['monkeys']:
            costs['monkeys'][monkey_type] = {'base': 0, 'upgrades': np.zeros((3, 5))}
            for i_path in range(0, 3):
                monkey_steps.append({'action': 'place', 'type': monkey_type, 'name': f'{monkey_type}{i_path}', 'key': keybinds['monkeys'][monkey_type], 'pos': pos[towers['monkeys'][monkey_type]['class']], 'cost': 1, 'extra': {'group': 'monkeys', 'type': monkey_type}})
                for i_upgrade in range(1, 6):
                    monkey_steps.append(
                        {
                            'action': 'upgrade',
                            'name': f'{monkey_type}{i_path}',
                            'key': keybinds['path'][str(i_path)],
                            'pos': pos[towers['monkeys'][monkey_type]['class']],
                            'path': i_path,
                            'cost': 1,
                            'extra': {'group': 'monkeys', 'type': monkey_type, 'upgrade': (i_path, i_upgrade)},
                        },
                    )
                    if upgrade_requires_confirmation({'type': monkey_type, 'upgrades': [(i_upgrade if iTmp == i_path else 0) for iTmp in range(0, 3)]}, i_path):
                        monkey_steps.append({'action': 'click', 'name': f'{monkey_type}{i_path}', 'pos': image_areas['click']['paragon_message_confirmation'], 'cost': 0})
                monkey_steps.append({'action': 'sell', 'name': f'{monkey_type}{i_path}', 'key': keybinds['others']['sell'], 'pos': pos[towers['monkeys'][monkey_type]['class']], 'cost': -1})

        monkey_map_config = copy.deepcopy(base_map_config)
        monkey_map_config['steps'] = monkey_steps

        original_objectives.append({'type': State.GOTO_HOME})
        original_objectives.append({'type': State.GOTO_INGAME, 'mapConfig': monkey_map_config})
        original_objectives.append({'type': State.INGAME, 'mapConfig': monkey_map_config})

        if include_heroes:
            costs['heroes'] = {}

            for hero in towers['heroes']:
                costs['heroes'][hero] = {'base': 0}
                hero_map_config = copy.deepcopy(base_map_config)
                hero_map_config['hero'] = hero
                hero_map_config['steps'] = [
                    {'action': 'click', 'pos': image_areas['click']['gamemode_deflation_message_confirmation'], 'cost': 0},
                    {'action': 'place', 'type': 'hero', 'name': 'hero0', 'key': keybinds['monkeys']['hero'], 'pos': pos[towers['heroes'][hero]['class']], 'cost': 1, 'extra': {'group': 'heroes', 'type': hero}},
                ]
                original_objectives.append({'type': State.GOTO_HOME})
                original_objectives.append({'type': State.SELECT_HERO, 'mapConfig': hero_map_config})
                original_objectives.append({'type': State.GOTO_HOME})
                original_objectives.append({'type': State.GOTO_INGAME, 'mapConfig': hero_map_config})
                original_objectives.append({'type': State.INGAME, 'mapConfig': hero_map_config})

        original_objectives.append({'type': State.MANAGE_OBJECTIVES})
        uses_all_available_playthroughs_list = False
        mode = Mode.VALIDATE_COSTS

    if mode == Mode.ERROR:
        custom_print('invalid arguments! exiting!')
        return

    if mode.name not in supported_modes:
        custom_print('mode not supported due to missing images!')
        return

    parsed_arguments.append(argv[0])
    parsed_arguments.append(argv[1])

    unparsed_arguments = []
    parsed_arguments_tmp = np.array(parsed_arguments)
    for arg in sys.argv:
        if len(np.where(parsed_arguments_tmp == arg)[0]):
            parsed_arguments_tmp = np.delete(parsed_arguments_tmp, np.where(parsed_arguments_tmp == arg)[0])
        else:
            unparsed_arguments.append(arg)

    if len(unparsed_arguments):
        custom_print('unrecognized arguments:')
        custom_print(unparsed_arguments)
        custom_print('exiting!')
        return

    if list_available_playthroughs:
        if uses_all_available_playthroughs_list:
            custom_print(str(len(all_available_playthroughs_list)) + ' playthroughs found:')
            for playthrough in all_available_playthroughs_list:
                custom_print(playthrough['filename'] + ': ' + playthrough['fileConfig']['map'] + ' - ' + playthrough['gamemode'] + (' with ' + str(playthrough['value']) + (' ' + value_unit if len(value_unit) else '') if 'value' in playthrough else ''))
        else:
            custom_print("Mode doesn't qualify for listing all available playthroughs")
        return

    if uses_all_available_playthroughs_list and len(all_available_playthroughs_list) == 0:
        custom_print('no playthroughs matching requirements found!')

    keyboard.add_hotkey('ctrl+space', set_exit_after_game)

    objectives = copy.deepcopy(original_objectives)

    state = objectives[0]['type']
    last_state_transition_successful = True
    objective_failed = False
    map_config = objectives[0].get('mapConfig', None)

    games_played = 0

    last_iteration_balance = -1
    last_iteration_round = -1
    last_iteration_cost = 0
    iteration_balances = []
    this_iteration_action = None
    last_iteration_action = None

    fast = True

    validation_result = None

    playthrough_log = {}

    last_hero_selected = None

    increased_rewards_playthrough = None

    last_playthrough = None
    last_playthrough_stats = {}

    last_screen = Screen.UNKNOWN
    last_state = State.UNDEFINED

    unknown_screen_has_waited = False

    segment_coordinates = None

    while True:
        screenshot = np.array(pyautogui.screenshot())[:, :, ::-1].copy()

        screen = Screen.UNKNOWN
        active_window = ahk.get_active_window()
        if not active_window or not is_btd6_window(active_window.title):
            screen = Screen.BTD6_UNFOCUSED
        else:
            best_match_diff = None
            for screen_cfg in [
                (Screen.STARTMENU, comparison_images['screens']['startmenu'], image_areas['compare']['screens']['startmenu']),
                (Screen.MAP_SELECTION, comparison_images['screens']['map_selection'], image_areas['compare']['screens']['map_selection']),
                (Screen.DIFFICULTY_SELECTION, comparison_images['screens']['difficulty_selection'], image_areas['compare']['screens']['difficulty_selection']),
                (Screen.GAMEMODE_SELECTION, comparison_images['screens']['gamemode_selection'], image_areas['compare']['screens']['gamemode_selection']),
                (Screen.HERO_SELECTION, comparison_images['screens']['hero_selection'], image_areas['compare']['screens']['hero_selection']),
                (Screen.INGAME, comparison_images['screens']['ingame'], image_areas['compare']['screens']['ingame']),
                (Screen.INGAME_PAUSED, comparison_images['screens']['ingame_paused'], image_areas['compare']['screens']['ingame_paused']),
                (Screen.VICTORY_SUMMARY, comparison_images['screens']['victory_summary'], image_areas['compare']['screens']['victory_summary']),
                (Screen.VICTORY, comparison_images['screens']['victory'], image_areas['compare']['screens']['victory']),
                (Screen.DEFEAT, comparison_images['screens']['defeat'], image_areas['compare']['screens']['defeat']),
                (Screen.OVERWRITE_SAVE, comparison_images['screens']['overwrite_save'], image_areas['compare']['screens']['overwrite_save']),
                (Screen.LEVELUP, comparison_images['screens']['levelup'], image_areas['compare']['screens']['levelup']),
                (Screen.APOPALYPSE_HINT, comparison_images['screens']['apopalypse_hint'], image_areas['compare']['screens']['apopalypse_hint']),
                (Screen.ROUND_100_INSTA, comparison_images['screens']['round_100_insta'], image_areas['compare']['screens']['round_100_insta']),
                (Screen.COLLECTION_CLAIM_CHEST, comparison_images['screens']['collection_claim_chest'], image_areas['compare']['screens']['collection_claim_chest']),
            ]:
                diff = cv2.matchTemplate(cut_image(screenshot, screen_cfg[2]), cut_image(screen_cfg[1], screen_cfg[2]), cv2.TM_SQDIFF_NORMED)[0][0]
                if diff < 0.05 and (best_match_diff is None or diff < best_match_diff):
                    best_match_diff = diff
                    screen = screen_cfg[0]

        if screen != last_screen:
            custom_print('screen ' + screen.name + '!')

        if screen == Screen.BTD6_UNFOCUSED:
            pass
        # don't do anything when ctrl is pressed: useful for alt + tab / sending SIGINT(ctrl + c) to the script
        elif keyboard.is_pressed('ctrl'):
            pass
        elif state == State.MANAGE_OBJECTIVES:
            custom_print('entered objective management!')

            if exit_after_game:
                state = State.EXIT
                continue

            if mode == Mode.VALIDATE_PLAYTHROUGHS:
                if validation_result is not None:
                    custom_print('validation result: playthrough ' + last_playthrough['filename'] + ' is ' + ('valid' if validation_result else 'invalid') + '!')
                    update_playthrough_validation_status(last_playthrough['filename'], validation_result)
                if len(all_available_playthroughs_list):
                    playthrough = all_available_playthroughs_list.pop(0)
                    custom_print('validation playthrough chosen: ' + playthrough['fileConfig']['map'] + ' on ' + playthrough['gamemode'] + ' (' + playthrough['filename'] + ')')

                    gamemode = is_sandbox_unlocked(playthrough['fileConfig']['map'])
                    if gamemode:
                        map_config = parse_btd6_instructions_file(playthrough['filename'], gamemode=gamemode)
                        objectives = []
                        objectives.append({'type': State.GOTO_HOME})
                        if 'hero' in map_config and last_hero_selected != map_config['hero']:
                            objectives.append({'type': State.SELECT_HERO, 'mapConfig': map_config})
                            objectives.append({'type': State.GOTO_HOME})
                        objectives.append({'type': State.GOTO_INGAME, 'mapConfig': map_config})
                        objectives.append({'type': State.INGAME, 'mapConfig': map_config})
                        objectives.append({'type': State.MANAGE_OBJECTIVES})

                        validation_result = True
                        last_playthrough = playthrough
                    else:
                        custom_print('missing sandbox access for ' + playthrough['fileConfig']['map'])
                        objectives = []
                        objectives.append({'type': State.MANAGE_OBJECTIVES})
                else:
                    objectives = []
                    objectives.append({'type': State.EXIT})
            elif mode == Mode.VALIDATE_COSTS:
                old_towers = copy.deepcopy(towers)
                changes = 0
                for monkey_type in costs['monkeys']:
                    if costs['monkeys'][monkey_type]['base'] and costs['monkeys'][monkey_type]['base'] != old_towers['monkeys'][monkey_type]['base']:
                        print(f'{monkey_type} base cost: {old_towers["monkeys"][monkey_type]["base"]} -> {int(costs["monkeys"][monkey_type]["base"])}')
                        towers['monkeys'][monkey_type]['base'] = int(costs['monkeys'][monkey_type]['base'])
                        changes += 1
                    for i_path in range(0, 3):
                        for i_upgrade in range(0, 5):
                            if costs['monkeys'][monkey_type]['upgrades'][i_path][i_upgrade] and costs['monkeys'][monkey_type]['upgrades'][i_path][i_upgrade] != old_towers['monkeys'][monkey_type]['upgrades'][i_path][i_upgrade]:
                                print(f'{monkey_type} path {i_path + 1} upgrade {i_upgrade + 1} cost: {old_towers["monkeys"][monkey_type]["upgrades"][i_path][i_upgrade]} -> {int(costs["monkeys"][monkey_type]["upgrades"][i_path][i_upgrade])}')
                                towers['monkeys'][monkey_type]['upgrades'][i_path][i_upgrade] = int(costs['monkeys'][monkey_type]['upgrades'][i_path][i_upgrade])
                                changes += 1
                if 'heroes' in costs:
                    for hero in costs['heroes']:
                        if costs['heroes'][hero]['base'] and costs['heroes'][hero]['base'] != old_towers['heroes'][hero]['base']:
                            print(f'hero {hero} base cost: {old_towers["heroes"][hero]["base"]} -> {int(costs["heroes"][hero]["base"])}')
                            towers['heroes'][hero]['base'] = int(costs['heroes'][hero]['base'])
                            changes += 1

                if changes:
                    print(f'updating "towers.json" with {changes} changes!')

                    save_json_file('towers.json', towers)
                    save_json_file('towers_backup.json', old_towers)
                else:
                    print('no price changes in comparison to "towers.json" detected!')

                return
            elif repeat_objectives or games_played == 0:
                if mode == Mode.SINGLE_MAP:
                    objectives = copy.deepcopy(original_objectives)
                elif mode == Mode.RANDOM_MAP or mode == Mode.XP_FARMING or mode == Mode.MM_FARMING:
                    objectives = []
                    playthrough = random.choice(all_available_playthroughs_list)
                    custom_print('random playthrough chosen: ' + playthrough['fileConfig']['map'] + ' on ' + playthrough['gamemode'] + ' (' + playthrough['filename'] + ')')
                    map_config = parse_btd6_instructions_file(playthrough['filename'], gamemode=playthrough['gamemode'])

                    objectives.append({'type': State.GOTO_HOME})
                    if 'hero' in map_config and last_hero_selected != map_config['hero']:
                        objectives.append({'type': State.SELECT_HERO, 'mapConfig': map_config})
                        objectives.append({'type': State.GOTO_HOME})
                    objectives.append({'type': State.GOTO_INGAME, 'mapConfig': map_config})
                    objectives.append({'type': State.INGAME, 'mapConfig': map_config})
                    objectives.append({'type': State.MANAGE_OBJECTIVES})
                    last_playthrough = playthrough
                elif mode == Mode.CHASE_REWARDS:
                    objectives = []
                    if increased_rewards_playthrough:
                        playthrough = increased_rewards_playthrough
                        custom_print('highest reward playthrough chosen: ' + playthrough['fileConfig']['map'] + ' on ' + playthrough['gamemode'] + ' (' + playthrough['filename'] + ')')
                        map_config = parse_btd6_instructions_file(playthrough['filename'], gamemode=playthrough['gamemode'])

                        objectives.append({'type': State.GOTO_HOME})
                        if 'hero' in map_config and last_hero_selected != map_config['hero']:
                            objectives.append({'type': State.SELECT_HERO, 'mapConfig': map_config})
                            objectives.append({'type': State.GOTO_HOME})
                        objectives.append({'type': State.GOTO_INGAME, 'mapConfig': map_config})
                        objectives.append({'type': State.INGAME, 'mapConfig': map_config})
                        objectives.append({'type': State.MANAGE_OBJECTIVES})
                        increased_rewards_playthrough = None
                        last_playthrough = playthrough
                    else:
                        objectives.append({'type': State.GOTO_HOME})
                        objectives.append({'type': State.FIND_HARDEST_INCREASED_REWARDS_MAP})
                        objectives.append({'type': State.MANAGE_OBJECTIVES})
                else:
                    objectives = copy.deepcopy(original_objectives)
            else:
                objectives = []
                objectives.append({'type': State.EXIT})

            state = objectives[0]['type']
            last_state_transition_successful = True
            objective_failed = False
        elif state == State.UNDEFINED:
            custom_print('entered state management!')
            if exit_after_game:
                state = State.EXIT
            if objective_failed:
                custom_print('objective failed on step ' + objectives[0]['type'].name + '(screen ' + last_screen.name + ')!')
                state = State.MANAGE_OBJECTIVES if repeat_objectives else State.EXIT
            elif not last_state_transition_successful:
                state = objectives[0]['type']
                if 'mapConfig' in objectives[0]:
                    map_config = objectives[0]['mapConfig']
                last_state_transition_successful = True
            elif last_state_transition_successful and len(objectives):
                objectives.pop(0)
                state = objectives[0]['type']
                if 'mapConfig' in objectives[0]:
                    map_config = objectives[0]['mapConfig']
            else:
                state = State.EXIT
        elif state == State.IDLE:
            pass
        elif state == State.EXIT:
            custom_print('goal EXIT! exiting!')
            return
        elif state == State.GOTO_HOME:
            custom_print('current screen: ' + screen.name)
            if screen == Screen.STARTMENU:
                custom_print('goal GOTO_HOME fulfilled!')
                state = State.UNDEFINED
            elif screen == Screen.UNKNOWN:
                if last_screen == Screen.UNKNOWN and unknown_screen_has_waited:
                    unknown_screen_has_waited = False
                    send_key('{Esc}')
                else:
                    unknown_screen_has_waited = True
                    time.sleep(2)
            elif screen == Screen.INGAME:
                send_key('{Esc}')
            elif screen == Screen.INGAME_PAUSED:
                pyautogui.click(image_areas['click']['screen_ingame_paused_button_home'])
            elif screen in [Screen.HERO_SELECTION, Screen.GAMEMODE_SELECTION, Screen.DIFFICULTY_SELECTION, Screen.MAP_SELECTION]:
                send_key('{Esc}')
            elif screen == Screen.DEFEAT:
                result = cv2.matchTemplate(screenshot, locate_images['button_home'], cv2.TM_SQDIFF_NORMED)
                pyautogui.click(cv2.minMaxLoc(result)[2])
            elif screen == Screen.VICTORY_SUMMARY:
                pyautogui.click(image_areas['click']['screen_victory_summary_button_next'])
            elif screen == Screen.VICTORY:
                pyautogui.click(image_areas['click']['screen_victory_button_home'])
            elif screen == Screen.OVERWRITE_SAVE:
                send_key('{Esc}')
            elif screen == Screen.LEVELUP:
                pyautogui.click(100, 100)
                time.sleep(menu_change_delay)
                pyautogui.click(100, 100)
            elif screen == Screen.ROUND_100_INSTA:
                pyautogui.click(100, 100)
                time.sleep(menu_change_delay)
            elif screen == Screen.COLLECTION_CLAIM_CHEST:
                pyautogui.click(image_areas['click']['collection_claim_chest'])
                time.sleep(menu_change_delay * 2)
                while True:
                    new_screenshot = np.array(pyautogui.screenshot())[:, :, ::-1].copy()
                    result = [cv2.minMaxLoc(cv2.matchTemplate(new_screenshot, locate_images['unknown_insta'], cv2.TM_SQDIFF_NORMED, mask=locate_images['unknown_insta_mask']))[i] for i in [0, 2]]
                    if result[0] < 0.01:
                        pyautogui.click(result[1])
                        time.sleep(menu_change_delay)
                        pyautogui.click(result[1])
                        time.sleep(menu_change_delay)
                    else:
                        break
                pyautogui.click(round(resolution[0] / 2), round(resolution[1] / 2))
                time.sleep(menu_change_delay)
                send_key('{Esc}')
            elif screen == Screen.APOPALYPSE_HINT:
                pyautogui.click(image_areas['click']['gamemode_apopalypse_message_confirmation'])
        elif state == State.GOTO_INGAME:
            if map_config is None:
                custom_print('Error: mapConfig is None in GOTO_INGAME state!')
                sys.exit(1)

            if screen == Screen.STARTMENU:
                pyautogui.click(image_areas['click']['screen_startmenu_button_play'])
                time.sleep(menu_change_delay)
                if map_config['category'] == 'beginner':
                    pyautogui.click(image_areas['click']['map_categories']['advanced'])
                    time.sleep(menu_change_delay)
                    pyautogui.click(image_areas['click']['map_categories'][map_config['category']])
                    time.sleep(menu_change_delay)
                else:
                    pyautogui.click(image_areas['click']['map_categories']['beginner'])
                    time.sleep(menu_change_delay)
                    pyautogui.click(image_areas['click']['map_categories'][map_config['category']])
                    time.sleep(menu_change_delay)
                tmp_clicks = map_config['page']
                while tmp_clicks > 0:
                    pyautogui.click(image_areas['click']['map_categories'][map_config['category']])
                    tmp_clicks -= 1
                    time.sleep(menu_change_delay)
                pyautogui.click(image_areas['click']['map_positions'][map_config['pos']])
                time.sleep(menu_change_delay)
                pyautogui.click(image_areas['click']['gamedifficulty_positions'][map_config['difficulty']])
                time.sleep(menu_change_delay)
                pyautogui.click(get_gamemode_position(map_config['gamemode']))
            elif screen == Screen.OVERWRITE_SAVE:
                pyautogui.click(image_areas['click']['screen_overwrite_save_button_ok'])
            elif screen == Screen.APOPALYPSE_HINT:
                pyautogui.click(image_areas['click']['gamemode_apopalypse_message_confirmation'])
            elif screen == Screen.INGAME:
                custom_print('goal GOTO_INGAME fulfilled!')
                custom_print('game: ' + map_config['map'] + ' - ' + map_config['difficulty'])
                segment_coordinates = get_ingame_ocr_segments(map_config)
                iteration_balances = []
                if log_stats:
                    last_playthrough_stats = {'gamemode': map_config['gamemode'], 'time': [], 'result': PlaythroughResult.UNDEFINED}
                    last_playthrough_stats['time'].append(('start', time.time()))
                last_iteration_balance = -1
                last_iteration_cost = 0
                state = State.UNDEFINED
            elif screen == Screen.UNKNOWN:
                pass
            else:
                custom_print('task GOTO_INGAME, but not in startmenu!')
                state = State.GOTO_HOME
                last_state_transition_successful = False
        elif state == State.SELECT_HERO:
            if map_config is None:
                custom_print('Error: mapConfig is None in SELECT_HERO state!')
                sys.exit(1)

            if screen == Screen.STARTMENU:
                pyautogui.click(image_areas['click']['screen_startmenu_button_hero_selection'])
                time.sleep(menu_change_delay)
                pyautogui.click(image_areas['click']['hero_positions'][map_config['hero']])
                time.sleep(menu_change_delay)
                pyautogui.click(image_areas['click']['screen_hero_selection_select_hero'])
                custom_print('goal SELECT_HERO ' + map_config['hero'] + ' fulfilled!')
                last_hero_selected = map_config['hero']
                state = State.UNDEFINED
            elif screen == Screen.UNKNOWN:
                pass
            else:
                custom_print('task SELECT_HERO, but not in startmenu!')
                state = State.GOTO_HOME
                last_state_transition_successful = False
        elif state == State.FIND_HARDEST_INCREASED_REWARDS_MAP:
            if screen == Screen.STARTMENU:
                pyautogui.click(image_areas['click']['screen_startmenu_button_play'])
                time.sleep(menu_change_delay)

                if category_restriction:
                    pyautogui.click(image_areas['click']['map_categories'][('advanced' if category_restriction == 'beginner' else 'beginner')])
                    time.sleep(menu_change_delay)

                    map_name = None
                    for page in range(0, category_pages[category_restriction]):
                        pyautogui.click(image_areas['click']['map_categories'][category_restriction])
                        if collection_event == 'golden_bloon':
                            time.sleep(4)
                        else:
                            time.sleep(menu_change_delay)
                        new_screenshot = np.array(pyautogui.screenshot())[:, :, ::-1].copy()
                        result = find_image_in_image(new_screenshot, locate_images['collection'][collection_event])
                        if result[0] < 0.05:
                            map_name = find_map_for_px_pos(category_restriction, page, result[1])
                            break
                    if not map_name:
                        custom_print('no maps with increased rewards found! exiting!')
                        return
                    custom_print('best map: ' + map_name)
                    increased_rewards_playthrough = get_highest_value_playthrough(all_available_playthroughs, map_name, playthrough_log)
                    if not increased_rewards_playthrough:
                        custom_print('no playthroughs for map found! exiting!')
                        return
                else:
                    for i, category in enumerate(reversed(list(maps_by_category.keys()))):
                        if i == 0:
                            pyautogui.click(image_areas['click']['map_categories'][('advanced' if category == 'beginner' else 'beginner')])
                            time.sleep(menu_change_delay)

                        map_name = None
                        for page in range(0, category_pages[category]):
                            pyautogui.click(image_areas['click']['map_categories'][category])
                            if collection_event == 'golden_bloon':
                                time.sleep(4)
                            else:
                                time.sleep(menu_change_delay)
                            new_screenshot = np.array(pyautogui.screenshot())[:, :, ::-1].copy()
                            result = find_image_in_image(new_screenshot, locate_images['collection'][collection_event])
                            if result[0] < 0.05:
                                map_name = find_map_for_px_pos(category, page, result[1])
                                break
                        if not map_name:
                            custom_print('no maps with increased rewards found! exiting!')
                            return
                        custom_print('best map in ' + category + ': ' + map_name)
                        increased_rewards_playthrough = get_highest_value_playthrough(all_available_playthroughs, map_name, playthrough_log)
                        if increased_rewards_playthrough:
                            break
                        else:
                            custom_print('no playthroughs for map found! searching lower map tiers!')

                    if not increased_rewards_playthrough:
                        custom_print('no available playthrough found! exiting!')
                        return
                state = State.UNDEFINED
            elif screen == Screen.UNKNOWN:
                pass
            else:
                custom_print('task FIND_HARDEST_INCREASED_REWARDS_MAP, but not in startmenu!')
                state = State.GOTO_HOME
                last_state_transition_successful = False
        elif state == State.INGAME:
            if map_config is None:
                custom_print('Error: mapConfig is None in INGAME state!')
                sys.exit(1)

            if screen == Screen.INGAME_PAUSED:
                if last_screen != screen and log_stats:
                    last_playthrough_stats['time'].append(('stop', time.time()))
                time.sleep(2)
                if is_btd6_window(ahk.get_active_window().title):
                    send_key('{Esc}')
            elif screen == Screen.UNKNOWN:
                if last_screen == Screen.UNKNOWN and unknown_screen_has_waited:
                    unknown_screen_has_waited = False
                    send_key('{Esc}')
                else:
                    unknown_screen_has_waited = True
                    time.sleep(2)
            elif screen == Screen.LEVELUP:
                pyautogui.click(100, 100)
                time.sleep(menu_change_delay)
                pyautogui.click(100, 100)
            elif screen == Screen.ROUND_100_INSTA:
                pyautogui.click(100, 100)
                time.sleep(menu_change_delay)
            elif screen == Screen.VICTORY_SUMMARY:
                if log_stats:
                    last_playthrough_stats['time'].append(('stop', time.time()))
                    last_playthrough_stats['result'] = PlaythroughResult.WIN
                    update_stats_file(map_config['filename'], last_playthrough_stats)
                games_played += 1
                if map_config['filename'] not in playthrough_log:
                    playthrough_log[map_config['filename']] = {}
                if map_config['gamemode'] not in playthrough_log[map_config['filename']]:
                    playthrough_log[map_config['filename']][map_config['gamemode']] = {'attempts': 0, 'wins': 0, 'defeats': 0}
                playthrough_log[map_config['filename']][map_config['gamemode']]['attempts'] += 1
                playthrough_log[map_config['filename']][map_config['gamemode']]['wins'] += 1

                if not is_continue:
                    set_medal_unlocked(map_config['map'], map_config['gamemode'])

                state = State.UNDEFINED
            elif screen == Screen.DEFEAT:
                if log_stats:
                    last_playthrough_stats['time'].append(('stop', time.time()))
                    last_playthrough_stats['result'] = PlaythroughResult.DEFEAT
                    update_stats_file(map_config['filename'], last_playthrough_stats)
                objective_failed = True
                games_played += 1
                if map_config['filename'] not in playthrough_log:
                    playthrough_log[map_config['filename']] = {}
                if map_config['gamemode'] not in playthrough_log[map_config['filename']]:
                    playthrough_log[map_config['filename']][map_config['gamemode']] = {'attempts': 0, 'wins': 0, 'defeats': 0}
                playthrough_log[map_config['filename']][map_config['gamemode']]['attempts'] += 1
                playthrough_log[map_config['filename']][map_config['gamemode']]['defeats'] += 1

                state = State.UNDEFINED
            elif screen == Screen.INGAME:
                if last_screen != screen and log_stats:
                    last_playthrough_stats['time'].append(('start', time.time()))

                images = [screenshot[segment_coordinates[segment][1] : segment_coordinates[segment][3], segment_coordinates[segment][0] : segment_coordinates[segment][2]] for segment in segment_coordinates]

                current_values = {}
                this_iteration_cost = 0
                this_iteration_action = None
                skipping_iteration = False

                try:
                    current_values['money'] = int(custom_ocr(images[2]))
                    current_values['round'] = int(custom_ocr(images[3]).split('/')[0])
                except ValueError:
                    current_values['money'] = -1
                    current_values['round'] = -1

                # to prevent random explosion particles that were recognized as digits from messing up the game
                # still possible: if it happens 2 times in a row
                # potential solution: when placing: check if pixel changed colour(or even is of correct colour) - potentially blocked by particles/projectiles
                # when upgrading: check if corresponding box turned green(for left and right menu)
                # remove obstacle: colour change?

                if len(map_config['steps']):
                    if map_config['steps'][0]['action'] == 'sell':
                        custom_print(
                            'detected money: '
                            + str(current_values['money'])
                            + ', required: '
                            + str(get_next_non_sell_action(map_config['steps'])['cost'] - sum_adjacent_sells(map_config['steps']))
                            + ' ('
                            + str(get_next_non_sell_action(map_config['steps'])['cost'])
                            + ' - '
                            + str(sum_adjacent_sells(map_config['steps']))
                            + ')'
                            + '          ',
                            end='',
                            rewrite_line=True,
                        )
                    if map_config['steps'][0]['action'] == 'await_round':
                        custom_print('detected round: ' + str(current_values['round']) + ', awaiting: ' + str(map_config['steps'][0]['round']) + '          ', end='', rewrite_line=True)
                    else:
                        custom_print('detected money: ' + str(current_values['money']) + ', required: ' + str(map_config['steps'][0]['cost']) + '          ', end='', rewrite_line=True)

                if mode == Mode.VALIDATE_PLAYTHROUGHS:
                    if last_iteration_balance != -1 and current_values['money'] != last_iteration_balance - last_iteration_cost:
                        if current_values['money'] == last_iteration_balance:
                            custom_print('action: ' + str(last_iteration_action) + ' failed!')
                            validation_result = False
                            map_config['steps'] = []
                        else:
                            custom_print('pricing error! expected cost: ' + str(last_iteration_cost) + ', detected cost: ' + str(last_iteration_balance - current_values['money']) + '. Is monkey knowledge disabled?')
                elif mode == Mode.VALIDATE_COSTS:
                    if last_iteration_balance != -1 and last_iteration_action:
                        if last_iteration_action['action'] == 'place':
                            costs[last_iteration_action['extra']['group']][last_iteration_action['extra']['type']]['base'] = int(last_iteration_balance - current_values['money'])
                        elif last_iteration_action['action'] == 'upgrade':
                            costs[last_iteration_action['extra']['group']][last_iteration_action['extra']['type']]['upgrades'][last_iteration_action['extra']['upgrade'][0]][last_iteration_action['extra']['upgrade'][1] - 1] = int(last_iteration_balance - current_values['money'])

                if mode == Mode.VALIDATE_PLAYTHROUGHS and len(map_config['steps']) and (map_config['steps'][0]['action'] == 'await_round' or map_config['steps'][0]['action'] == 'speed'):
                    map_config['steps'].pop(0)
                elif current_values['money'] == -1 or current_values['round'] == -1 and len(map_config['steps']) and map_config['steps'][0]['action'] == 'await_round':
                    custom_print('recognition error. money: ' + str(current_values['money']) + ', round: ' + str(current_values['round']))
                elif mode != Mode.VALIDATE_COSTS and last_iteration_balance - last_iteration_cost > current_values['money']:
                    custom_print('potential cash recognition error: ' + str(last_iteration_balance) + ' - ' + str(last_iteration_cost) + ' -> ' + str(current_values['money']))
                    # cv2.imwrite('tmp_images/' + time.strftime("%Y-%m-%d_%H-%M-%S") + '_' + str(lastIterationBalance) + '.png', lastIterationScreenshotAreas[2])
                    # cv2.imwrite('tmp_images/' + time.strftime("%Y-%m-%d_%H-%M-%S") + '_' + str(currentValues['money']) + '.png', images[2])
                    skipping_iteration = True
                elif mode != Mode.VALIDATE_COSTS and (current_values['round'] - last_iteration_round > 1 or last_iteration_round > current_values['round']) and len(map_config['steps']) and map_config['steps'][0]['action'] == 'await_round':
                    custom_print('potential round recognition error: ' + str(last_iteration_round) + ' -> ' + str(current_values['round']))
                    skipping_iteration = True
                elif len(map_config['steps']) and (
                    (map_config['steps'][0]['action'] != 'sell' and map_config['steps'][0]['action'] != 'await_round' and min(current_values['money'], last_iteration_balance - last_iteration_cost) >= map_config['steps'][0]['cost'])
                    or map_config['gamemode'] == 'deflation'
                    or map_config['steps'][0]['action'] == 'await_round'
                    and current_values['round'] >= map_config['steps'][0]['round']
                    or map_config['steps'][0]['action'] == 'await_round'
                    and mode == Mode.VALIDATE_PLAYTHROUGHS
                    or ((map_config['steps'][0]['action'] == 'sell') and min(current_values['money'], last_iteration_balance - last_iteration_cost) + sum_adjacent_sells(map_config['steps']) >= get_next_non_sell_action(map_config['steps'])['cost'])
                ):
                    action = map_config['steps'].pop(0)
                    this_iteration_action = action
                    if action['action'] != 'sell' and action['action'] != 'await_round':
                        this_iteration_cost = action['cost']
                    custom_print('performing action: ' + str(action))
                    if action['action'] == 'place':
                        pyautogui.moveTo(action['pos'])
                        time.sleep(action_delay)
                        send_key(action['key'])
                        time.sleep(action_delay)
                        pyautogui.click()
                    elif action['action'] == 'upgrade' or action['action'] == 'retarget' or action['action'] == 'special':
                        # game hints potentially blocking monkeys
                        pyautogui.click(action['pos'])
                        time.sleep(action_delay)
                        action_tmp = None
                        while action:
                            if 'to' in action:
                                pyautogui.moveTo(action['to'])
                                time.sleep(small_action_delay)
                            if action['action'] == 'click':
                                time.sleep(action_delay)
                                pyautogui.moveTo(action['pos'])
                                pyautogui.click()
                                time.sleep(action_delay)
                            else:
                                send_key(action['key'])
                            if 'to' in action and map_config['monkeys'][action['name']]['type'] == 'mortar':
                                pyautogui.click()
                            time.sleep(small_action_delay)
                            action_tmp = action
                            if len(map_config['steps']) and 'name' in map_config['steps'][0] and map_config['steps'][0]['name'] == action['name'] and (map_config['steps'][0]['action'] == 'retarget' or map_config['steps'][0]['action'] == 'special' or map_config['steps'][0]['action'] == 'click'):
                                action = map_config['steps'].pop(0)
                                custom_print('+' + action['action'])
                            else:
                                action = None
                        action = action_tmp
                        send_key('{Esc}')
                    elif action['action'] == 'sell':
                        pyautogui.moveTo(action['pos'])
                        pyautogui.click()
                        time.sleep(action_delay)
                        send_key(action['key'])
                    elif action['action'] == 'remove':
                        custom_print('removing obstacle at ' + tuple_to_str(action['pos']) + ' for ' + str(action['cost']))
                        pyautogui.moveTo(action['pos'])
                        pyautogui.click()
                        time.sleep(menu_change_delay)
                        result = cv2.matchTemplate(np.array(pyautogui.screenshot())[:, :, ::-1].copy(), locate_images['remove_obstacle_confirm_button'], cv2.TM_SQDIFF_NORMED)
                        pyautogui.click(cv2.minMaxLoc(result)[2])
                    elif action['action'] == 'click':
                        pyautogui.moveTo(action['pos'])
                        pyautogui.click()
                    elif action['action'] == 'press':
                        send_key(action['key'])
                    elif action['action'] == 'speed':
                        if action['speed'] == 'fast':
                            fast = True
                        elif action['speed'] == 'slow':
                            fast = False

                elif mode in [Mode.VALIDATE_PLAYTHROUGHS, Mode.VALIDATE_COSTS] and len(map_config['steps']) == 0 and last_iteration_cost == 0:
                    state = State.UNDEFINED

                if (not do_all_steps_before_start and map_config['gamemode'] != 'deflation' and not skipping_iteration and get_next_costing_action(map_config['steps'])['cost'] > min(current_values['money'], last_iteration_balance - last_iteration_cost)) or len(map_config['steps']) == 0:
                    best_match_diff = None
                    game_state = None
                    for screen_cfg in [
                        ('game_playing_fast', comparison_images['game_state']['game_playing_fast'], image_areas['compare']['game_state']),
                        ('game_playing_slow', comparison_images['game_state']['game_playing_slow'], image_areas['compare']['game_state']),
                        ('game_paused', comparison_images['game_state']['game_paused'], image_areas['compare']['game_state']),
                    ]:
                        diff = cv2.matchTemplate(cut_image(screenshot, screen_cfg[2]), cut_image(screen_cfg[1], screen_cfg[2]), cv2.TM_SQDIFF_NORMED)[0][0]
                        if best_match_diff is None or diff < best_match_diff:
                            best_match_diff = diff
                            game_state = screen_cfg[0]

                    if game_state == 'game_playing_fast' and not fast or game_state == 'game_playing_slow' and fast or game_state == 'game_paused':
                        send_key(keybinds['others']['play'])

                last_iteration_balance = current_values['money']
                last_iteration_cost = this_iteration_cost
                last_iteration_action = this_iteration_action

                last_iteration_round = current_values['round']

                iteration_balances.append((current_values['money'], this_iteration_cost))
            else:
                custom_print('task INGAME, but not in related screen!')
                state = State.GOTO_HOME
                last_state_transition_successful = False
        else:
            state = State.UNDEFINED
            last_state_transition_successful = False

        if state != last_state:
            custom_print('new state ' + state.name + '!')

        last_screen = screen
        last_state = state

        time.sleep(action_delay if state == State.INGAME else menu_change_delay)


if __name__ == '__main__':
    main()
