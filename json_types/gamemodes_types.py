from enum import Enum

from pydantic import BaseModel


class DifficultyGroup(str, Enum):
    easy = 'easy'
    medium = 'medium'
    hard = 'hard'


class CashGroup(str, Enum):
    easy = 'easy'
    medium = 'medium'
    hard = 'hard'
    impoppable = 'impoppable'


class GamemodeModel(BaseModel):
    group: DifficultyGroup
    """Difficulty group of the gamemode."""
    cash_group: CashGroup
    """Cash group determining the money earned per bloon."""
    name: str
    """Display name of the gamemode."""
    value: int
    """Difficulty value of the gamemode."""


class Gamemodes(BaseModel):
    easy: GamemodeModel
    primary_only: GamemodeModel
    deflation: GamemodeModel
    medium: GamemodeModel
    military_only: GamemodeModel
    reverse: GamemodeModel
    apopalypse: GamemodeModel
    hard: GamemodeModel
    magic_monkeys_only: GamemodeModel
    double_hp_moabs: GamemodeModel
    half_cash: GamemodeModel
    alternate_bloons_rounds: GamemodeModel
    impoppable: GamemodeModel
    chimps: GamemodeModel


if __name__ == '__main__':
    with open('gamemodes.json', 'r', encoding='utf-8') as f:
        data = f.read()

    gamemodes_data = Gamemodes.model_validate_json(data, strict=True)
    print(gamemodes_data.easy.name)
    print(gamemodes_data.chimps.cash_group)
