from typing import Any

from pydantic import BaseModel, RootModel, model_validator


class ModeStats(BaseModel):
    attempts: int
    """Number of attempts for this gamemode."""
    wins: int
    """Number of successful wins for this gamemode."""
    win_times: list[float]
    """List of completion times in seconds for successful runs."""


class ResolutionData(BaseModel):
    validation_result: bool | None = None
    modes: dict[str, ModeStats] = {}

    @model_validator(mode='before')
    @classmethod
    def split_modes(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            raise TypeError('Resolution data must be a dict.')
        # Separate known and unknown keys
        v_result = data.get('validation_result')
        modes = {k: v for k, v in data.items() if k != 'validation_result'}
        return {'validation_result': v_result, 'modes': modes}

    @model_validator(mode='after')
    def parse_modes(self) -> 'ResolutionData':
        # Parse modes from dicts to ModeStats
        self.modes = {k: (v if isinstance(v, ModeStats) else ModeStats.model_validate(v)) for k, v in self.modes.items()}
        return self

    def model_dump(self, **kwargs):
        out = super().model_dump(**kwargs)
        # flatten: merge modes and validation_result for serialization
        result = dict(out.get('modes', {}))
        if out.get('validation_result') is not None:
            result['validation_result'] = out['validation_result']
        return result


class PlaythroughEntry(BaseModel):
    version: float | None = None
    """BTD6 version number when this playthrough was recorded."""
    resolutions: dict[str, ResolutionData]

    @model_validator(mode='before')
    @classmethod
    def split_resolutions(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            raise TypeError('PlaythroughEntry must be a dict.')
        v = data.get('version')
        resolutions = {k: v for k, v in data.items() if k != 'version'}
        return {'version': v, 'resolutions': resolutions}

    def model_dump(self, **kwargs):
        out = super().model_dump(**kwargs)
        # flatten: version, then all resolution keys at top level
        flat = {'version': out['version']}
        flat.update(out['resolutions'])
        return flat


class PlaythroughStats(RootModel):
    root: dict[str, PlaythroughEntry]
    """
    Playthrough statistics, where the key is the playthrough filename.
    Each playthrough contains stats for different resolutions and gamemodes.
    """


if __name__ == '__main__':
    with open('playthrough_stats.json', 'r', encoding='utf-8') as f:
        data = f.read()

    stats_data = PlaythroughStats.model_validate_json(data, strict=True)
    # Access a specific playthrough
    logs_chimps = stats_data.root['playthroughs/logs#chimps#2560x1440#noMK#noLL.btd6']
    print(f'Version: {logs_chimps.version}')

    # Access resolution stats
    resolution_2560 = logs_chimps.resolutions.get('2560x1440', None)
    if resolution_2560:
        print(f'Validation result: {resolution_2560.validation_result}')

        # Access gamemode stats
        chimps_stats = resolution_2560.modes.get('chimps', None)
        if chimps_stats:
            print(f'CHIMPS attempts: {chimps_stats.attempts}')
            print(f'CHIMPS wins: {chimps_stats.wins}')
            print(f'Win times: {chimps_stats.win_times}')
