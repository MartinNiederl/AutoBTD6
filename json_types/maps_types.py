from enum import Enum

from pydantic import BaseModel, RootModel


class MapCategory(str, Enum):
    beginner = 'beginner'
    intermediate = 'intermediate'
    advanced = 'advanced'
    expert = 'expert'


class MapModel(BaseModel):
    category: MapCategory
    """Category of the map (beginner, intermediate, advanced, expert)."""
    name: str
    """Display name of the map."""
    page: int
    """Page number in the map selection UI."""
    pos: int
    """Position on the page (0-5)."""


class Maps(RootModel):
    root: dict[str, MapModel]
    """
    Maps configuration, where the key is the map identifier (e.g., 'carved', 'ouch').
    Each map has a category, name, page number, and position on that page.
    """


if __name__ == '__main__':
    with open('maps.json', 'r', encoding='utf-8') as f:
        data = f.read()

    maps_data = Maps.model_validate_json(data, strict=True)
    print(maps_data.root['carved'].name)
    print(maps_data.root['ouch'].category)
