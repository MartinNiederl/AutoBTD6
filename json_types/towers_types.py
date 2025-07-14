from enum import Enum

from pydantic import BaseModel, Field

UpgradeCosts = tuple[int, int, int, int, int]
UpgradePathCosts = tuple[UpgradeCosts, UpgradeCosts, UpgradeCosts]

UpgradeConfirmations = tuple[bool, bool, bool, bool, bool]
UpgradePathConfirmations = tuple[UpgradeConfirmations, UpgradeConfirmations, UpgradeConfirmations]


class MonkeyType(str, Enum):
    primary = 'primary'
    military = 'military'
    magic = 'magic'
    support = 'support'


class MonkeyClass(str, Enum):
    land = 'land'
    water = 'water'
    any = 'any'


class MonkeyCostModel(BaseModel):
    base: int
    """Base cost of the monkey."""
    type: MonkeyType
    """Type of the monkey, e.g., primary, military, magic, or support."""
    class_: MonkeyClass = Field(..., alias='class')
    """Class of the monkey, e.g. land, water, or any."""
    upgrades: UpgradePathCosts
    """Costs for each upgrade path, each with 5 levels."""
    upgrade_confirmation: UpgradePathConfirmations | None = None
    """Indicates whether the upgrade must be confirmed before applying."""


class HeroCostModel(BaseModel):
    base: int
    """Base cost of the hero."""
    class_: MonkeyClass = Field(..., alias='class')
    """Class of the hero, e.g., land, water, or any."""


class Towers(BaseModel):
    monkeys: dict[str, MonkeyCostModel]
    heroes: dict[str, HeroCostModel]


if __name__ == '__main__':
    with open('towers.json', 'r', encoding='utf-8') as f:
        data = f.read()

    towers_data = Towers.model_validate_json(data, strict=True)
    # print(towers_data.model_dump_json(indent=4, by_alias=True))
    print(towers_data.heroes['quincy'].class_.value)
    print(towers_data.monkeys['super'].upgrade_confirmation)
