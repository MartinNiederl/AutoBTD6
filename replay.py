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
    categoryPages,
    convertPositionsInString,
    custom_print,
    cutImage,
    filterAllAvailablePlaythroughs,
    findImageInImage,
    findMapForPxPos,
    gamemodes,
    getAllAvailablePlaythroughs,
    getAvailableSandbox,
    getHighestValuePlaythrough,
    getIngameOcrSegments,
    getMonkeyKnowledgeStatus,
    getResolutionString,
    imageAreas,
    isBTD6Window,
    keybinds,
    maps,
    maps_by_category,
    parseBTD6InstructionFileName,
    parseBTD6InstructionsFile,
    playthroughs_to_list,
    sendKey,
    setMonkeyKnowledgeStatus,
    sortPlaythroughsByMonkeyMoneyGain,
    sortPlaythroughsByXPGain,
    towers,
    tupleToStr,
    updateMedalStatus,
    updatePlaythroughValidationStatus,
    updateStatsFile,
    upgradeRequiresConfirmation,
)

# if gamemodes is None:
# sys.exit('gamemodes is None! did you run setup.py?')
from ocr import custom_ocr
from step_types import Step

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

    images_dir = f'images/{getResolutionString(monitor_resolution)}/'

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
    positions = imageAreas['click']['gamemode_positions']
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
    activeWindow = ahk.get_active_window()
    if not activeWindow or not isBTD6Window(activeWindow.title):
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

    comparisonImages = rd_data['comparisonImages']
    locateImages = rd_data['locateImages']
    supportedModes = rd_data['supportedModes']
    resolution = rd_data['resolution']

    all_available_playthroughs = getAllAvailablePlaythroughs(['own_playthroughs'], considerUserConfig=True)
    all_available_pPlaythroughs_list = playthroughs_to_list(all_available_playthroughs)

    mode = Mode.ERROR
    logStats = True
    isContinue = False
    repeatObjectives = False
    doAllStepsBeforeStart = False
    listAvailablePlaythroughs = False
    handlePlaythroughValidation = ValidatedPlaythroughs.EXCLUDE_NON_VALIDATED
    usesAllAvailablePlaythroughsList = False

    collectionEvent = None
    valueUnit = ''

    originalObjectives = []
    objectives = []

    categoryRestriction = None
    gamemodeRestriction = None

    argv = np.array(sys.argv)

    parsedArguments = []

    # Additional flags:
    # -ns: disable stats logging
    if len(np.where(argv == '-ns')[0]):
        custom_print('stats logging disabled!')
        parsedArguments.append('-ns')
        logStats = False
    else:
        custom_print('stats logging enabled!')
    # -r: after finishing all objectives the program restarts with the first objective
    if len(np.where(argv == '-r')[0]):
        custom_print('repeating objective indefinitely! cancel with ctrl + c!')
        parsedArguments.append('-r')
        repeatObjectives = True

    # -mk: after finishing all objectives the program restarts with the first objective
    if len(np.where(argv == '-mk')[0]):
        custom_print('including playthroughs with monkey knowledge enabled and adjusting prices according to userconfig.json!')
        parsedArguments.append('-mk')
        setMonkeyKnowledgeStatus(True)
    # -nomk: after finishing all objectives the program restarts with the first objective
    elif len(np.where(argv == '-nomk')[0]):
        custom_print('ignoring playthroughs with monkey knowledge enabled!')
        parsedArguments.append('-nomk')
        setMonkeyKnowledgeStatus(False)
    else:
        custom_print('"-mk" (for monkey knowledge enabled) or "-nomk" (for monkey knowledge disabled) must be specified! exiting!')
        return

    # -l: list all available playthroughs(only works with specific modes)
    if len(np.where(argv == '-l')[0]):
        parsedArguments.append('-l')
        listAvailablePlaythroughs = True

    # -nv: include non validated playthroughs. ignored when mode = validate
    if len(np.where(argv == '-nv')[0]):
        parsedArguments.append('-nv')
        handlePlaythroughValidation = ValidatedPlaythroughs.INCLUDE_ALL

    iArg = 1
    if len(argv) <= iArg:
        custom_print('arguments missing! Usage: py replay.py <mode> <mode arguments...> <flags>')
        return
    # py replay.py file <filename> [continue <(int start)|-> [until (int end)]]
    # replays the specified file
    # if continue is specified it is assumed you are already in game. the script starts with instruction start(0 for first instruction)
    #   if the value for continue equals "-" all instructions are executed before the game is started
    # if until is specified the script only executes instructions until instruction end(start=0, end=1 -> only first instruction is executed)
    # the continue option is mainly for creating/debugging playthroughs
    # -r for indefinite playing only works if continue is not set
    elif argv[iArg] == 'file':
        # run single map, next argument should be the filename
        iAdditionalStart = iArg + 2
        iAdditional = iAdditionalStart
        if len(argv) <= iArg + 1:
            custom_print('requested running a playthrough but no playthrough provided! exiting!')
            return

        parsedArguments.append(argv[iArg + 1])
        instructionOffset = -1
        instructionLast = -1
        gamemode = None

        if len(argv) > iAdditional and argv[iAdditional] in gamemodes:
            gamemode = argv[iAdditional]
            parsedArguments.append(argv[iAdditional])
            iAdditional += 1

        if len(argv) > iAdditional + 1 and argv[iAdditional] == 'continue':
            parsedArguments.append(argv[iAdditional])

            isContinue = True

            if str(argv[iAdditional + 1]) == '-':
                instructionOffset = 0
                doAllStepsBeforeStart = True
            elif str(argv[iAdditional + 1]).isdigit():
                instructionOffset = int(argv[iAdditional + 1])
            else:
                custom_print('continue of playthrough requested but no instruction offset provided!')
                return
            custom_print('stats logging disabled!')
            logStats = False
            parsedArguments.append(argv[iAdditional + 1])
            iAdditional += 2

            if len(argv) >= iAdditional + 1 and argv[iAdditional] == 'until':
                if str(argv[iAdditional + 1]).isdigit():
                    instructionLast = int(argv[iAdditional + 1])
                else:
                    custom_print('cutting of instructions for playthrough requested but no index provided!')
                    return
                parsedArguments.append(argv[iAdditional])
                parsedArguments.append(argv[iAdditional + 1])
                iAdditional += 2
        if not parseBTD6InstructionFileName(argv[iArg + 1]):
            custom_print('"' + str(argv[iArg + 1]) + '" can\'t be recognized as a playthrough filename! exiting!')
            return
        elif str(argv[iArg + 1]).count('/') or str(argv[iArg + 1]).count('\\') and exists(argv[iArg + 1]):
            filename = argv[iArg + 1]
        elif exists('own_playthroughs/' + argv[iArg + 1]):
            filename = 'own_playthroughs/' + argv[iArg + 1]
        elif exists('playthroughs/' + argv[iArg + 1]):
            filename = 'playthroughs/' + argv[iArg + 1]
        elif exists('unvalidated_playthroughs/' + argv[iArg + 1]):
            filename = 'unvalidated_playthroughs/' + argv[iArg + 1]
        else:
            custom_print('requested playthrough ' + str(argv[iArg + 1]) + ' not found! exiting!')
            return
        mapConfig = parseBTD6InstructionsFile(filename, gamemode=gamemode)

        mode = Mode.SINGLE_MAP
        if instructionOffset == -1:
            originalObjectives.append({'type': State.GOTO_HOME})
            if 'hero' in mapConfig:
                originalObjectives.append({'type': State.SELECT_HERO, 'mapConfig': mapConfig})
                originalObjectives.append({'type': State.GOTO_HOME})
            originalObjectives.append({'type': State.GOTO_INGAME, 'mapConfig': mapConfig})
        else:
            if instructionOffset >= len(mapConfig['steps']) or (instructionLast != -1 and instructionOffset >= instructionLast):
                custom_print('instruction offset > last instruction (' + (str(instructionLast) if instructionLast != -1 else str(len(mapConfig['steps']))) + ')')
                return

            if instructionLast != -1:
                mapConfig['steps'] = mapConfig['steps'][(instructionOffset + mapConfig['extrainstructions']) : instructionLast]
            else:
                mapConfig['steps'] = mapConfig['steps'][(instructionOffset + mapConfig['extrainstructions']) :]
            custom_print('continuing playthrough. first instruction:')
            custom_print(mapConfig['steps'][0])
        originalObjectives.append({'type': State.INGAME, 'mapConfig': mapConfig})
        originalObjectives.append({'type': State.MANAGE_OBJECTIVES})
    # py replay.py random [category] [gamemode]
    # plays a random game from all available playthroughs (which fulfill the category and gamemode requirement if specified)
    elif argv[iArg] == 'random':
        iAdditional = iArg + 1
        if len(argv) > iAdditional and argv[iAdditional] in maps_by_category:
            categoryRestriction = argv[iAdditional]
            parsedArguments.append(argv[iAdditional])
            iAdditional += 1

        if len(argv) > iAdditional and argv[iAdditional] in gamemodes:
            gamemodeRestriction = argv[iAdditional]
            parsedArguments.append(argv[iAdditional])
            iAdditional += 1

        custom_print('Mode: playing random games' + (f' on {gamemodeRestriction}' if gamemodeRestriction else '') + (f' in {categoryRestriction} category' if categoryRestriction else '') + '!')

        all_available_playthroughs = filterAllAvailablePlaythroughs(all_available_playthroughs, getMonkeyKnowledgeStatus(), handlePlaythroughValidation, categoryRestriction, gamemodeRestriction)
        all_available_pPlaythroughs_list = playthroughs_to_list(all_available_playthroughs)

        originalObjectives.append({'type': State.MANAGE_OBJECTIVES})
        mode = Mode.RANDOM_MAP
        usesAllAvailablePlaythroughsList = True
    # py replay.py chase <event> [category] [gamemode]
    # chases increased rewards for the specified event
    # if category is not provided it finds the map with increased rewards in expert category and plays the most valuable available playthrough and downgrades category if no playthrough is available
    # use -r to farm indefinitely
    elif argv[iArg] == 'chase':
        if len(argv) <= iArg + 1 or argv[iArg + 1] not in locateImages['collection']:
            custom_print('requested chasing event rewards but no event specified or unknown event! exiting!')
            return

        collectionEvent = argv[iArg + 1]
        parsedArguments.append(argv[iArg + 1])

        iAdditional = iArg + 2
        if len(argv) > iAdditional and argv[iAdditional] in maps_by_category:
            categoryRestriction = argv[iAdditional]
            parsedArguments.append(argv[iAdditional])
            iAdditional += 1

        if len(argv) > iAdditional and argv[iAdditional] in gamemodes:
            gamemodeRestriction = argv[iAdditional]
            parsedArguments.append(argv[iAdditional])
            iAdditional += 1

        if collectionEvent == 'golden_bloon':
            all_available_playthroughs = filterAllAvailablePlaythroughs(all_available_playthroughs, getMonkeyKnowledgeStatus(), handlePlaythroughValidation, categoryRestriction, gamemodeRestriction, requiredFlags=['gB'])
            custom_print('Mode: playing games with golden bloons using special playthroughs' + (f' on {gamemodeRestriction}' if gamemodeRestriction else '') + (f' in {categoryRestriction} category' if categoryRestriction else '') + '!')
        else:
            all_available_playthroughs = filterAllAvailablePlaythroughs(all_available_playthroughs, getMonkeyKnowledgeStatus(), handlePlaythroughValidation, categoryRestriction, gamemodeRestriction)
            custom_print(f'Mode: playing games with increased {collectionEvent} collection event rewards' + (f' on {gamemodeRestriction}' if gamemodeRestriction else '') + (f' in {categoryRestriction} category' if categoryRestriction else '') + '!')
        all_available_pPlaythroughs_list = playthroughs_to_list(all_available_playthroughs)

        originalObjectives.append({'type': State.MANAGE_OBJECTIVES})
        mode = Mode.CHASE_REWARDS
        usesAllAvailablePlaythroughsList = True
    # py replay.py achievements [achievement]
    # plays all achievement related playthroughs
    # if achievement is provided it just plays plays until said achievement is unlocked
    # userconfig.json can be used to specify which achievements have already been unlocked or to document progress(e. g. games won only using primary monkeys)
    # refer to userconfig.example.json for an example
    elif argv[iArg] == 'achievements':
        pass
    # py replay.py missing [category]
    # plays all playthroughs with missing medals
    # if category is not provided from easiest category to hardest
    # if category is provided in said category
    # requires userconfig.json to specify which medals have already been earned
    # unlocking of maps has do be done manually
    elif argv[iArg] == 'missing':
        pass
    # py replay.py xp [int n=1]
    # plays one of the n most efficient(in terms of xp/hour) playthroughs
    # with -r: plays indefinitely
    elif argv[iArg] == 'xp':
        all_available_pPlaythroughs_list = sortPlaythroughsByXPGain(all_available_pPlaythroughs_list)

        if len(argv) > iArg + 1 and argv[iArg + 1].isdigit():
            all_available_pPlaythroughs_list = all_available_pPlaythroughs_list[: int(argv[iArg + 1])]
            parsedArguments.append(argv[iArg + 1])
        else:
            all_available_pPlaythroughs_list = all_available_pPlaythroughs_list[:1]

        originalObjectives.append({'type': State.MANAGE_OBJECTIVES})
        mode = Mode.XP_FARMING
        valueUnit = 'XP/h'
        usesAllAvailablePlaythroughsList = True
    # py replay.py mm [int n=1]
    # plays one of the n most efficient(in terms of mm/hour) playthroughs
    # with -r: plays indefinitely
    elif argv[iArg] == 'mm' or argv[iArg] == 'monkey_money':
        all_available_pPlaythroughs_list = sortPlaythroughsByMonkeyMoneyGain(all_available_pPlaythroughs_list)

        if len(argv) > iArg + 1 and argv[iArg + 1].isdigit():
            all_available_pPlaythroughs_list = all_available_pPlaythroughs_list[: int(argv[iArg + 1])]
            parsedArguments.append(argv[iArg + 1])
        else:
            all_available_pPlaythroughs_list = all_available_pPlaythroughs_list[:1]

        originalObjectives.append({'type': State.MANAGE_OBJECTIVES})
        mode = Mode.MM_FARMING
        valueUnit = 'MM/h'
        usesAllAvailablePlaythroughsList = True
    # py replay.py validate file <filename>
    # or
    # py replay.py validate all [category]
    elif argv[iArg] == 'validate':
        if len(argv) <= iArg + 1:
            custom_print('requested validation but arguments missing!')
            return

        parsedArguments.append(argv[iArg + 1])

        if getMonkeyKnowledgeStatus():
            custom_print('Mode validate only works with monkey knowledge disabled!')
            return

        if argv[iArg + 1] == 'file':
            if len(argv) <= iArg + 2:
                custom_print('no filename provided!')
                return

            if not parseBTD6InstructionFileName(argv[iArg + 2]):
                custom_print('"' + str(argv[iArg + 2]) + '" can\'t be recognized as a playthrough filename! exiting!')
                return
            elif str(argv[iArg + 1]).count('/') or str(argv[iArg + 2]).count('\\') and exists(argv[iArg + 2]):
                filename = argv[iArg + 1]
            elif exists('own_playthroughs/' + argv[iArg + 2]):
                filename = 'own_playthroughs/' + argv[iArg + 2]
            elif exists('playthroughs/' + argv[iArg + 2]):
                filename = 'playthroughs/' + argv[iArg + 2]
            elif exists('unvalidated_playthroughs/' + argv[iArg + 2]):
                filename = 'unvalidated_playthroughs/' + argv[iArg + 2]
            else:
                custom_print('requested playthrough ' + str(argv[iArg + 2]) + ' not found! exiting!')
                return

            parsedArguments.append(argv[iArg + 2])

            fileConfig = parseBTD6InstructionFileName(filename)
            all_available_pPlaythroughs_list = [{'filename': filename, 'fileConfig': fileConfig, 'gamemode': fileConfig['gamemode'], 'isOriginalGamemode': True}]
        elif argv[iArg + 1] == 'all':
            iAdditional = iArg + 2

            if len(argv) > iAdditional and argv[iAdditional] in maps_by_category:
                categoryRestriction = argv[iAdditional]
                parsedArguments.append(argv[iAdditional])
                iAdditional += 1

            custom_print('Mode: validating all playthroughs' + (' in ' + categoryRestriction + ' category' if categoryRestriction else '') + '!')

            all_available_playthroughs = filterAllAvailablePlaythroughs(
                all_available_playthroughs,
                True,
                ValidatedPlaythroughs.EXCLUDE_VALIDATED if handlePlaythroughValidation == ValidatedPlaythroughs.INCLUDE_ALL else ValidatedPlaythroughs.INCLUDE_ALL,
                categoryRestriction,
                gamemodeRestriction,
                onlyOriginalGamemodes=True,
            )
            all_available_pPlaythroughs_list = playthroughs_to_list(all_available_playthroughs)

        originalObjectives.append({'type': State.MANAGE_OBJECTIVES})
        usesAllAvailablePlaythroughsList = True
        mode = Mode.VALIDATE_PLAYTHROUGHS
    # py replay.py costs [+heroes]
    # determines the base cost and cost of each upgrade for each monkey as well as the base cost for each hero if '+heroes' is specified
    elif argv[iArg] == 'costs':
        if getMonkeyKnowledgeStatus():
            custom_print('Mode validate costs only works with monkey knowledge disabled!')
            return

        includeHeroes = False

        if len(argv) >= iArg + 2 and argv[iArg + 1] == '+heroes':
            includeHeroes = True
            parsedArguments.append(argv[iArg + 1])

        custom_print('Mode: validating monkey costs' + (' including heroes' if includeHeroes else '') + '!')

        allTestPositions = json.load(open('test_positions.json'))
        if getResolutionString() in allTestPositions:
            testPositions = allTestPositions[getResolutionString()]
        else:
            testPositions = json.loads(convertPositionsInString(json.dumps(allTestPositions['2560x1440']), (2560, 1440), pyautogui.size()))

        selectedMap = None
        for map_name in testPositions:
            if getAvailableSandbox(map_name, ['medium_sandbox']):
                selectedMap = map_name
                break

        if selectedMap is None:
            custom_print('This mode requires access to medium sandbox for one of the maps in "test_positions.json"!')
            return

        costs = {'monkeys': {}}

        baseMapConfig = {
            'category': maps[selectedMap]['category'],
            'map': selectedMap,
            'page': maps[selectedMap]['page'],
            'pos': maps[selectedMap]['pos'],
            'difficulty': 'medium',
            'gamemode': 'medium_sandbox',
            'steps': [],
            'extrainstructions': 1,
            'filename': None,
        }

        monkeySteps = []
        monkeySteps.append({'action': 'click', 'pos': imageAreas['click']['gamemode_deflation_message_confirmation'], 'cost': 0})
        pos = testPositions[selectedMap]
        pos['any'] = pos['land']
        for monkeyType in towers['monkeys']:
            costs['monkeys'][monkeyType] = {'base': 0, 'upgrades': np.zeros((3, 5))}
            for iPath in range(0, 3):
                monkeySteps.append({'action': 'place', 'type': monkeyType, 'name': f'{monkeyType}{iPath}', 'key': keybinds['monkeys'][monkeyType], 'pos': pos[towers['monkeys'][monkeyType]['class']], 'cost': 1, 'extra': {'group': 'monkeys', 'type': monkeyType}})
                for iUpgrade in range(1, 6):
                    monkeySteps.append(
                        {
                            'action': 'upgrade',
                            'name': f'{monkeyType}{iPath}',
                            'key': keybinds['path'][str(iPath)],
                            'pos': pos[towers['monkeys'][monkeyType]['class']],
                            'path': iPath,
                            'cost': 1,
                            'extra': {'group': 'monkeys', 'type': monkeyType, 'upgrade': (iPath, iUpgrade)},
                        },
                    )
                    if upgradeRequiresConfirmation({'type': monkeyType, 'upgrades': [(iUpgrade if iTmp == iPath else 0) for iTmp in range(0, 3)]}, iPath):
                        monkeySteps.append({'action': 'click', 'name': f'{monkeyType}{iPath}', 'pos': imageAreas['click']['paragon_message_confirmation'], 'cost': 0})
                monkeySteps.append({'action': 'sell', 'name': f'{monkeyType}{iPath}', 'key': keybinds['others']['sell'], 'pos': pos[towers['monkeys'][monkeyType]['class']], 'cost': -1})

        monkeyMapConfig = copy.deepcopy(baseMapConfig)
        monkeyMapConfig['steps'] = monkeySteps

        originalObjectives.append({'type': State.GOTO_HOME})
        originalObjectives.append({'type': State.GOTO_INGAME, 'mapConfig': monkeyMapConfig})
        originalObjectives.append({'type': State.INGAME, 'mapConfig': monkeyMapConfig})

        if includeHeroes:
            costs['heroes'] = {}

            for hero in towers['heroes']:
                costs['heroes'][hero] = {'base': 0}
                heroMapConfig = copy.deepcopy(baseMapConfig)
                heroMapConfig['hero'] = hero
                heroMapConfig['steps'] = [
                    {'action': 'click', 'pos': imageAreas['click']['gamemode_deflation_message_confirmation'], 'cost': 0},
                    {'action': 'place', 'type': 'hero', 'name': 'hero0', 'key': keybinds['monkeys']['hero'], 'pos': pos[towers['heroes'][hero]['class']], 'cost': 1, 'extra': {'group': 'heroes', 'type': hero}},
                ]
                originalObjectives.append({'type': State.GOTO_HOME})
                originalObjectives.append({'type': State.SELECT_HERO, 'mapConfig': heroMapConfig})
                originalObjectives.append({'type': State.GOTO_HOME})
                originalObjectives.append({'type': State.GOTO_INGAME, 'mapConfig': heroMapConfig})
                originalObjectives.append({'type': State.INGAME, 'mapConfig': heroMapConfig})

        originalObjectives.append({'type': State.MANAGE_OBJECTIVES})
        usesAllAvailablePlaythroughsList = False
        mode = Mode.VALIDATE_COSTS

    if mode == Mode.ERROR:
        custom_print('invalid arguments! exiting!')
        return

    if not mode.name in supportedModes:
        custom_print('mode not supported due to missing images!')
        return

    parsedArguments.append(argv[0])
    parsedArguments.append(argv[1])

    unparsedArguments = []
    parsedArgumentsTmp = np.array(parsedArguments)
    for arg in sys.argv:
        if len(np.where(parsedArgumentsTmp == arg)[0]):
            parsedArgumentsTmp = np.delete(parsedArgumentsTmp, np.where(parsedArgumentsTmp == arg)[0])
        else:
            unparsedArguments.append(arg)

    if len(unparsedArguments):
        custom_print('unrecognized arguments:')
        custom_print(unparsedArguments)
        custom_print('exiting!')
        return

    if listAvailablePlaythroughs:
        if usesAllAvailablePlaythroughsList:
            custom_print(str(len(all_available_pPlaythroughs_list)) + ' playthroughs found:')
            for playthrough in all_available_pPlaythroughs_list:
                custom_print(playthrough['filename'] + ': ' + playthrough['fileConfig']['map'] + ' - ' + playthrough['gamemode'] + (' with ' + str(playthrough['value']) + (' ' + valueUnit if len(valueUnit) else '') if 'value' in playthrough else ''))
        else:
            custom_print("Mode doesn't qualify for listing all available playthroughs")
        return

    if usesAllAvailablePlaythroughsList and len(all_available_pPlaythroughs_list) == 0:
        custom_print('no playthroughs matching requirements found!')

    keyboard.add_hotkey('ctrl+space', set_exit_after_game)

    objectives = copy.deepcopy(originalObjectives)

    state = objectives[0]['type']
    lastStateTransitionSuccessful = True
    objectiveFailed = False
    mapConfig = objectives[0]['mapConfig'] if 'mapConfig' in objectives[0] else None

    gamesPlayed = 0

    lastIterationBalance = -1
    lastIterationRound = -1
    lastIterationScreenshotAreas = []
    lastIterationCost = 0
    iterationBalances = []
    thisIterationAction = None
    lastIterationAction = None

    fast = True

    validationResult = None

    playthroughLog = {}

    lastHeroSelected = None

    increasedRewardsPlaythrough = None

    lastPlaythrough = None
    lastPlaythroughStats = {}

    lastScreen = Screen.UNKNOWN
    lastState = State.UNDEFINED

    unknownScreenHasWaited = False

    segmentCoordinates = None

    while True:
        screenshot = np.array(pyautogui.screenshot())[:, :, ::-1].copy()

        screen = Screen.UNKNOWN
        activeWindow = ahk.get_active_window()
        if not activeWindow or not isBTD6Window(activeWindow.title):
            screen = Screen.BTD6_UNFOCUSED
        else:
            bestMatchDiff = None
            for screenCfg in [
                (Screen.STARTMENU, comparisonImages['screens']['startmenu'], imageAreas['compare']['screens']['startmenu']),
                (Screen.MAP_SELECTION, comparisonImages['screens']['map_selection'], imageAreas['compare']['screens']['map_selection']),
                (Screen.DIFFICULTY_SELECTION, comparisonImages['screens']['difficulty_selection'], imageAreas['compare']['screens']['difficulty_selection']),
                (Screen.GAMEMODE_SELECTION, comparisonImages['screens']['gamemode_selection'], imageAreas['compare']['screens']['gamemode_selection']),
                (Screen.HERO_SELECTION, comparisonImages['screens']['hero_selection'], imageAreas['compare']['screens']['hero_selection']),
                (Screen.INGAME, comparisonImages['screens']['ingame'], imageAreas['compare']['screens']['ingame']),
                (Screen.INGAME_PAUSED, comparisonImages['screens']['ingame_paused'], imageAreas['compare']['screens']['ingame_paused']),
                (Screen.VICTORY_SUMMARY, comparisonImages['screens']['victory_summary'], imageAreas['compare']['screens']['victory_summary']),
                (Screen.VICTORY, comparisonImages['screens']['victory'], imageAreas['compare']['screens']['victory']),
                (Screen.DEFEAT, comparisonImages['screens']['defeat'], imageAreas['compare']['screens']['defeat']),
                (Screen.OVERWRITE_SAVE, comparisonImages['screens']['overwrite_save'], imageAreas['compare']['screens']['overwrite_save']),
                (Screen.LEVELUP, comparisonImages['screens']['levelup'], imageAreas['compare']['screens']['levelup']),
                (Screen.APOPALYPSE_HINT, comparisonImages['screens']['apopalypse_hint'], imageAreas['compare']['screens']['apopalypse_hint']),
                (Screen.ROUND_100_INSTA, comparisonImages['screens']['round_100_insta'], imageAreas['compare']['screens']['round_100_insta']),
                (Screen.COLLECTION_CLAIM_CHEST, comparisonImages['screens']['collection_claim_chest'], imageAreas['compare']['screens']['collection_claim_chest']),
            ]:
                diff = cv2.matchTemplate(cutImage(screenshot, screenCfg[2]), cutImage(screenCfg[1], screenCfg[2]), cv2.TM_SQDIFF_NORMED)[0][0]
                if diff < 0.05 and (bestMatchDiff is None or diff < bestMatchDiff):
                    bestMatchDiff = diff
                    screen = screenCfg[0]

        if screen != lastScreen:
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
                if validationResult != None:
                    custom_print('validation result: playthrough ' + lastPlaythrough['filename'] + ' is ' + ('valid' if validationResult else 'invalid') + '!')
                    updatePlaythroughValidationStatus(lastPlaythrough['filename'], validationResult)
                if len(all_available_pPlaythroughs_list):
                    playthrough = all_available_pPlaythroughs_list.pop(0)
                    custom_print('validation playthrough chosen: ' + playthrough['fileConfig']['map'] + ' on ' + playthrough['gamemode'] + ' (' + playthrough['filename'] + ')')

                    gamemode = getAvailableSandbox(playthrough['fileConfig']['map'])
                    if gamemode:
                        mapConfig = parseBTD6InstructionsFile(playthrough['filename'], gamemode=gamemode)
                        objectives = []
                        objectives.append({'type': State.GOTO_HOME})
                        if 'hero' in mapConfig and lastHeroSelected != mapConfig['hero']:
                            objectives.append({'type': State.SELECT_HERO, 'mapConfig': mapConfig})
                            objectives.append({'type': State.GOTO_HOME})
                        objectives.append({'type': State.GOTO_INGAME, 'mapConfig': mapConfig})
                        objectives.append({'type': State.INGAME, 'mapConfig': mapConfig})
                        objectives.append({'type': State.MANAGE_OBJECTIVES})

                        validationResult = True
                        lastPlaythrough = playthrough
                    else:
                        custom_print('missing sandbox access for ' + playthrough['fileConfig']['map'])
                        objectives = []
                        objectives.append({'type': State.MANAGE_OBJECTIVES})
                else:
                    objectives = []
                    objectives.append({'type': State.EXIT})
            elif mode == Mode.VALIDATE_COSTS:
                oldTowers = copy.deepcopy(towers)
                changes = 0
                for monkeyType in costs['monkeys']:
                    if costs['monkeys'][monkeyType]['base'] and costs['monkeys'][monkeyType]['base'] != oldTowers['monkeys'][monkeyType]['base']:
                        print(f'{monkeyType} base cost: {oldTowers["monkeys"][monkeyType]["base"]} -> {int(costs["monkeys"][monkeyType]["base"])}')
                        towers['monkeys'][monkeyType]['base'] = int(costs['monkeys'][monkeyType]['base'])
                        changes += 1
                    for iPath in range(0, 3):
                        for iUpgrade in range(0, 5):
                            if costs['monkeys'][monkeyType]['upgrades'][iPath][iUpgrade] and costs['monkeys'][monkeyType]['upgrades'][iPath][iUpgrade] != oldTowers['monkeys'][monkeyType]['upgrades'][iPath][iUpgrade]:
                                print(f'{monkeyType} path {iPath + 1} upgrade {iUpgrade + 1} cost: {oldTowers["monkeys"][monkeyType]["upgrades"][iPath][iUpgrade]} -> {int(costs["monkeys"][monkeyType]["upgrades"][iPath][iUpgrade])}')
                                towers['monkeys'][monkeyType]['upgrades'][iPath][iUpgrade] = int(costs['monkeys'][monkeyType]['upgrades'][iPath][iUpgrade])
                                changes += 1
                if 'heroes' in costs:
                    for hero in costs['heroes']:
                        if costs['heroes'][hero]['base'] and costs['heroes'][hero]['base'] != oldTowers['heroes'][hero]['base']:
                            print(f'hero {hero} base cost: {oldTowers["heroes"][hero]["base"]} -> {int(costs["heroes"][hero]["base"])}')
                            towers['heroes'][hero]['base'] = int(costs['heroes'][hero]['base'])
                            changes += 1

                if changes:
                    print(f'updating "towers.json" with {changes} changes!')
                    fp = open('towers_backup.json', 'w')
                    fp.write(json.dumps(oldTowers, indent=4))
                    fp.close()
                    fp = open('towers.json', 'w')
                    fp.write(json.dumps(towers, indent=4))
                    fp.close()
                else:
                    print('no price changes in comparison to "towers.json" detected!')

                return
            elif repeatObjectives or gamesPlayed == 0:
                if mode == Mode.SINGLE_MAP:
                    objectives = copy.deepcopy(originalObjectives)
                elif mode == Mode.RANDOM_MAP or mode == Mode.XP_FARMING or mode == Mode.MM_FARMING:
                    objectives = []
                    playthrough = random.choice(all_available_pPlaythroughs_list)
                    custom_print('random playthrough chosen: ' + playthrough['fileConfig']['map'] + ' on ' + playthrough['gamemode'] + ' (' + playthrough['filename'] + ')')
                    mapConfig = parseBTD6InstructionsFile(playthrough['filename'], gamemode=playthrough['gamemode'])

                    objectives.append({'type': State.GOTO_HOME})
                    if 'hero' in mapConfig and lastHeroSelected != mapConfig['hero']:
                        objectives.append({'type': State.SELECT_HERO, 'mapConfig': mapConfig})
                        objectives.append({'type': State.GOTO_HOME})
                    objectives.append({'type': State.GOTO_INGAME, 'mapConfig': mapConfig})
                    objectives.append({'type': State.INGAME, 'mapConfig': mapConfig})
                    objectives.append({'type': State.MANAGE_OBJECTIVES})
                    lastPlaythrough = playthrough
                elif mode == Mode.CHASE_REWARDS:
                    objectives = []
                    if increasedRewardsPlaythrough:
                        playthrough = increasedRewardsPlaythrough
                        custom_print('highest reward playthrough chosen: ' + playthrough['fileConfig']['map'] + ' on ' + playthrough['gamemode'] + ' (' + playthrough['filename'] + ')')
                        mapConfig = parseBTD6InstructionsFile(playthrough['filename'], gamemode=playthrough['gamemode'])

                        objectives.append({'type': State.GOTO_HOME})
                        if 'hero' in mapConfig and lastHeroSelected != mapConfig['hero']:
                            objectives.append({'type': State.SELECT_HERO, 'mapConfig': mapConfig})
                            objectives.append({'type': State.GOTO_HOME})
                        objectives.append({'type': State.GOTO_INGAME, 'mapConfig': mapConfig})
                        objectives.append({'type': State.INGAME, 'mapConfig': mapConfig})
                        objectives.append({'type': State.MANAGE_OBJECTIVES})
                        increasedRewardsPlaythrough = None
                        lastPlaythrough = playthrough
                    else:
                        objectives.append({'type': State.GOTO_HOME})
                        objectives.append({'type': State.FIND_HARDEST_INCREASED_REWARDS_MAP})
                        objectives.append({'type': State.MANAGE_OBJECTIVES})
                else:
                    objectives = copy.deepcopy(originalObjectives)
            else:
                objectives = []
                objectives.append({'type': State.EXIT})

            state = objectives[0]['type']
            lastStateTransitionSuccessful = True
            objectiveFailed = False
        elif state == State.UNDEFINED:
            custom_print('entered state management!')
            if exit_after_game:
                state = State.EXIT
            if objectiveFailed:
                custom_print('objective failed on step ' + objectives[0]['type'].name + '(screen ' + lastScreen.name + ')!')
                if repeatObjectives:
                    state = State.MANAGE_OBJECTIVES
                else:
                    state = State.EXIT
            elif not lastStateTransitionSuccessful:
                state = objectives[0]['type']
                if 'mapConfig' in objectives[0]:
                    mapConfig = objectives[0]['mapConfig']
                lastStateTransitionSuccessful = True
            elif lastStateTransitionSuccessful and len(objectives):
                objectives.pop(0)
                state = objectives[0]['type']
                if 'mapConfig' in objectives[0]:
                    mapConfig = objectives[0]['mapConfig']
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
                if lastScreen == Screen.UNKNOWN and unknownScreenHasWaited:
                    unknownScreenHasWaited = False
                    sendKey('{Esc}')
                else:
                    unknownScreenHasWaited = True
                    time.sleep(2)
            elif screen == Screen.INGAME:
                sendKey('{Esc}')
            elif screen == Screen.INGAME_PAUSED:
                pyautogui.click(imageAreas['click']['screen_ingame_paused_button_home'])
            elif screen in [Screen.HERO_SELECTION, Screen.GAMEMODE_SELECTION, Screen.DIFFICULTY_SELECTION, Screen.MAP_SELECTION]:
                sendKey('{Esc}')
            elif screen == Screen.DEFEAT:
                result = cv2.matchTemplate(screenshot, locateImages['button_home'], cv2.TM_SQDIFF_NORMED)
                pyautogui.click(cv2.minMaxLoc(result)[2])
            elif screen == Screen.VICTORY_SUMMARY:
                pyautogui.click(imageAreas['click']['screen_victory_summary_button_next'])
            elif screen == Screen.VICTORY:
                pyautogui.click(imageAreas['click']['screen_victory_button_home'])
            elif screen == Screen.OVERWRITE_SAVE:
                sendKey('{Esc}')
            elif screen == Screen.LEVELUP:
                pyautogui.click(100, 100)
                time.sleep(menu_change_delay)
                pyautogui.click(100, 100)
            elif screen == Screen.ROUND_100_INSTA:
                pyautogui.click(100, 100)
                time.sleep(menu_change_delay)
            elif screen == Screen.COLLECTION_CLAIM_CHEST:
                pyautogui.click(imageAreas['click']['collection_claim_chest'])
                time.sleep(menu_change_delay * 2)
                while True:
                    newScreenshot = np.array(pyautogui.screenshot())[:, :, ::-1].copy()
                    result = [cv2.minMaxLoc(cv2.matchTemplate(newScreenshot, locateImages['unknown_insta'], cv2.TM_SQDIFF_NORMED, mask=locateImages['unknown_insta_mask']))[i] for i in [0, 2]]
                    if result[0] < 0.01:
                        pyautogui.click(result[1])
                        time.sleep(menu_change_delay)
                        pyautogui.click(result[1])
                        time.sleep(menu_change_delay)
                    else:
                        break
                pyautogui.click(round(resolution[0] / 2), round(resolution[1] / 2))
                time.sleep(menu_change_delay)
                sendKey('{Esc}')
            elif screen == Screen.APOPALYPSE_HINT:
                pyautogui.click(imageAreas['click']['gamemode_apopalypse_message_confirmation'])
        elif state == State.GOTO_INGAME:
            if mapConfig is None:
                custom_print('Error: mapConfig is None in GOTO_INGAME state!')
                sys.exit(1)

            if screen == Screen.STARTMENU:
                pyautogui.click(imageAreas['click']['screen_startmenu_button_play'])
                time.sleep(menu_change_delay)
                if mapConfig['category'] == 'beginner':
                    pyautogui.click(imageAreas['click']['map_categories']['advanced'])
                    time.sleep(menu_change_delay)
                    pyautogui.click(imageAreas['click']['map_categories'][mapConfig['category']])
                    time.sleep(menu_change_delay)
                else:
                    pyautogui.click(imageAreas['click']['map_categories']['beginner'])
                    time.sleep(menu_change_delay)
                    pyautogui.click(imageAreas['click']['map_categories'][mapConfig['category']])
                    time.sleep(menu_change_delay)
                tmpClicks = mapConfig['page']
                while tmpClicks > 0:
                    pyautogui.click(imageAreas['click']['map_categories'][mapConfig['category']])
                    tmpClicks -= 1
                    time.sleep(menu_change_delay)
                pyautogui.click(imageAreas['click']['map_positions'][mapConfig['pos']])
                time.sleep(menu_change_delay)
                pyautogui.click(imageAreas['click']['gamedifficulty_positions'][mapConfig['difficulty']])
                time.sleep(menu_change_delay)
                pyautogui.click(get_gamemode_position(mapConfig['gamemode']))
            elif screen == Screen.OVERWRITE_SAVE:
                pyautogui.click(imageAreas['click']['screen_overwrite_save_button_ok'])
            elif screen == Screen.APOPALYPSE_HINT:
                pyautogui.click(imageAreas['click']['gamemode_apopalypse_message_confirmation'])
            elif screen == Screen.INGAME:
                custom_print('goal GOTO_INGAME fulfilled!')
                custom_print('game: ' + mapConfig['map'] + ' - ' + mapConfig['difficulty'])
                segmentCoordinates = getIngameOcrSegments(mapConfig)
                iterationBalances = []
                if logStats:
                    lastPlaythroughStats = {'gamemode': mapConfig['gamemode'], 'time': [], 'result': PlaythroughResult.UNDEFINED}
                    lastPlaythroughStats['time'].append(('start', time.time()))
                lastIterationBalance = -1
                lastIterationCost = 0
                state = State.UNDEFINED
            elif screen == Screen.UNKNOWN:
                pass
            else:
                custom_print('task GOTO_INGAME, but not in startmenu!')
                state = State.GOTO_HOME
                lastStateTransitionSuccessful = False
        elif state == State.SELECT_HERO:
            if mapConfig is None:
                custom_print('Error: mapConfig is None in SELECT_HERO state!')
                sys.exit(1)

            if screen == Screen.STARTMENU:
                pyautogui.click(imageAreas['click']['screen_startmenu_button_hero_selection'])
                time.sleep(menu_change_delay)
                pyautogui.click(imageAreas['click']['hero_positions'][mapConfig['hero']])
                time.sleep(menu_change_delay)
                pyautogui.click(imageAreas['click']['screen_hero_selection_select_hero'])
                custom_print('goal SELECT_HERO ' + mapConfig['hero'] + ' fulfilled!')
                lastHeroSelected = mapConfig['hero']
                state = State.UNDEFINED
            elif screen == Screen.UNKNOWN:
                pass
            else:
                custom_print('task SELECT_HERO, but not in startmenu!')
                state = State.GOTO_HOME
                lastStateTransitionSuccessful = False
        elif state == State.FIND_HARDEST_INCREASED_REWARDS_MAP:
            if screen == Screen.STARTMENU:
                pyautogui.click(imageAreas['click']['screen_startmenu_button_play'])
                time.sleep(menu_change_delay)

                if categoryRestriction:
                    pyautogui.click(imageAreas['click']['map_categories'][('advanced' if categoryRestriction == 'beginner' else 'beginner')])
                    time.sleep(menu_change_delay)

                    map_name = None
                    for page in range(0, categoryPages[categoryRestriction]):
                        pyautogui.click(imageAreas['click']['map_categories'][categoryRestriction])
                        if collectionEvent == 'golden_bloon':
                            time.sleep(4)
                        else:
                            time.sleep(menu_change_delay)
                        newScreenshot = np.array(pyautogui.screenshot())[:, :, ::-1].copy()
                        result = findImageInImage(newScreenshot, locateImages['collection'][collectionEvent])
                        if result[0] < 0.05:
                            map_name = findMapForPxPos(categoryRestriction, page, result[1])
                            break
                    if not map_name:
                        custom_print('no maps with increased rewards found! exiting!')
                        return
                    custom_print('best map: ' + map_name)
                    increasedRewardsPlaythrough = getHighestValuePlaythrough(all_available_playthroughs, map_name, playthroughLog)
                    if not increasedRewardsPlaythrough:
                        custom_print('no playthroughs for map found! exiting!')
                        return
                else:
                    iTmp = 0
                    for category in reversed(list(maps_by_category.keys())):
                        if iTmp == 0:
                            pyautogui.click(imageAreas['click']['map_categories'][('advanced' if category == 'beginner' else 'beginner')])
                            time.sleep(menu_change_delay)

                        map_name = None
                        for page in range(0, categoryPages[category]):
                            pyautogui.click(imageAreas['click']['map_categories'][category])
                            if collectionEvent == 'golden_bloon':
                                time.sleep(4)
                            else:
                                time.sleep(menu_change_delay)
                            newScreenshot = np.array(pyautogui.screenshot())[:, :, ::-1].copy()
                            result = findImageInImage(newScreenshot, locateImages['collection'][collectionEvent])
                            if result[0] < 0.05:
                                map_name = findMapForPxPos(category, page, result[1])
                                break
                        if not map_name:
                            custom_print('no maps with increased rewards found! exiting!')
                            return
                        custom_print('best map in ' + category + ': ' + map_name)
                        increasedRewardsPlaythrough = getHighestValuePlaythrough(all_available_playthroughs, map_name, playthroughLog)
                        if increasedRewardsPlaythrough:
                            break
                        else:
                            custom_print('no playthroughs for map found! searching lower map tiers!')
                        iTmp += 1

                    if not increasedRewardsPlaythrough:
                        custom_print('no available playthrough found! exiting!')
                        return
                state = State.UNDEFINED
            elif screen == Screen.UNKNOWN:
                pass
            else:
                custom_print('task FIND_HARDEST_INCREASED_REWARDS_MAP, but not in startmenu!')
                state = State.GOTO_HOME
                lastStateTransitionSuccessful = False
        elif state == State.INGAME:
            if mapConfig is None:
                custom_print('Error: mapConfig is None in INGAME state!')
                sys.exit(1)

            if screen == Screen.INGAME_PAUSED:
                if lastScreen != screen and logStats:
                    lastPlaythroughStats['time'].append(('stop', time.time()))
                time.sleep(2)
                if isBTD6Window(ahk.get_active_window().title):
                    sendKey('{Esc}')
            elif screen == Screen.UNKNOWN:
                if lastScreen == Screen.UNKNOWN and unknownScreenHasWaited:
                    unknownScreenHasWaited = False
                    sendKey('{Esc}')
                else:
                    unknownScreenHasWaited = True
                    time.sleep(2)
            elif screen == Screen.LEVELUP:
                pyautogui.click(100, 100)
                time.sleep(menu_change_delay)
                pyautogui.click(100, 100)
            elif screen == Screen.ROUND_100_INSTA:
                pyautogui.click(100, 100)
                time.sleep(menu_change_delay)
            elif screen == Screen.VICTORY_SUMMARY:
                if logStats:
                    lastPlaythroughStats['time'].append(('stop', time.time()))
                    lastPlaythroughStats['result'] = PlaythroughResult.WIN
                    updateStatsFile(mapConfig['filename'], lastPlaythroughStats)
                gamesPlayed += 1
                if mapConfig['filename'] not in playthroughLog:
                    playthroughLog[mapConfig['filename']] = {}
                if mapConfig['gamemode'] not in playthroughLog[mapConfig['filename']]:
                    playthroughLog[mapConfig['filename']][mapConfig['gamemode']] = {'attempts': 0, 'wins': 0, 'defeats': 0}
                playthroughLog[mapConfig['filename']][mapConfig['gamemode']]['attempts'] += 1
                playthroughLog[mapConfig['filename']][mapConfig['gamemode']]['wins'] += 1

                if not isContinue:
                    updateMedalStatus(mapConfig['map'], mapConfig['gamemode'])

                state = State.UNDEFINED
            elif screen == Screen.DEFEAT:
                if logStats:
                    lastPlaythroughStats['time'].append(('stop', time.time()))
                    lastPlaythroughStats['result'] = PlaythroughResult.DEFEAT
                    updateStatsFile(mapConfig['filename'], lastPlaythroughStats)
                objectiveFailed = True
                gamesPlayed += 1
                if mapConfig['filename'] not in playthroughLog:
                    playthroughLog[mapConfig['filename']] = {}
                if mapConfig['gamemode'] not in playthroughLog[mapConfig['filename']]:
                    playthroughLog[mapConfig['filename']][mapConfig['gamemode']] = {'attempts': 0, 'wins': 0, 'defeats': 0}
                playthroughLog[mapConfig['filename']][mapConfig['gamemode']]['attempts'] += 1
                playthroughLog[mapConfig['filename']][mapConfig['gamemode']]['defeats'] += 1

                state = State.UNDEFINED
            elif screen == Screen.INGAME:
                if lastScreen != screen and logStats:
                    lastPlaythroughStats['time'].append(('start', time.time()))

                images = [screenshot[segmentCoordinates[segment][1] : segmentCoordinates[segment][3], segmentCoordinates[segment][0] : segmentCoordinates[segment][2]] for segment in segmentCoordinates]

                currentValues = {}
                thisIterationCost = 0
                thisIterationAction = None
                skippingIteration = False

                try:
                    currentValues['money'] = int(custom_ocr(images[2]))
                    currentValues['round'] = int(custom_ocr(images[3]).split('/')[0])
                except ValueError:
                    currentValues['money'] = -1
                    currentValues['round'] = -1

                # to prevent random explosion particles that were recognized as digits from messing up the game
                # still possible: if it happens 2 times in a row
                # potential solution: when placing: check if pixel changed colour(or even is of correct colour) - potentially blocked by particles/projectiles
                # when upgrading: check if corresponding box turned green(for left and right menu)
                # remove obstacle: colour change?

                if len(mapConfig['steps']):
                    if mapConfig['steps'][0]['action'] == 'sell':
                        custom_print(
                            'detected money: '
                            + str(currentValues['money'])
                            + ', required: '
                            + str(get_next_non_sell_action(mapConfig['steps'])['cost'] - sum_adjacent_sells(mapConfig['steps']))
                            + ' ('
                            + str(get_next_non_sell_action(mapConfig['steps'])['cost'])
                            + ' - '
                            + str(sum_adjacent_sells(mapConfig['steps']))
                            + ')'
                            + '          ',
                            end='',
                            rewriteLine=True,
                        )
                    if mapConfig['steps'][0]['action'] == 'await_round':
                        custom_print('detected round: ' + str(currentValues['round']) + ', awaiting: ' + str(mapConfig['steps'][0]['round']) + '          ', end='', rewriteLine=True)
                    else:
                        custom_print('detected money: ' + str(currentValues['money']) + ', required: ' + str(mapConfig['steps'][0]['cost']) + '          ', end='', rewriteLine=True)

                if mode == Mode.VALIDATE_PLAYTHROUGHS:
                    if lastIterationBalance != -1 and currentValues['money'] != lastIterationBalance - lastIterationCost:
                        if currentValues['money'] == lastIterationBalance:
                            custom_print('action: ' + str(lastIterationAction) + ' failed!')
                            validationResult = False
                            mapConfig['steps'] = []
                        else:
                            custom_print('pricing error! expected cost: ' + str(lastIterationCost) + ', detected cost: ' + str(lastIterationBalance - currentValues['money']) + '. Is monkey knowledge disabled?')
                elif mode == Mode.VALIDATE_COSTS:
                    if lastIterationBalance != -1 and lastIterationAction:
                        if lastIterationAction['action'] == 'place':
                            costs[lastIterationAction['extra']['group']][lastIterationAction['extra']['type']]['base'] = int(lastIterationBalance - currentValues['money'])
                        elif lastIterationAction['action'] == 'upgrade':
                            costs[lastIterationAction['extra']['group']][lastIterationAction['extra']['type']]['upgrades'][lastIterationAction['extra']['upgrade'][0]][lastIterationAction['extra']['upgrade'][1] - 1] = int(lastIterationBalance - currentValues['money'])

                if mode == Mode.VALIDATE_PLAYTHROUGHS and len(mapConfig['steps']) and (mapConfig['steps'][0]['action'] == 'await_round' or mapConfig['steps'][0]['action'] == 'speed'):
                    mapConfig['steps'].pop(0)
                elif currentValues['money'] == -1 or currentValues['round'] == -1 and len(mapConfig['steps']) and mapConfig['steps'][0]['action'] == 'await_round':
                    custom_print('recognition error. money: ' + str(currentValues['money']) + ', round: ' + str(currentValues['round']))
                elif mode != Mode.VALIDATE_COSTS and lastIterationBalance - lastIterationCost > currentValues['money']:
                    custom_print('potential cash recognition error: ' + str(lastIterationBalance) + ' - ' + str(lastIterationCost) + ' -> ' + str(currentValues['money']))
                    # cv2.imwrite('tmp_images/' + time.strftime("%Y-%m-%d_%H-%M-%S") + '_' + str(lastIterationBalance) + '.png', lastIterationScreenshotAreas[2])
                    # cv2.imwrite('tmp_images/' + time.strftime("%Y-%m-%d_%H-%M-%S") + '_' + str(currentValues['money']) + '.png', images[2])
                    skippingIteration = True
                elif mode != Mode.VALIDATE_COSTS and (currentValues['round'] - lastIterationRound > 1 or lastIterationRound > currentValues['round']) and len(mapConfig['steps']) and mapConfig['steps'][0]['action'] == 'await_round':
                    custom_print('potential round recognition error: ' + str(lastIterationRound) + ' -> ' + str(currentValues['round']))
                    skippingIteration = True
                elif len(mapConfig['steps']) and (
                    (mapConfig['steps'][0]['action'] != 'sell' and mapConfig['steps'][0]['action'] != 'await_round' and min(currentValues['money'], lastIterationBalance - lastIterationCost) >= mapConfig['steps'][0]['cost'])
                    or mapConfig['gamemode'] == 'deflation'
                    or mapConfig['steps'][0]['action'] == 'await_round'
                    and currentValues['round'] >= mapConfig['steps'][0]['round']
                    or mapConfig['steps'][0]['action'] == 'await_round'
                    and mode == Mode.VALIDATE_PLAYTHROUGHS
                    or ((mapConfig['steps'][0]['action'] == 'sell') and min(currentValues['money'], lastIterationBalance - lastIterationCost) + sum_adjacent_sells(mapConfig['steps']) >= get_next_non_sell_action(mapConfig['steps'])['cost'])
                ):
                    action = mapConfig['steps'].pop(0)
                    thisIterationAction = action
                    if action['action'] != 'sell' and action['action'] != 'await_round':
                        thisIterationCost = action['cost']
                    custom_print('performing action: ' + str(action))
                    if action['action'] == 'place':
                        pyautogui.moveTo(action['pos'])
                        time.sleep(action_delay)
                        sendKey(action['key'])
                        time.sleep(action_delay)
                        pyautogui.click()
                    elif action['action'] == 'upgrade' or action['action'] == 'retarget' or action['action'] == 'special':
                        # game hints potentially blocking monkeys
                        pyautogui.click(action['pos'])
                        time.sleep(action_delay)
                        actionTmp = None
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
                                sendKey(action['key'])
                            if 'to' in action and mapConfig['monkeys'][action['name']]['type'] == 'mortar':
                                pyautogui.click()
                            time.sleep(small_action_delay)
                            actionTmp = action
                            if len(mapConfig['steps']) and 'name' in mapConfig['steps'][0] and mapConfig['steps'][0]['name'] == action['name'] and (mapConfig['steps'][0]['action'] == 'retarget' or mapConfig['steps'][0]['action'] == 'special' or mapConfig['steps'][0]['action'] == 'click'):
                                action = mapConfig['steps'].pop(0)
                                custom_print('+' + action['action'])
                            else:
                                action = None
                        action = actionTmp
                        sendKey('{Esc}')
                    elif action['action'] == 'sell':
                        pyautogui.moveTo(action['pos'])
                        pyautogui.click()
                        time.sleep(action_delay)
                        sendKey(action['key'])
                    elif action['action'] == 'remove':
                        custom_print('removing obstacle at ' + tupleToStr(action['pos']) + ' for ' + str(action['cost']))
                        pyautogui.moveTo(action['pos'])
                        pyautogui.click()
                        time.sleep(menu_change_delay)
                        result = cv2.matchTemplate(np.array(pyautogui.screenshot())[:, :, ::-1].copy(), locateImages['remove_obstacle_confirm_button'], cv2.TM_SQDIFF_NORMED)
                        pyautogui.click(cv2.minMaxLoc(result)[2])
                    elif action['action'] == 'click':
                        pyautogui.moveTo(action['pos'])
                        pyautogui.click()
                    elif action['action'] == 'press':
                        sendKey(action['key'])
                    elif action['action'] == 'speed':
                        if action['speed'] == 'fast':
                            fast = True
                        elif action['speed'] == 'slow':
                            fast = False

                elif mode in [Mode.VALIDATE_PLAYTHROUGHS, Mode.VALIDATE_COSTS] and len(mapConfig['steps']) == 0 and lastIterationCost == 0:
                    state = State.UNDEFINED

                if (not doAllStepsBeforeStart and mapConfig['gamemode'] != 'deflation' and not skippingIteration and get_next_costing_action(mapConfig['steps'])['cost'] > min(currentValues['money'], lastIterationBalance - lastIterationCost)) or len(mapConfig['steps']) == 0:
                    bestMatchDiff = None
                    gameState = None
                    for screenCfg in [
                        ('game_playing_fast', comparisonImages['game_state']['game_playing_fast'], imageAreas['compare']['game_state']),
                        ('game_playing_slow', comparisonImages['game_state']['game_playing_slow'], imageAreas['compare']['game_state']),
                        ('game_paused', comparisonImages['game_state']['game_paused'], imageAreas['compare']['game_state']),
                    ]:
                        diff = cv2.matchTemplate(cutImage(screenshot, screenCfg[2]), cutImage(screenCfg[1], screenCfg[2]), cv2.TM_SQDIFF_NORMED)[0][0]
                        if bestMatchDiff is None or diff < bestMatchDiff:
                            bestMatchDiff = diff
                            gameState = screenCfg[0]

                    if gameState == 'game_playing_fast' and not fast or gameState == 'game_playing_slow' and fast or gameState == 'game_paused':
                        sendKey(keybinds['others']['play'])

                lastIterationScreenshotAreas = images
                lastIterationBalance = currentValues['money']
                lastIterationCost = thisIterationCost
                lastIterationAction = thisIterationAction

                lastIterationRound = currentValues['round']

                iterationBalances.append((currentValues['money'], thisIterationCost))
            else:
                custom_print('task INGAME, but not in related screen!')
                state = State.GOTO_HOME
                lastStateTransitionSuccessful = False
        else:
            state = State.UNDEFINED
            lastStateTransitionSuccessful = False

        if state != lastState:
            custom_print('new state ' + state.name + '!')

        lastScreen = screen
        lastState = state

        time.sleep(action_delay if state == State.INGAME else menu_change_delay)


if __name__ == '__main__':
    main()
