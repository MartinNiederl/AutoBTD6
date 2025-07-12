import os
import re
from os.path import exists

import pyautogui

from consts import SANDBOX_GAMEMODES
from helper import calculate_adjusted_price, gamemodes, get_monkey_sell_value, image_areas, keybinds, maps, towers, upgrade_requires_confirmation
from utils.utils import create_resolution_string, custom_print, scale_string_coordinate_pairs, tuple_to_str


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
