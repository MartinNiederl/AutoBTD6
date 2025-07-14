from pydantic import BaseModel, Field

MonkeyHotkey = str | int
PathHotkey = int
OtherHotkey = str
RecordingHotkey = str


class Keybinds(BaseModel):
    monkeys: dict[str, MonkeyHotkey]
    """
    Keybinds for monkeys, where the key can be a string or an integer.
    In case of an integer, it represents an AHK (AutoHotkey) key code. (e.g., 21 for 'Y')
    """
    paths: dict[str, PathHotkey] = Field(..., alias='path')
    others: dict[str, OtherHotkey]
    recording: dict[str, RecordingHotkey]


if __name__ == '__main__':
    with open('keybinds.json', 'r', encoding='utf-8') as f:
        data = f.read()

    config = Keybinds.model_validate_json(data, strict=True)
    print(config.monkeys['dart'])
    print(config.paths['0'])
    print(config.others['sell'])
    print(config.recording['retarget'])
