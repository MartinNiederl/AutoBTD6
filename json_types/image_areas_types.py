from pydantic import BaseModel, RootModel

Coord = tuple[int, int]
Rect = tuple[int, int, int, int]
Coords = list[Coord]
Label = str

SimpleValue = Coord | Rect | str
NestedValue = SimpleValue | dict[Label, SimpleValue] | Coords


class ResolutionConfig(BaseModel):
    ocr_segments: dict[Label, Rect]
    compare: dict[Label, Rect | dict[Label, Rect]]
    click: dict[Label, NestedValue]


class ImageAreas(RootModel):
    root: dict[Label, ResolutionConfig]


if __name__ == '__main__':
    with open('image_areas.json', encoding='utf-8') as f:
        data = f.read()

    config = ImageAreas.model_validate_json(data, strict=True)
    print(config.root['2560x1440'].click['hero_positions'])
