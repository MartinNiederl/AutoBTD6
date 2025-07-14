from enum import Enum

from pydantic import BaseModel, Field


# TODO: this enum is only here for usage in code and has nothing to do with the config itself
class Medal(str, Enum):
    easy = 'easy'
    primary_only = 'primary_only'
    deflation = 'deflation'
    medium = 'medium'
    military_only = 'military_only'
    reverse = 'reverse'
    apopalypse = 'apopalypse'
    hard = 'hard'
    magic_monkeys_only = 'magic_monkeys_only'
    double_hp_moabs = 'double_hp_moabs'
    half_cash = 'half_cash'
    alternate_bloons_rounds = 'alternate_bloons_rounds'
    impoppable = 'impoppable'
    chimps = 'chimps'


class MapMedals(BaseModel):
    easy: bool
    primary_only: bool
    deflation: bool
    medium: bool
    military_only: bool
    reverse: bool
    apopalypse: bool
    hard: bool
    magic_monkeys_only: bool
    double_hp_moabs: bool
    half_cash: bool
    alternate_bloons_rounds: bool
    impoppable: bool
    chimps: bool


class UserConfig(BaseModel):
    monkey_knowledge: dict[str, bool]
    heroes: dict[str, bool] = Field(..., alias='heros')  # this is a typo in the original code
    unlocked_maps: dict[str, bool]
    unlocked_monkey_upgrades: dict[str, list[int]]
    medals: dict[str, MapMedals]


if __name__ == '__main__':
    with open('userconfig.json', encoding='utf-8') as f:
        data = f.read()

    profile = UserConfig.model_validate_json(data, strict=True)
    print(profile.medals['monkey_meadow'].chimps)
