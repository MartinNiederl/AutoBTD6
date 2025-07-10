import re
from urllib.parse import quote_plus

from helper import (
    checkForSingleMonkeyGroup,
    checkForSingleMonkeyType,
    gamemodes,
    getAllAvailablePlaythroughs,
    getMonkeyUpgradeRequirements,
    maps,
    monkeyUpgradesToString,
    parseBTD6InstructionsFile,
    playthroughStats,
)

extra_comments = {
    'playthroughs/spice_islands#alternate_bloons_rounds#2560x1440#noMK#noWaterTowers.btd6': [
        'no water towers(achievement)',
    ],
}

map_comments = {
    'geared': 'changing monkey positions (1)',
    'sanctuary': 'changing monkey positions (1)',
    'covered_garden': 'positions and monkeys not always accessible (2)',
}

output = ''
output += '<table border=1 style="border-collapse: collapse">' + '\n'
output += '\t<tr>' + '\n'
output += '\t\t<th>Map</th>' + '\n'
output += '\t\t<th>Category</th>' + '\n'

for gamemode in gamemodes:
    output += '\t\t<th>' + gamemodes[gamemode]['name'] + '</th>' + '\n'

output += '\t\t<th>Comment</th>' + '\n'
output += '\t</tr>' + '\n'

playthroughs = getAllAvailablePlaythroughs()

maps_by_category = {}

for map_name in maps:
    if maps[map_name]['category'] not in maps_by_category:
        maps_by_category[maps[map_name]['category']] = []
    maps_by_category[maps[map_name]['category']].append((map_name, maps[map_name]))

for category in maps_by_category:
    first_row = True
    for map_data in maps_by_category[category]:
        map_name = map_data[0]
        map_data = map_data[1]
        if first_row:
            output += '\t<tr style="border-top: 2px solid white">' + '\n'
            output += '\t<th>' + map_data['name'] + '</th>' + '\n'
            output += '\t<td rowspan=' + str(len(maps_by_category[category])) + '>' + category + '</th>' + '\n'
            first_row = False
        else:
            output += '\t<tr>' + '\n'
            output += '\t<th>' + map_data['name'] + '</th>' + '\n'

        for gamemode in gamemodes:
            output += '\t\t<td>'
            first_playthrough_row = True
            for playthrough in (playthroughs.get(map_name, {})).get(gamemode, []):
                no_MK = False  # noqa: N816
                no_LL = False  # noqa: N816
                no_LLwMK = False  # noqa: N816
                for m in re.finditer(
                    '(?P<noMK>noMK(?:#|$))?(?:(?P<singleType>[a-z]+)Only(?:#|$))?(?P<noLL>noLL(?:#|$))?(?P<noLLwMK>noLLwMK(?:#|$))?',
                    (playthrough['fileConfig']['comment'] if 'comment' in playthrough['fileConfig'] and playthrough['fileConfig']['comment'] else ''),
                ):
                    if m.group('noMK'):
                        no_MK = True  # noqa: N816
                    if m.group('noLL'):
                        no_LL = True  # noqa: N816
                    if m.group('noLLwMK'):
                        no_LLwMK = True  # noqa: N816
                description = ''
                if no_MK:
                    description += 'supported'
                else:
                    description += 'with MK'

                map_config = parseBTD6InstructionsFile(playthrough['filename'])

                if 'hero' in map_config:
                    description += ', ' + ' '.join(
                        [w.capitalize() for w in map_config['hero'].split(' ')],
                    )
                else:
                    description += ', -'

                single_type = checkForSingleMonkeyType(map_config['monkeys'])
                if single_type:
                    description += ', ' + single_type + ' only'
                single_group = checkForSingleMonkeyGroup(map_config['monkeys'])
                if single_group:
                    description += ', ' + single_group + ' monkeys only'

                if no_LL:
                    pass
                elif no_LLwMK:
                    description += ', (*)'
                else:
                    description += ', *'

                if playthrough['filename'] in extra_comments:
                    for extra_comment in extra_comments[playthrough['filename']]:
                        description += ', ' + extra_comment

                description += (
                    ', native: '
                    + playthrough['fileConfig']['resolution']
                    + (
                        ', tested for: '
                        + ', '.join(
                            filter(
                                lambda x: type(
                                    playthroughStats[playthrough['filename']][x],
                                )
                                is dict
                                and 'validation_result' in playthroughStats[playthrough['filename']][x]
                                and playthroughStats[playthrough['filename']][x]['validation_result'] == True,
                                playthroughStats[playthrough['filename']].keys(),
                            ),
                        )
                        if playthrough['filename'] in playthroughStats
                        and len(playthroughStats[playthrough['filename']].keys())
                        and len(
                            list(
                                filter(
                                    lambda x: type(
                                        playthroughStats[playthrough['filename']][x],
                                    )
                                    is dict
                                    and 'validation_result' in playthroughStats[playthrough['filename']][x]
                                    and playthroughStats[playthrough['filename']][x]['validation_result'] == True,
                                    playthroughStats[playthrough['filename']].keys(),
                                ),
                            ),
                        )
                        else ''
                    )
                )

                title = ''
                monkey_upgrade_requirements = getMonkeyUpgradeRequirements(
                    map_config['monkeys'],
                )
                for monkey in monkey_upgrade_requirements:
                    if len(title):
                        title += ', '
                    title += monkey + '(' + monkeyUpgradesToString(monkey_upgrade_requirements[monkey]) + ')'

                if first_playthrough_row:
                    first_playthrough_row = False
                else:
                    output += '<br><br>'
                output += '<a href="' + quote_plus(playthrough['filename']) + '"' + (' title="required monkeys: ' + title + '"' if len(title) else '') + '>' + ('<i>' + description + '</i>' if not playthrough['isOriginalGamemode'] else description) + '</a>'
            output += '</td>' + '\n'

        if map_name in map_comments:
            output += '\t\t<td>' + map_comments[map_name] + '</td>' + '\n'
        else:
            output += '\t\t<td></td>' + '\n'
        output += '\t</tr>' + '\n'

output += '</table>' + '\n'

with open('README.md') as fp:
    old_README = fp.read()  # noqa: N816

output = re.sub(
    '<div id="supported_maps">.*?<\\/div>',
    '<div id="supported_maps">\n' + output + '</div>',
    old_README,
    1,
    re.DOTALL,
)

if output == old_README:
    print('README identical after replacement')
else:
    with open('README.md', 'w') as fp:
        fp.write(output)
