MODE_PATHS = {
    'easy': [
        ['primary_only', 'deflation'],
        ['easy_sandbox'],
    ],
    'medium': [
        ['military_only', 'apopalypse'],
        ['reverse', 'medium_sandbox'],
    ],
    'hard': [
        ['magic_monkeys_only', 'double_hp_moabs', 'half_cash', 'alternate_bloons_rounds'],
        ['hard_sandbox'],
    ],
}

SANDBOX_GAMEMODES = {
    'easy_sandbox': {'group': 'easy'},
    'medium_sandbox': {'group': 'medium'},
    'hard_sandbox': {'group': 'hard'},
}

# TODO: think about getting from json files instead (or enum)
MONKEYS = [
    'dart',
    'boomerang',
    'bomb',
    'tack',
    'ice',
    'glue',
    'sniper',
    'sub',
    'buccaneer',
    'ace',
    'heli',
    'mortar',
    'dartling',
    'wizard',
    'super',
    'ninja',
    'alchemist',
    'druid',
    'farm',
    'engineer',
    'spike',
    'village',
    'hero',
]

PATHS = [0, 1, 2]
