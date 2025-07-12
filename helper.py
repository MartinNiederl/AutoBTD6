import copy
import json
import math
import os
import re
from enum import Enum
from os.path import exists

import numpy as np
import pyautogui
from ahk import AHK

from consts import SANDBOX_GAMEMODES

# from instructions_file_manager import parse_btd6_instruction_file_name, parse_btd6_instructions_file # TODO: temporarily moved back here
from utils.utils import create_resolution_string, custom_print, load_json_file, save_json_file, scale_string_coordinate_pairs, tuple_to_str

# TODO: fix circular imports!!


def parse_btd6_instruction_file_name(filename: str):
    matches = re.search(
        r'^(?:(?:own_|unvalidated_|unsuccessful_)?playthroughs\/)?(?P<map>\w+)#(?P<gamemode>\w+)#(?P<resolution>(?P<resolution_x>\d+)x(?P<resolution_y>\d+))(?:#(?P<comment>.+))?\.btd6$',
        filename,
    )
    if not matches:
        return None
    matches = matches.groupdict()
    matches['noMK'] = False
    matches['noLL'] = False
    matches['noLLwMK'] = False
    for m in re.finditer(
        r'(?P<noMK>noMK(?:#|$))?(?:(?P<singleType>[a-z]+)Only(?:#|$))?(?P<noLL>noLL(?:#|$))?(?P<noLLwMK>noLLwMK(?:#|$))?(?P<gB>gB(?:#|$))?',
        matches['comment'] if 'comment' in matches and matches['comment'] else '',
    ):
        if m.group('noMK'):
            matches['noMK'] = True
        if m.group('noLL'):
            matches['noLL'] = True
        if m.group('noLLwMK'):
            matches['noLLwMK'] = True
        if m.group('gB'):
            matches['gB'] = True
    return matches


def get_btd6_instructions_file_name_by_config(this_config, folder='own_playthroughs', resolution=create_resolution_string()):
    return folder + '/' + this_config['map'] + '#' + this_config['gamemode'] + '#' + resolution + ('#' + this_config['comment'] if 'comment' in this_config and this_config['comment'] else '') + '.btd6'


def write_btd6_instructions_file(this_config, folder='own_playthroughs', resolution=create_resolution_string()):
    filename = get_btd6_instructions_file_name_by_config(this_config, folder, resolution)

    if not exists(folder):
        os.mkdir(folder)

    with open(filename, 'w') as fp:
        for action in this_config['steps']:
            if action['action'] == 'place':
                fp.write('place ' + (this_config['hero'] if action['type'] == 'hero' else action['type']) + ' ' + action['name'] + ' at ' + tuple_to_str(action['pos']) + (' with ' + action['discount'] + '% discount' if 'discount' in action else '') + '\n')
            elif action['action'] == 'upgrade':
                fp.write('upgrade ' + action['name'] + ' path ' + str(action['path']) + (' with ' + action['discount'] + '% discount' if 'discount' in action else '') + '\n')
            elif action['action'] == 'retarget':
                fp.write('retarget ' + action['name'] + (' to ' + tuple_to_str(action['to']) if 'to' in action else '') + '\n')
            elif action['action'] == 'special':
                fp.write('special ' + action['name'] + '\n')
            elif action['action'] == 'sell':
                fp.write('sell ' + action['name'] + '\n')
            elif action['action'] == 'remove':
                cost = ''
                while True:
                    print('enter cost of obstacle removal at ' + tuple_to_str(action['pos']) + ' >')
                    cost = input()
                    if len(cost) and cost.isdigit():
                        break
                    else:
                        print('non integer provided!')
                fp.write('remove obstacle at ' + tuple_to_str(action['pos']) + ' for ' + str(cost) + '\n')
            elif action['action'] == 'await_round':
                fp.write('round ' + str(action['round']) + '\n')


def parse_btd6_instructions_file(filename, target_resolution=pyautogui.size(), gamemode=None):
    file_config = parse_btd6_instruction_file_name(filename)

    if not file_config:
        return None

    sandbox_mode = False

    map_name = file_config['map']
    if map_name not in maps:
        print('unknown map: ' + str(map_name))
        return None
    gamemode = gamemode if gamemode else file_config['gamemode']
    if gamemode not in gamemodes and gamemode not in SANDBOX_GAMEMODES:
        print('unknown gamemode: ' + str(gamemode))
        return None
    if gamemode in SANDBOX_GAMEMODES:
        sandbox_mode = True
    if not exists(filename):
        print('unknown file: ' + str(filename))
        return None

    with open(filename, 'r') as fp:
        raw_input_file = fp.read()

    if not target_resolution and file_config['resolution'] != create_resolution_string():
        custom_print('tried parsing playthrough for non native resolution with rescaling disabled!')
        return None
    elif file_config['resolution'] != create_resolution_string(target_resolution):
        # customPrint("rescaling " + filename + " from " + fileConfig['resolution'] + " to " + getResolutionString(targetResolution))
        raw_input_file = scale_string_coordinate_pairs(
            raw_input_file,
            [int(x) for x in file_config['resolution'].split('x')],
            target_resolution,
        )

    config_lines = raw_input_file.splitlines()

    monkeys = {}

    new_map_config = {
        'category': maps[map_name]['category'],
        'map': map_name,
        'page': maps[map_name]['page'],
        'pos': maps[map_name]['pos'],
        'difficulty': (gamemodes[gamemode]['group'] if not sandbox_mode else SANDBOX_GAMEMODES[gamemode]['group']),
        'gamemode': gamemode,
        'steps': [],
        'extrainstructions': 0,
        'filename': filename,
    }

    if gamemode == 'deflation' or gamemode == 'half_cash' or gamemode == 'impoppable' or gamemode == 'chimps' or gamemode in SANDBOX_GAMEMODES:
        new_map_config['steps'].append(
            {
                'action': 'click',
                'pos': image_areas['click']['gamemode_deflation_message_confirmation'],
                'cost': 0,
            },
        )
        new_map_config['extrainstructions'] = 1

    for line in config_lines:
        matches = re.search(
            r'^(?P<action>place|upgrade|retarget|special|sell|remove|round|speed) ?(?P<type>[a-z_]+)? (?P<name>\w+)(?: (?:(?:at|to) (?P<x>\d+), (?P<y>\d+))?(?:path (?P<path>[0-2]))?)?(?: for (?P<price>\d+|\?\?\?))?(?: with (?P<discount>\d{1,2}|100)% discount)?$',
            line,
        )
        if not matches:
            continue

        new_step = None
        new_steps = []

        if matches.group('action') == 'place':
            if monkeys.get(matches.group('name')):
                print(filename + ': monkey ' + matches.group('name') + ' placed twice! skipping!')
                continue
            if matches.group('type') in towers['monkeys']:
                new_step = {
                    'action': 'place',
                    'type': matches.group('type'),
                    'name': matches.group('name'),
                    'key': keybinds['monkeys'][matches.group('type')],
                    'pos': (int(matches.group('x')), int(matches.group('y'))),
                    'cost': calculate_adjusted_price(
                        towers['monkeys'][matches.group('type')]['base'],
                        new_map_config['difficulty'],
                        gamemode,
                        {'action': 'place'},
                        {
                            'type': matches.group('type'),
                            'name': matches.group('name'),
                            'upgrades': [0, 0, 0],
                        },
                        matches.group('discount'),
                    ),
                }
                if matches.group('discount'):
                    new_step['discount'] = matches.group('discount')
                monkeys[matches.group('name')] = {
                    'type': matches.group('type'),
                    'name': matches.group('name'),
                    'upgrades': [0, 0, 0],
                    'pos': (int(matches.group('x')), int(matches.group('y'))),
                    'value': calculate_adjusted_price(
                        towers['monkeys'][matches.group('type')]['base'],
                        new_map_config['difficulty'],
                        gamemode,
                        {'action': 'place'},
                        {
                            'type': matches.group('type'),
                            'name': matches.group('name'),
                            'upgrades': [0, 0, 0],
                        },
                        matches.group('discount'),
                    ),
                }
                new_steps.append(new_step)
            elif matches.group('type') in towers['heroes']:
                new_step = {
                    'action': 'place',
                    'type': 'hero',
                    'name': matches.group('name'),
                    'key': keybinds['monkeys']['hero'],
                    'pos': (int(matches.group('x')), int(matches.group('y'))),
                    'cost': calculate_adjusted_price(
                        towers['heroes'][matches.group('type')]['base'],
                        new_map_config['difficulty'],
                        gamemode,
                        {'action': 'place'},
                        {
                            'type': 'hero',
                            'name': matches.group('name'),
                            'upgrades': [0, 0, 0],
                        },
                        matches.group('discount'),
                    ),
                }
                if matches.group('discount'):
                    new_step['discount'] = matches.group('discount')
                new_map_config['hero'] = matches.group('type')
                monkeys[matches.group('name')] = {
                    'type': 'hero',
                    'name': matches.group('name'),
                    'upgrades': [0, 0, 0],
                    'pos': (int(matches.group('x')), int(matches.group('y'))),
                    'value': calculate_adjusted_price(
                        towers['heroes'][matches.group('type')]['base'],
                        new_map_config['difficulty'],
                        gamemode,
                        {'action': 'place'},
                        {
                            'type': 'hero',
                            'name': matches.group('name'),
                            'upgrades': [0, 0, 0],
                        },
                        matches.group('discount'),
                    ),
                }
                new_steps.append(new_step)
            else:
                print(filename + ': monkey/hero ' + matches.group('name') + ' has unknown type: ' + matches.group('type') + '! skipping!')
                continue
        elif matches.group('action') == 'upgrade':
            if not monkeys.get(matches.group('name')):
                print(filename + ': monkey ' + matches.group('name') + ' unplaced! skipping!')
                continue
            if monkeys[matches.group('name')]['type'] == 'hero':
                print(filename + ': tried to upgrade hero ' + matches.group('name') + '! skipping instruction!')
                continue
            monkey_upgrades = monkeys[matches.group('name')]['upgrades']
            monkey_upgrades[int(matches.group('path'))] += 1
            if sum(map(lambda x: x > 2, monkey_upgrades)) > 1 or sum(map(lambda x: x > 0, monkey_upgrades)) > 2 or monkey_upgrades[int(matches.group('path'))] > 5:
                print(filename + ': monkey ' + matches.group('name') + ' has invalid upgrade path! skipping!')
                monkey_upgrades[int(matches.group('path'))] -= 1
                continue
            new_step = {
                'action': 'upgrade',
                'name': matches.group('name'),
                'key': keybinds['path'][str(matches.group('path'))],
                'pos': monkeys[matches.group('name')]['pos'],
                'path': int(matches.group('path')),
                'cost': calculate_adjusted_price(
                    towers['monkeys'][monkeys[matches.group('name')]['type']]['upgrades'][int(matches.group('path'))][monkey_upgrades[int(matches.group('path'))] - 1],
                    new_map_config['difficulty'],
                    gamemode,
                    {'action': 'upgrade', 'path': int(matches.group('path'))},
                    monkeys[matches.group('name')],
                    matches.group('discount'),
                ),
            }
            if matches.group('discount'):
                new_step['discount'] = matches.group('discount')
            monkeys[matches.group('name')]['value'] += calculate_adjusted_price(
                towers['monkeys'][monkeys[matches.group('name')]['type']]['upgrades'][int(matches.group('path'))][monkey_upgrades[int(matches.group('path'))] - 1],
                new_map_config['difficulty'],
                gamemode,
                {'action': 'upgrade', 'path': int(matches.group('path'))},
                monkeys[matches.group('name')],
                matches.group('discount'),
            )
            new_steps.append(new_step)
            if upgrade_requires_confirmation(monkeys[matches.group('name')], int(matches.group('path'))):
                new_steps.append(
                    {
                        'action': 'click',
                        'name': matches.group('name'),
                        'pos': image_areas['click']['paragon_message_confirmation'],
                        'cost': 0,
                    },
                )
        elif matches.group('action') == 'retarget':
            if not monkeys.get(matches.group('name')):
                print(filename + ': monkey ' + matches.group('name') + ' unplaced! skipping!')
                continue
            new_step = {
                'action': 'retarget',
                'name': matches.group('name'),
                'key': keybinds['others']['retarget'],
                'pos': monkeys[matches.group('name')]['pos'],
                'cost': 0,
            }
            if matches.group('x'):
                new_step['to'] = (int(matches.group('x')), int(matches.group('y')))
            elif monkeys[matches.group('name')]['type'] == 'mortar':
                print('mortar can only be retargeted to a position! skipping!')
                continue
            new_steps.append(new_step)
        elif matches.group('action') == 'special':
            if not monkeys.get(matches.group('name')):
                print(filename + ': monkey ' + matches.group('name') + ' unplaced! skipping!')
                continue
            new_step = {
                'action': 'special',
                'name': matches.group('name'),
                'key': keybinds['others']['special'],
                'pos': monkeys[matches.group('name')]['pos'],
                'cost': 0,
            }
            new_steps.append(new_step)
        elif matches.group('action') == 'sell':
            if not monkeys.get(matches.group('name')):
                print(filename + ': monkey ' + matches.group('name') + ' unplaced! skipping!')
                continue
            new_step = {
                'action': 'sell',
                'name': matches.group('name'),
                'key': keybinds['others']['sell'],
                'pos': monkeys[matches.group('name')]['pos'],
                'cost': -get_monkey_sell_value(monkeys[matches.group('name')]['value']),
            }
            new_steps.append(new_step)
        elif matches.group('action') == 'remove':
            if matches.group('price') == '???':
                print('remove obstacle without price specified: ' + line)
                continue
            new_step = {
                'action': 'remove',
                'pos': (int(matches.group('x')), int(matches.group('y'))),
                'cost': int(matches.group('price')),
            }
            new_steps.append(new_step)
        elif matches.group('action') == 'round':
            try:
                if int(matches.group('name')) < 1:
                    print(f'Invalid round {matches.group("name")}, skipping!')
                    continue
            except ValueError:
                print(f'NaN round {matches.group("name")}, skipping!')
            new_step = {
                'action': 'await_round',
                'round': int(matches.group('name')),
                'cost': 0,
            }
            new_steps.append(new_step)
        elif matches.group('action') == 'speed':
            new_step = {
                'action': 'speed',
                'speed': matches.group('name'),
                'cost': 0,
            }
            new_steps.append(new_step)

        if len(new_steps):
            new_map_config['steps'] += new_steps

    new_map_config['monkeys'] = monkeys
    return new_map_config


def convert_btd6_instructions_file(filename: str, target_resolution: tuple[int, int]) -> bool:
    file_config = parse_btd6_instruction_file_name(filename)
    if not file_config:
        return False
    if not exists(filename):
        return False

    new_filename = get_btd6_instructions_file_name_by_config(file_config, resolution=create_resolution_string(target_resolution))

    if exists(new_filename):
        return False

    with open(filename, 'r') as fp:
        raw_input_file = fp.read()

    output = scale_string_coordinate_pairs(
        raw_input_file,
        [int(x) for x in file_config['resolution'].split('x')],
        target_resolution,
    )

    with open(new_filename, 'w') as fp:
        fp.write(output)

    return True


ahk = AHK()

pyautogui.FAILSAFE = False


class PlaythroughResult(Enum):
    UNDEFINED = 0
    WIN = 1
    DEFEAT = 2


class ValidatedPlaythroughs(Enum):
    EXCLUDE_NON_VALIDATED = 0
    INCLUDE_ALL = 1
    EXCLUDE_VALIDATED = 2


def user_has_monkey_knowledge(name):
    return is_monkey_knowledge_enabled and 'monkey_knowledge' in user_config and name in user_config['monkey_knowledge'] and user_config['monkey_knowledge'][name] == True


def calculate_adjusted_price(price: int, difficulty: str, gamemode: str, action: dict = None, monkey: dict = None, discount_percentage: int = None) -> int:
    discount = int(discount_percentage) / 100 if discount_percentage and str(discount_percentage).isdigit() else 0
    price_reduction = 0

    difficulty_mapping = {
        'easy': 0.85,
        'medium': 1,
        'hard': 1.08,
    }

    if gamemode == 'impoppable':
        factor = 1.2
    elif difficulty in difficulty_mapping:  # TODO: find out if check is necessary
        factor = difficulty_mapping[difficulty]

    additional_factor = 1

    if gamemode != 'chimps' and monkey and action and action['action'] == 'place':
        if monkey['type'] == 'hero' and user_has_monkey_knowledge('hero_favors'):
            additional_factor = 0.9
        if monkey['type'] == 'spike' and monkey['name'] == 'spike0' and user_has_monkey_knowledge('first_last_line_of_defense'):
            price_reduction += 150

    return round(price * (1 - discount) * factor * additional_factor / 5) * 5 - price_reduction


def get_monkey_sell_value(cost):
    return round(cost * 0.7)


# reads a playthrough file, converts it and saves the converted file under the same name in own_playthroughs(except changed resolution)
def get_monkey_upgrade_requirements(monkeys):
    monkey_upgrade_requirements = {}
    for monkey in monkeys:
        if monkeys[monkey]['type'] == 'hero':
            continue
        if monkeys[monkey]['type'] not in monkey_upgrade_requirements:
            monkey_upgrade_requirements[monkeys[monkey]['type']] = np.array(monkeys[monkey]['upgrades'])
        else:
            monkey_upgrade_requirements[monkeys[monkey]['type']] = np.maximum(
                monkey_upgrade_requirements[monkeys[monkey]['type']],
                np.array(monkeys[monkey]['upgrades']),
            )
    for monkey in monkey_upgrade_requirements:
        monkey_upgrade_requirements[monkey] = monkey_upgrade_requirements[monkey].tolist()
    return monkey_upgrade_requirements


def monkey_upgrades_to_string(upgrades):
    return str(upgrades[0]) + '-' + str(upgrades[1]) + '-' + str(upgrades[2])


def get_had_defeats(playthrough, playthrough_log):
    if playthrough['filename'] not in playthrough_log or playthrough['gamemode'] not in playthrough_log[playthrough['filename']]:
        return False
    return playthrough_log[playthrough['filename']][playthrough['gamemode']]['defeats'] > 0


def get_average_playthrough_time(playthrough):
    if playthrough['filename'] not in playthrough_stats:
        return -1

    times = []
    for resolution in playthrough_stats[playthrough['filename']]:
        if not re.search(r'\d+x\d+', resolution):
            continue
        if playthrough['gamemode'] in playthrough_stats[playthrough['filename']][resolution]:
            times = [
                *times,
                *playthrough_stats[playthrough['filename']][resolution][playthrough['gamemode']]['win_times'],
            ]
    return np.average(times or [-1])


def get_highest_value_playthrough(all_available_playthroughs, map_name, playthrough_log, prefer_no_mk=True):
    highest_value_playthrough = None
    highest_value_playthrough_value = 0
    highest_value_playthrough_time = -1
    highest_value_no_defeats_playthrough = None
    highest_value_no_defeats_playthrough_value = 0
    highest_value_no_defeats_playthrough_time = 0

    if map_name not in all_available_playthroughs:
        return None

    for gamemode in all_available_playthroughs[map_name]:
        for playthrough in all_available_playthroughs[map_name][gamemode]:
            average_time = get_average_playthrough_time(playthrough)
            if not get_had_defeats(playthrough, playthrough_log):
                if gamemodes[gamemode]['value'] > highest_value_no_defeats_playthrough_value:
                    highest_value_no_defeats_playthrough_value = gamemodes[gamemode]['value']
                    highest_value_no_defeats_playthrough = playthrough
                    highest_value_no_defeats_playthrough_time = average_time
                elif prefer_no_mk and highest_value_no_defeats_playthrough['fileConfig']['noMK'] == False and playthrough['fileConfig']['noMK'] == True:
                    highest_value_no_defeats_playthrough_value = gamemodes[gamemode]['value']
                    highest_value_no_defeats_playthrough = playthrough
                    highest_value_no_defeats_playthrough_time = average_time
                elif (
                    (not prefer_no_mk or highest_value_no_defeats_playthrough['fileConfig']['noMK'] == playthrough['fileConfig']['noMK'] or playthrough['fileConfig']['noMK'] == True)
                    and gamemodes[gamemode]['value'] == highest_value_no_defeats_playthrough_value
                    and average_time != -1
                    and (average_time < highest_value_no_defeats_playthrough_time or highest_value_no_defeats_playthrough_time == -1)
                ):
                    highest_value_no_defeats_playthrough_value = gamemodes[gamemode]['value']
                    highest_value_no_defeats_playthrough = playthrough
                    highest_value_no_defeats_playthrough_time = average_time
            else:
                if gamemodes[gamemode]['value'] > highest_value_playthrough_value:
                    highest_value_playthrough_value = gamemodes[gamemode]['value']
                    highest_value_playthrough = playthrough
                    highest_value_playthrough_time = average_time
                elif prefer_no_mk and highest_value_playthrough['fileConfig']['noMK'] == False and playthrough['fileConfig']['noMK'] == True:
                    highest_value_playthrough_value = gamemodes[gamemode]['value']
                    highest_value_playthrough = playthrough
                    highest_value_playthrough_time = average_time
                elif (
                    (not prefer_no_mk or highest_value_playthrough['fileConfig']['noMK'] == playthrough['fileConfig']['noMK'] or playthrough['fileConfig']['noMK'] == True)
                    and gamemodes[gamemode]['value'] == highest_value_playthrough_value
                    and average_time != -1
                    and (average_time < highest_value_playthrough_time or highest_value_playthrough_time == -1)
                ):
                    highest_value_playthrough_value = gamemodes[gamemode]['value']
                    highest_value_playthrough = playthrough
                    highest_value_playthrough_time = average_time

    return highest_value_no_defeats_playthrough or highest_value_playthrough


def update_playthrough_validation_status(playthrough_file, validation_status, resolution=create_resolution_string()):
    global playthrough_stats

    if playthrough_file not in playthrough_stats:
        playthrough_stats[playthrough_file] = {}
    if resolution not in playthrough_stats[playthrough_file]:
        playthrough_stats[playthrough_file][resolution] = {'validation_result': False}

    playthrough_stats[playthrough_file][resolution]['validation_result'] = validation_status

    save_json_file('playthrough_stats.json', playthrough_stats)


def update_stats_file(playthrough_file, this_playthrough_stats, resolution=create_resolution_string()):
    global playthrough_stats

    if playthrough_file not in playthrough_stats:
        playthrough_stats[playthrough_file] = {}
    if resolution not in playthrough_stats[playthrough_file]:
        playthrough_stats[playthrough_file][resolution] = {'validation_result': False}
    if this_playthrough_stats['gamemode'] not in playthrough_stats[playthrough_file][resolution]:
        playthrough_stats[playthrough_file][resolution][this_playthrough_stats['gamemode']] = {'attempts': 0, 'wins': 0, 'win_times': []}

    if this_playthrough_stats['result'] == PlaythroughResult.WIN:
        playthrough_stats[playthrough_file][resolution][this_playthrough_stats['gamemode']]['attempts'] += 1
        playthrough_stats[playthrough_file][resolution][this_playthrough_stats['gamemode']]['wins'] += 1
        playthrough_stats[playthrough_file]['version'] = version
        total_time = 0
        last_start = -1
        for state_change in this_playthrough_stats['time']:
            if state_change[0] == 'start' and last_start == -1:
                last_start = state_change[1]
            elif state_change[0] == 'stop' and last_start != -1:
                total_time += state_change[1] - last_start
                last_start = -1
        playthrough_stats[playthrough_file][resolution][this_playthrough_stats['gamemode']]['win_times'].append(total_time)
    else:
        playthrough_stats[playthrough_file][resolution][this_playthrough_stats['gamemode']]['attempts'] += 1

    save_json_file('playthrough_stats.json', playthrough_stats)


def check_for_single_monkey_group(monkeys):
    types = list(
        filter(
            lambda x: x != '-',
            list(
                map(
                    lambda monkey: (towers['monkeys'][monkeys[monkey]['type']]['type'] if monkeys[monkey]['type'] != 'hero' else '-'),
                    monkeys,
                ),
            ),
        ),
    )

    if len(set(types)) == 1:
        return types[0]
    else:
        return None


def check_for_single_monkey_type(monkeys):
    types = list(
        filter(
            lambda x: x != 'hero',
            list(map(lambda monkey: monkeys[monkey]['type'], monkeys)),
        ),
    )

    if len(set(types)) == 1:
        return types[0]
    else:
        return None


def list_btd6_instructions_file_compatibility(filename):
    file_config = parse_btd6_instruction_file_name(filename)
    map_config = parse_btd6_instructions_file(filename)
    single_monkey_group = check_for_single_monkey_group(map_config['monkeys'])

    compatible_gamemodes = []
    if file_config['gamemode'] == 'chimps':
        compatible_gamemodes = ['hard', 'medium', 'easy']
    elif file_config['gamemode'] == 'hard':
        compatible_gamemodes = ['medium', 'easy']
    elif file_config['gamemode'] == 'medium':
        compatible_gamemodes = ['easy']
    elif file_config['gamemode'] == 'magic_monkeys_only':
        compatible_gamemodes = ['hard', 'medium', 'easy']
    elif file_config['gamemode'] == 'double_hp_moabs':
        compatible_gamemodes = ['hard', 'medium', 'easy']
    elif file_config['gamemode'] == 'half_cash':
        compatible_gamemodes = ['hard', 'medium', 'easy']
    elif file_config['gamemode'] == 'impoppable':
        compatible_gamemodes = ['hard', 'medium', 'easy']
    elif file_config['gamemode'] == 'military_only':
        compatible_gamemodes = ['medium', 'easy']
    elif file_config['gamemode'] == 'primary_only':
        compatible_gamemodes = ['easy']

    if file_config['gamemode'] in ['hard', 'double_hp_moabs', 'half_cash', 'impoppable', 'chimps'] and single_monkey_group and single_monkey_group == 'magic':
        compatible_gamemodes.append('magic_monkeys_only')
    elif file_config['gamemode'] in ['medium', 'hard', 'double_hp_moabs', 'half_cash', 'impoppable', 'chimps'] and single_monkey_group and single_monkey_group == 'military':
        compatible_gamemodes.append('military_only')
    elif (
        file_config['gamemode']
        in [
            'easy',
            'medium',
            'hard',
            'double_hp_moabs',
            'half_cash',
            'impoppable',
            'chimps',
        ]
        and single_monkey_group
        and single_monkey_group == 'primary'
    ):
        compatible_gamemodes.append('primary_only')

    compatible_gamemodes.append(file_config['gamemode'])

    return compatible_gamemodes


def check_btd6_instructions_file_compatibility(filename, gamemode):
    return gamemode in list_btd6_instructions_file_compatibility(filename)


# doesn't yet consider unlocked_monkey_upgrades
def can_user_use_playthrough(playthrough):
    if playthrough['fileConfig']['map'] not in user_config['unlocked_maps'] or not user_config['unlocked_maps'][playthrough['fileConfig']['map']]:
        return False
    map_config = parse_btd6_instructions_file(playthrough['filename'])
    return not ('hero' in map_config and (map_config['hero'] not in user_config['heroes'] or not user_config['heroes'][map_config['hero']]))


def is_medal_unlocked(map_name: str, gamemode: str) -> bool:
    return user_config['medals'].get(map_name, {}).get(gamemode, False)


def set_medal_unlocked(map_name: str, gamemode: str, is_unlocked: bool = True) -> None:
    if is_medal_unlocked(map_name, gamemode) == is_unlocked:
        return

    user_config['medals'].setdefault(map_name, {})[gamemode] = is_unlocked
    save_json_file('userconfig.json', user_config)


def can_user_access_gamemode(map_name: str, gamemode: str) -> bool:
    if map_name not in user_config['medals']:
        return False
    if gamemode in ['easy', 'medium', 'hard'] or is_medal_unlocked(map_name, gamemode):
        return True

    # TODO think about using MODE_PATHS instead of this
    mode_prerequisites: dict[str, str] = {
        'primary_only': 'easy',
        'deflation': 'primary_only',
        'easy_sandbox': 'easy',
        'military_only': 'medium',
        'apopalypse': 'military_only',
        'reverse': 'medium',
        'medium_sandbox': 'reverse',
        'hard_sandbox': 'hard',
        'magic_monkeys_only': 'hard',
        'double_hp_moabs': 'magic_monkeys_only',
        'half_cash': 'double_hp_moabs',
        'alternate_bloons_rounds': 'hard',
        'impoppable': 'alternate_bloons_rounds',
        'chimps': 'impoppable',
    }

    mode_prerequisite = mode_prerequisites.get(gamemode)
    return bool(mode_prerequisite and is_medal_unlocked(map_name, mode_prerequisite))


def is_sandbox_unlocked(map_name: str, restricted_to: list[str] | None) -> str | None:
    for gamemode in restricted_to if restricted_to else SANDBOX_GAMEMODES:
        if can_user_access_gamemode(map_name, gamemode):
            return gamemode
    return None


def get_all_available_playthroughs(additional_dirs=[], consider_user_config=False):
    playthroughs = {}
    files = []
    for dir_list in ['playthroughs', *additional_dirs]:
        if exists(dir_list):
            files = [*files, *[dir_list + '/' + x for x in os.listdir(dir_list)]]

    for filename in files:
        file_config = parse_btd6_instruction_file_name(filename)
        if consider_user_config and not can_user_use_playthrough({'filename': filename, 'fileConfig': file_config}):
            continue
        if file_config['map'] not in playthroughs:
            playthroughs[file_config['map']] = {}
        compatible_gamemodes = list_btd6_instructions_file_compatibility(filename)
        for gamemode in compatible_gamemodes:
            if consider_user_config and not can_user_access_gamemode(file_config['map'], gamemode):
                continue
            if gamemode not in playthroughs[file_config['map']]:
                playthroughs[file_config['map']][gamemode] = []
            playthroughs[file_config['map']][gamemode].append(
                {
                    'filename': filename,
                    'fileConfig': file_config,
                    'gamemode': gamemode,
                    'isOriginalGamemode': gamemode == file_config['gamemode'],
                },
            )

    return playthroughs


def filter_all_available_playthroughs(
    playthroughs,
    monkey_knowledge_enabled,
    handle_playthrough_validation,
    category_restriction,
    gamemode_restriction,
    hero_whitelist=None,
    required_flags=None,
    only_original_gamemodes=False,
    resolution=create_resolution_string(),
):
    filtered_playthroughs = {}

    for map_name in playthroughs:
        if category_restriction and maps[map_name]['category'] != category_restriction:
            continue
        for gamemode in playthroughs[map_name]:
            if gamemode_restriction and gamemode != gamemode_restriction:
                continue
            for playthrough in playthroughs[map_name][gamemode]:
                if playthrough['fileConfig']['noMK'] == False and monkey_knowledge_enabled == False:
                    continue
                if hero_whitelist:
                    map_config = parse_btd6_instructions_file(playthrough['filename'])
                    if 'hero' in map_config and map_config['hero'] not in hero_whitelist:
                        continue
                if required_flags and not all([x in playthrough['fileConfig'] for x in required_flags]):
                    continue
                if only_original_gamemodes and not playthrough['isOriginalGamemode']:
                    continue
                if handle_playthrough_validation != ValidatedPlaythroughs.INCLUDE_ALL and (
                    (
                        handle_playthrough_validation == ValidatedPlaythroughs.EXCLUDE_NON_VALIDATED
                        and (playthrough['filename'] not in playthrough_stats or resolution not in playthrough_stats[playthrough['filename']] or 'validation_result' not in playthrough_stats[playthrough['filename']][resolution] or playthrough_stats[playthrough['filename']][resolution]['validation_result'] == False)
                    )
                    or (
                        handle_playthrough_validation == ValidatedPlaythroughs.EXCLUDE_VALIDATED
                        and (playthrough['filename'] in playthrough_stats and resolution in playthrough_stats[playthrough['filename']] and 'validation_result' in playthrough_stats[playthrough['filename']][resolution] and playthrough_stats[playthrough['filename']][resolution]['validation_result'] == True)
                    )
                ):
                    continue
                if map_name not in filtered_playthroughs:
                    filtered_playthroughs[map_name] = {}
                if gamemode not in filtered_playthroughs[map_name]:
                    filtered_playthroughs[map_name][gamemode] = []
                filtered_playthroughs[map_name][gamemode].append(playthrough)

    return filtered_playthroughs


def playthroughs_to_list(playthroughs):
    playthroughs_list = []
    for map_name in playthroughs:
        for gamemode in playthroughs[map_name]:
            for playthrough in playthroughs[map_name][gamemode]:
                playthroughs_list.append(playthrough)

    return playthroughs_list


# TODO: freeplay xp gain
# "Upon reaching freeplay mode, you gain 30% of the normal XP, and after round 100 (if on freeplay mode), 10% of the normal XP, although heroes will not be affected by the cut at this point."
def get_round_total_base_xp(round_no: int) -> int:
    segments: list[tuple[int, int, int, int]] = [
        (0, 21, 0, 20),
        (21, 30, 21 * 20, 40),
        (51, 50, 21 * 20 + 30 * 40, 90),
    ]

    xp = 0
    for start, length, base, inc in segments:
        count = max(0, min(round_no - start + 1, length))
        xp += base * count + inc * (count * (count + 1) // 2)

    return xp


def get_playthrough_xp(gamemode: str, map_category: str) -> int:
    first_round, final_round = {
        **dict.fromkeys(['easy', 'primary_only'], (0, 40)),
        **dict.fromkeys(['medium', 'military_only', 'reverse', 'apopalypse'], (0, 60)),
        **dict.fromkeys(['hard', 'magic_monkeys_only', 'double_hp_moabs', 'half_cash', 'alternate_bloons_rounds'], (2, 80)),
        **dict.fromkeys(['impoppable', 'chimps'], (5, 100)),
        'deflation': (30, 60),
    }.get(gamemode, (0, 0))

    total_xp = get_round_total_base_xp(final_round) - get_round_total_base_xp(first_round)

    difficulty_multiplier = {'intermediate': 1.1, 'advanced': 1.2, 'expert': 1.3}.get(map_category, 1.0)
    return int(total_xp * difficulty_multiplier)


def get_playthrough_monkey_money(gamemode, map_category):
    if gamemode not in gamemodes:
        return 0

    replay_monkey_money = {
        'easy': {'beginner': 15, 'intermediate': 30, 'advanced': 45, 'expert': 60},
        'medium': {'beginner': 25, 'intermediate': 50, 'advanced': 75, 'expert': 100},
        'hard': {'beginner': 40, 'intermediate': 80, 'advanced': 120, 'expert': 160},
        'impoppable': {
            'beginner': 60,
            'intermediate': 120,
            'advanced': 180,
            'expert': 240,
        },
    }

    if map_category not in replay_monkey_money['easy']:
        return 0

    return replay_monkey_money[gamemodes[gamemode]['cash_group']][map_category]


def get_playthrough_xp_per_hour(playthrough):
    average_time = get_average_playthrough_time(playthrough)
    if average_time == -1:
        return 0
    return 3600 / average_time * get_playthrough_xp(playthrough['gamemode'], maps[playthrough['fileConfig']['map']]['category'])


def get_playthrough_monkey_money_per_hour(playthrough):
    average_time = get_average_playthrough_time(playthrough)
    if average_time == -1:
        return 0
    return 3600 / average_time * get_playthrough_monkey_money(playthrough['gamemode'], maps[playthrough['fileConfig']['map']]['category'])


def sort_playthroughs_by_gain(playthroughs, gain_func):
    return sorted(
        map(lambda x: {**x, 'value': gain_func(x)}, playthroughs),
        key=lambda x: x['value'],
        reverse=True,
    )


def sort_playthroughs_by_monkey_money_gain(playthroughs):
    return sort_playthroughs_by_gain(playthroughs, get_playthrough_monkey_money_per_hour)


def sort_playthroughs_by_xp_gain(playthroughs):
    return sort_playthroughs_by_gain(playthroughs, get_playthrough_xp_per_hour)


def find_map_for_px_pos(category, page, px_pos):
    if category not in maps_by_pos or page not in maps_by_pos[category]:
        return None
    best_find = None
    best_find_dist = 100000
    for i_tmp in maps_by_pos[category][page]:
        map_name = maps_by_pos[category][page][i_tmp]
        pos = image_areas['click']['map_positions'][maps[map_name]['pos']]
        if pos[0] < px_pos[0] and pos[1] < px_pos[1]:
            dist = math.dist(pos, px_pos)
            if dist < best_find_dist:
                best_find = map_name
                best_find_dist = dist
    return best_find


# TODO: refactor to some kind of config class etc.
is_monkey_knowledge_enabled = False


def set_monkey_knowledge_enabled(enabled: bool):
    global is_monkey_knowledge_enabled
    is_monkey_knowledge_enabled = enabled


def get_monkey_knowledge_enabled() -> bool:
    return is_monkey_knowledge_enabled


def map_name_to_key_name(map_name: str) -> str:
    return map_name.translate(str.maketrans('', '', "'#")).replace(' ', '_').lower()


def maps_by_category_to_map_list(maps_by_category: dict[str, list[str]], maps: dict[str, dict]) -> dict[str, dict]:
    """
    Converts a dictionary of map categories to a flat dictionary of map details with pagination.

    Groups maps into pages of six. After every six maps, it resets the position counter to zero
    and increments the page counter.
    """
    new_maps = {}
    for category in maps_by_category:
        current_pos = 0
        current_page = 0
        for map_name in maps_by_category[category]:
            new_maps[map_name] = {
                'category': category,
                'name': maps[map_name]['name'],
                'page': current_page,
                'pos': current_pos,
            }
            current_pos += 1
            if current_pos >= 6:
                current_pos = 0
                current_page += 1
    return new_maps


def upgrade_requires_confirmation(monkey, path):
    if 'upgrade_confirmation' not in towers['monkeys'][monkey['type']]:
        return False
    if monkey['upgrades'][path] - 1 == -1:
        return False
    if monkey['upgrades'][path] - 1 >= 5:  # paragons
        return True
    return towers['monkeys'][monkey['type']]['upgrade_confirmation'][path][monkey['upgrades'][path] - 1]


def is_btd6_window(name):
    return name in ['BloonsTD6', 'BloonsTD6-Epic']


def get_ingame_ocr_segments(map_config: dict) -> dict:
    segment_coordinates = copy.deepcopy(image_areas['ocr_segments'])

    if map_config['gamemode'] in ['impoppable', 'chimps']:
        segment_coordinates['round'] = segment_coordinates['round_ge100_rounds']

    return {
        'lives': segment_coordinates['lives'],
        'mana_lives': segment_coordinates['mana_lives'],
        'money': segment_coordinates['money'],
        'round': segment_coordinates['round'],
    }


with open('version.txt') as fp:
    version = float(fp.read())

names = ['maps', 'gamemodes', 'keybinds', 'towers', 'image_areas']
loaded = []
for name in names:
    loaded.append(load_json_file(f'{name}.json'))
maps, gamemodes, keybinds, towers, all_image_areas = loaded

if create_resolution_string() in all_image_areas:
    image_areas = all_image_areas[create_resolution_string()]
else:
    image_areas = json.loads(scale_string_coordinate_pairs(json.dumps(all_image_areas['2560x1440']), (2560, 1440), pyautogui.size()))

playthrough_stats = load_json_file('playthrough_stats.json')

user_config = {
    'monkey_knowledge': {},
    'heroes': {},
    'unlocked_maps': {},
    'unlocked_monkey_upgrades': {},
}

user_config = load_json_file('userconfig.json', check_exists=True, default=user_config)

maps_by_category = {}
for map_name in maps:
    if maps[map_name]['category'] not in maps_by_category:
        maps_by_category[maps[map_name]['category']] = []
    maps_by_category[maps[map_name]['category']].append(map_name)

maps_by_pos = {}
for map_name in maps:
    if maps[map_name]['category'] not in maps_by_pos:
        maps_by_pos[maps[map_name]['category']] = {}
    if maps[map_name]['page'] not in maps_by_pos[maps[map_name]['category']]:
        maps_by_pos[maps[map_name]['category']][maps[map_name]['page']] = {}
    maps_by_pos[maps[map_name]['category']][maps[map_name]['page']][maps[map_name]['pos']] = map_name


category_pages = {}
for category in maps_by_category:
    category_pages[category] = max(map(lambda x: maps[x]['page'], maps_by_category[category])) + 1
