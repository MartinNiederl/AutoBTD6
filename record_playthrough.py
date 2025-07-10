import math
import signal
import sys
import time
from os.path import exists

import ahk
import keyboard
import numpy as np
import pyautogui

# TODO: refactor this atrocity
from helper import (
    gamemodes,
    getBTD6InstructionsFileNameByConfig,
    isBTD6Window,
    keybinds,
    maps,
    parseBTD6InstructionsFile,
    towers,
    tupleToStr,
    writeBTD6InstructionsFile,
)

monkeys_by_type_count = {'hero': 0}

for monkey_type in keybinds['monkeys']:
    monkeys_by_type_count[monkey_type] = 0

selected_monkey = None
monkeys = {}
config = {'steps': []}


def get_closest_monkey(pos: tuple[int, int]) -> dict:
    closest_monkey = None
    closest_dist = 10000
    dist = None
    for monkey in monkeys:
        dist = math.dist(pos, monkeys[monkey]['pos'])
        if dist < closest_dist:
            closest_monkey = monkeys[monkey]
            closest_dist = dist

    print('selected monkey: ' + (closest_monkey['name'] or ''))
    return {'monkey': closest_monkey, 'dist': closest_dist}


def signal_handler(signum, frame):
    keyboard.unhook_all()
    print('stopping recording!')
    writeBTD6InstructionsFile(config)
    sys.exit(0)


def on_recording_event(e):
    global selected_monkey
    global config
    global monkeys
    global monkeys_by_type_count

    pos = pyautogui.position()

    active_window = ahk.get_active_window()
    if not active_window or not isBTD6Window(active_window.title):
        print('BTD6 not focused')
        return
    if not pyautogui.onScreen(pos):
        print(tupleToStr(pos) + ' not on screen')
        return
    if e['action'] == 'select_monkey':
        selected_monkey = get_closest_monkey(pos)['monkey']
    elif e['action'] == 'remove_obstacle':
        config['steps'].append({'action': 'remove', 'pos': pos})
        print('remove obstacle at ' + tupleToStr(pos) + ' for ???')
    elif e['action'] == 'retarget':
        if selected_monkey is None:
            print('selectedMonkey unassigned!')
            return
        step = {'action': 'retarget', 'name': selected_monkey['name']}
        if keyboard.is_pressed('space'):
            step['to'] = pos
            print('retarget ' + selected_monkey['name'] + ' to ' + tupleToStr(pos))
        elif selected_monkey['type'] == 'mortar':
            print('mortar can only be retargeted to a position(tab + space)!')
            return
        else:
            print('retarget ' + selected_monkey['name'])
        config['steps'].append(step)
    elif e['action'] == 'monkey_special':
        if selected_monkey is None:
            print('selectedMonkey unassigned!')
            return
        config['steps'].append({'action': 'special', 'name': selected_monkey['name']})
        print('special ' + selected_monkey['name'])
    elif e['action'] == 'sell':
        if selected_monkey is None:
            print('selectedMonkey unassigned!')
            return
        config['steps'].append({'action': 'sell', 'name': selected_monkey['name']})
        print('sell ' + selected_monkey['name'])
        monkeys.pop(selected_monkey['name'])
        selected_monkey = None
    elif e['action'] == 'place' and e['type'] == 'hero':
        monkey_name = 'hero' + str(monkeys_by_type_count['hero'])
        config['steps'].append({'action': 'place', 'type': 'hero', 'name': monkey_name, 'pos': pos})
        print('place ' + config['hero'] + ' ' + monkey_name + ' at ' + tupleToStr(pos))
        monkeys_by_type_count['hero'] += 1
        monkeys[monkey_name] = {'name': monkey_name, 'type': config['hero'], 'pos': pos}
    elif e['action'] == 'place':
        monkey_name = e['type'] + str(monkeys_by_type_count[e['type']])
        config['steps'].append({'action': 'place', 'type': e['type'], 'name': monkey_name, 'pos': pos})
        print('place ' + e['type'] + ' ' + monkey_name + ' ' + tupleToStr(pos))
        monkeys_by_type_count[e['type']] += 1
        monkeys[monkey_name] = {'name': monkey_name, 'type': e['type'], 'pos': pos}
        selected_monkey = get_closest_monkey(pos)['monkey']
    elif e['action'] == 'upgrade':
        if selected_monkey is None:
            print('selectedMonkey unassigned!')
            return
        config['steps'].append({'action': 'upgrade', 'name': selected_monkey['name'], 'path': e['path']})
        print('upgrade ' + selected_monkey['name'] + ' path ' + e['path'])
    elif e['action'] == 'await_round':
        e['round'] = input('wait for round: ')
        try:
            e['round'] = int(e['round'])
            if e['round'] > 0 and not any((x['action'] == 'await_round' and x['round'] >= e['round']) for x in config['steps']):
                config['steps'].append({'action': 'await_round', 'round': e['round']})
                print('await round ' + str(e['round']))
                return
        except ValueError:
            pass
        print('invalid round! aborting entry!')


while True:
    print('map name > ')
    config['map'] = input().replace(' ', '_').lower()
    if config['map'] in maps:
        break
    else:
        print('unknown map!')

while True:
    print('gamemode > ')
    config['gamemode'] = input().replace(' ', '_').lower()
    if config['gamemode'] in gamemodes:
        break
    else:
        print('unknown gamemode!')

while True:
    print('hero > ')
    config['hero'] = input().replace(' ', '_').lower()
    if config['hero'] in towers['heroes']:
        break
    else:
        print('unknown hero!')

filename = getBTD6InstructionsFileNameByConfig(config)

argv = np.array(sys.argv)

extending = False

if len(np.where(argv == '-e')[0]):
    print('extending upon existing file')
    if not exists(filename):
        print('requested extending of file, but file not existing!')
        exit()
    extending = True
    new_config = parseBTD6InstructionsFile(filename)
    config['steps'] = new_config['steps']
    monkeys = new_config['monkeys']

    for monkey_name in monkeys:
        monkeys_by_type_count[monkeys[monkey_name]['type']] += 1

if not extending and exists(filename):
    print('run for selected config already existing! rename or delete "' + filename + '" if you want to record again!')
    exit()

print('started recording to "' + filename + '"')

signal.signal(signal.SIGINT, signal_handler)

# filtering on all key presses doesn't work as the provided key name is localized
# keyboard.hook(onKeyPress)

keyboard.on_press_key(
    keybinds['monkeys']['dart'],
    lambda e: on_recording_event({'action': 'place', 'type': 'dart'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['boomerang'],
    lambda e: on_recording_event({'action': 'place', 'type': 'boomerang'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['bomb'],
    lambda e: on_recording_event({'action': 'place', 'type': 'bomb'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['tack'],
    lambda e: on_recording_event({'action': 'place', 'type': 'tack'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['ice'],
    lambda e: on_recording_event({'action': 'place', 'type': 'ice'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['glue'],
    lambda e: on_recording_event({'action': 'place', 'type': 'glue'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['sniper'],
    lambda e: on_recording_event({'action': 'place', 'type': 'sniper'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['sub'],
    lambda e: on_recording_event({'action': 'place', 'type': 'sub'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['buccaneer'],
    lambda e: on_recording_event({'action': 'place', 'type': 'buccaneer'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['ace'],
    lambda e: on_recording_event({'action': 'place', 'type': 'ace'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['heli'],
    lambda e: on_recording_event({'action': 'place', 'type': 'heli'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['mortar'],
    lambda e: on_recording_event({'action': 'place', 'type': 'mortar'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['dartling'],
    lambda e: on_recording_event({'action': 'place', 'type': 'dartling'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['wizard'],
    lambda e: on_recording_event({'action': 'place', 'type': 'wizard'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['super'],
    lambda e: on_recording_event({'action': 'place', 'type': 'super'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['ninja'],
    lambda e: on_recording_event({'action': 'place', 'type': 'ninja'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['alchemist'],
    lambda e: on_recording_event({'action': 'place', 'type': 'alchemist'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['druid'],
    lambda e: on_recording_event({'action': 'place', 'type': 'druid'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['farm'],
    lambda e: on_recording_event({'action': 'place', 'type': 'farm'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['engineer'],
    lambda e: on_recording_event({'action': 'place', 'type': 'engineer'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['spike'],
    lambda e: on_recording_event({'action': 'place', 'type': 'spike'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['village'],
    lambda e: on_recording_event({'action': 'place', 'type': 'village'}),
)
keyboard.on_press_key(
    keybinds['monkeys']['hero'],
    lambda e: on_recording_event({'action': 'place', 'type': 'hero'}),
)

keyboard.on_press_key(
    keybinds['path']['0'],
    lambda e: on_recording_event({'action': 'upgrade', 'path': '0'}),
)
keyboard.on_press_key(
    keybinds['path']['1'],
    lambda e: on_recording_event({'action': 'upgrade', 'path': '1'}),
)
keyboard.on_press_key(
    keybinds['path']['2'],
    lambda e: on_recording_event({'action': 'upgrade', 'path': '2'}),
)

keyboard.on_press_key(
    keybinds['recording']['select_monkey'],
    lambda e: on_recording_event({'action': 'select_monkey'}),
)
keyboard.on_press_key(
    keybinds['recording']['remove_obstacle'],
    lambda e: on_recording_event({'action': 'remove_obstacle'}),
)
keyboard.on_press_key(
    keybinds['recording']['retarget'],
    lambda e: on_recording_event({'action': 'retarget'}),
)
keyboard.on_press_key(keybinds['recording']['sell'], lambda e: on_recording_event({'action': 'sell'}))
keyboard.on_press_key(
    keybinds['recording']['monkey_special'],
    lambda e: on_recording_event({'action': 'monkey_special'}),
)
keyboard.on_press_key(
    keybinds['recording']['await_round'],
    lambda e: on_recording_event({'action': 'await_round', 'round': '0'}),
)

while True:
    time.sleep(60)
