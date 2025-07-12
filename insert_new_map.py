import copy
import json
import sys

from helper import map_name_to_key_name, maps, maps_by_category, maps_by_category_to_map_list, user_config
from utils.utils import save_json_file

if len(sys.argv) < 4 or sys.argv[2] not in ['before', 'after']:
    print(
        f'Usage: py {sys.argv[0]} "<name of the new map>" <before|after> "<name of adjacent map>"',
    )
    exit()

next_map = sys.argv[3]
next_map_key = map_name_to_key_name(next_map)
new_map = sys.argv[1]
new_map_key = map_name_to_key_name(new_map)
insert_pos_offset = 0 if sys.argv[2] == 'before' else 1

if next_map_key not in maps:
    print(f'Unknown map: {next_map}')
    exit()
if new_map_key in maps:
    print('New map already inserted!')
    exit()

maps_by_category[maps[next_map_key]['category']].insert(
    maps_by_category[maps[next_map_key]['category']].index(next_map_key) + insert_pos_offset,
    new_map_key,
)
maps[new_map_key] = {'name': new_map}

new_maps = maps_by_category_to_map_list(maps_by_category, maps)

new_maps_tmp = {}

for i, map_name in enumerate(new_maps):
    new_maps_tmp[map_name] = f'%placeholder{i}%'

output = json.dumps(new_maps_tmp, indent=4)

for i, map_name in enumerate(new_maps):
    output = output.replace(f'"%placeholder{i}%"', json.dumps(new_maps[map_name]))

with open('maps.json', 'w') as fp:
    fp.write(output)

print('"maps.json" successfully updated')

new_user_config = copy.deepcopy(user_config)

if new_map_key not in new_user_config['unlocked_maps']:
    pos = list(new_user_config['unlocked_maps'].keys()).index(next_map_key)
    items = list(new_user_config['unlocked_maps'].items())
    items.insert(pos, (new_map_key, True))
    new_user_config['unlocked_maps'] = dict(items)

if new_map_key not in new_user_config['medals']:
    pos = list(new_user_config['medals'].keys()).index(next_map_key)
    items = list(new_user_config['medals'].items())
    items.insert(
        pos,
        (
            new_map_key,
            {
                'easy': True,
                'primary_only': True,
                'deflation': True,
                'medium': True,
                'military_only': True,
                'reverse': True,
                'apopalypse': True,
                'hard': True,
                'magic_monkeys_only': True,
                'double_hp_moabs': True,
                'half_cash': True,
                'alternate_bloons_rounds': True,
                'impoppable': True,
                'chimps': True,
            },
        ),
    )
    new_user_config['medals'] = dict(items)

save_json_file('userconfig.json', new_user_config)

print('"userconfig.json" successfully updated')
