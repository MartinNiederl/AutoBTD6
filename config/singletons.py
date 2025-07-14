from typing import Any, ClassVar, TypeVar, cast

import pyautogui
from pydantic import BaseModel

from json_types.gamemodes_types import Gamemodes
from json_types.image_areas_types import ImageAreas
from json_types.keybinds_types import Keybinds
from json_types.maps_types import Maps
from json_types.playthrough_stats_types import PlaythroughStats
from json_types.towers_types import Towers
from json_types.userconfig_types import UserConfig
from utils.utils import create_resolution_string, load_json_file, save_json_file

T = TypeVar('T', bound=BaseModel)


class SingletonMeta(type):
    """
    Metaclass that creates singleton behavior for configuration classes.
    """

    _instances: ClassVar[dict[type, Any]] = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class BaseConfigSingleton(metaclass=SingletonMeta):
    """Base class for all configuration singletons"""

    _data: BaseModel | None = None
    _file_path: str = ''
    _model_cls: type[BaseModel] = BaseModel
    _auto_save: bool = False

    def __init__(self, file_path: str | None = None, model_cls: type[BaseModel] | None = None, auto_save: bool | None = None):
        """Initialize the config singleton - parameters are optional and will use class defaults if not provided"""
        # Only set attributes if they're provided and the class attributes aren't already set
        # This allows for both class-level initialization and instance initialization
        if file_path and not self.__class__._file_path:
            self.__class__._file_path = file_path
        if model_cls and not self.__class__._model_cls:
            self.__class__._model_cls = model_cls
        if auto_save is not None and self.__class__._auto_save is False:
            self.__class__._auto_save = auto_save

    def load(self, force_reload: bool = False) -> BaseModel:
        """Load data from file"""
        if self.__class__._data is None or force_reload:
            json_data = load_json_file(self.__class__._file_path)
            self.__class__._data = self.__class__._model_cls.model_validate(json_data)
        return cast(BaseModel, self.__class__._data)

    def get_data(self) -> BaseModel:
        """Get the configuration data"""
        return self.load()

    def save(self) -> None:
        """Save data to file"""
        if self.__class__._data is not None:
            save_json_file(self.__class__._file_path, self.__class__._data.model_dump())

    def update(self, updated_data: dict[str, Any]) -> None:
        """Update data and save if auto_save is enabled"""
        data = self.get_data()
        for key, value in updated_data.items():
            setattr(data, key, value)

        if self.__class__._auto_save:
            self.save()


class GamemodesConfig(BaseConfigSingleton):
    _file_path = 'gamemodes.json'
    _model_cls = Gamemodes

    def get_data(self) -> Gamemodes:
        """Get the gamemodes data"""
        return cast(Gamemodes, super().get_data())

    def get_modes_list(self) -> list[str]:
        """Get a list of all available game modes"""
        return list(self.get_data().model_dump().keys())

    def get_mode_details(self, mode_name: str) -> dict[str, Any]:
        """Get details for a specific game mode"""
        data = self.get_data().model_dump()
        return data.get(mode_name, {})

    def is_valid_mode(self, mode_name: str) -> bool:
        """Check if a mode name is valid"""
        return mode_name in self.get_modes_list()


class MapsConfig(BaseConfigSingleton):
    _file_path = 'maps.json'
    _model_cls = Maps

    def get_data(self) -> Maps:
        """Get the maps data"""
        return cast(Maps, super().get_data())

    def get_map_names(self) -> list[str]:
        """Get all map names"""
        return list(self.get_data().model_dump().keys())

    def get_maps_by_category(self) -> dict[str, list[str]]:
        """Group maps by their category"""
        maps_by_category = {}
        for map_name, map_data in self.get_data().model_dump().items():
            category = map_data.get('category', 'Unknown')
            if category not in maps_by_category:
                maps_by_category[category] = []
            maps_by_category[category].append(map_name)
        return maps_by_category

    def get_map_details(self, map_name: str) -> dict[str, Any]:
        """Get details for a specific map"""
        data = self.get_data().model_dump()
        return data.get(map_name, {})


class KeybindsConfig(BaseConfigSingleton):
    _file_path = 'keybinds.json'
    _model_cls = Keybinds

    def get_data(self) -> Keybinds:
        """Get the keybinds data"""
        return cast(Keybinds, super().get_data())

    def get_monkey_key(self, monkey_name: str) -> str:
        """Get the key binding for a specific monkey"""
        data = self.get_data().model_dump()
        return data.get('monkeys', {}).get(monkey_name, '')

    def get_path_key(self, path: str) -> str:
        """Get the key binding for an upgrade path"""
        data = self.get_data().model_dump()
        return data.get('paths', {}).get(path, '')


class TowersConfig(BaseConfigSingleton):
    _file_path = 'towers.json'
    _model_cls = Towers

    def get_data(self) -> Towers:
        """Get the towers data"""
        return cast(Towers, super().get_data())

    def get_heroes(self) -> dict[str, Any]:
        """Get all heroes"""
        return self.get_data().model_dump().get('heroes', {})

    def get_hero_names(self) -> list[str]:
        """Get a list of all hero names"""
        return list(self.get_heroes().keys())


class ImageAreasConfig(BaseConfigSingleton):
    _file_path = 'image_areas.json'
    _model_cls = ImageAreas

    def get_data(self) -> ImageAreas:
        """Get the image areas data"""
        return cast(ImageAreas, super().get_data())

    def get_for_resolution(self, resolution=None):
        """Get image areas for a specific resolution"""
        areas = self.get_data().model_dump()
        res_string = create_resolution_string(resolution or pyautogui.size())

        if res_string in areas:
            return areas[res_string]

        # Default to 2560x1440 if not available
        return areas.get('2560x1440', {})


class PlaythroughStatsConfig(BaseConfigSingleton):
    _file_path = 'playthrough_stats.json'
    _model_cls = PlaythroughStats
    _auto_save = True

    def get_data(self) -> PlaythroughStats:
        """Get the playthrough stats data"""
        return cast(PlaythroughStats, super().get_data())

    def update_validation_status(self, playthrough_file: str, validation_status: bool, resolution=create_resolution_string()):
        """Update the validation status for a playthrough"""
        data = self.get_data().model_dump()

        if playthrough_file not in data:
            data[playthrough_file] = {}
        if resolution not in data[playthrough_file]:
            data[playthrough_file][resolution] = {'validation_result': False}

        data[playthrough_file][resolution]['validation_result'] = validation_status
        self.update(data)


class UserConfigConfig(BaseConfigSingleton):
    _file_path = 'userconfig.json'
    _model_cls = UserConfig
    _auto_save = True

    def get_data(self) -> UserConfig:
        """Get the user config data"""
        return cast(UserConfig, super().get_data())

    def has_monkey_knowledge(self, name: str) -> bool:
        """Check if the user has a specific monkey knowledge"""
        data = self.get_data().model_dump()
        return data.get('monkey_knowledge', {}).get(name, False)

    def set_monkey_knowledge(self, name: str, enabled: bool) -> None:
        """Set the status of a monkey knowledge"""
        data = self.get_data().model_dump()
        if 'monkey_knowledge' not in data:
            data['monkey_knowledge'] = {}
        data['monkey_knowledge'][name] = enabled
        self.update(data)

    def is_medal_unlocked(self, map_name: str, gamemode: str) -> bool:
        """Check if a medal is unlocked"""
        data = self.get_data().model_dump()
        return data.get('unlocked_maps', {}).get(map_name, {}).get(gamemode, False)

    def set_medal_unlocked(self, map_name: str, gamemode: str, is_unlocked: bool = True) -> None:
        """Set a medal as unlocked"""
        data = self.get_data().model_dump()
        if 'unlocked_maps' not in data:
            data['unlocked_maps'] = {}
        if map_name not in data['unlocked_maps']:
            data['unlocked_maps'][map_name] = {}
        data['unlocked_maps'][map_name][gamemode] = is_unlocked
        self.update(data)
