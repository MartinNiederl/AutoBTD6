from typing import TypedDict, NotRequired, Literal, Tuple, Union

# TODO: fix "action" overrides symbol of same name in class "StepBase"
# TODO: use this class instead of the nasty dictionary that is created in helper.py

class StepBase(TypedDict):
    action: str
    cost: int

class PlaceStep(StepBase):
    action: Literal["place"]  # type: ignore
    type: str
    name: str
    key: str
    pos: Tuple[int, int]
    discount: NotRequired[str]

class UpgradeStep(StepBase):
    action: Literal["upgrade"]  # type: ignore
    name: str
    key: str
    pos: Tuple[int, int]
    path: int
    discount: NotRequired[str]

class RetargetStep(StepBase):
    action: Literal["retarget"]  # type: ignore
    name: str
    key: str
    pos: Tuple[int, int]
    to: NotRequired[Tuple[int, int]]

class SpecialStep(StepBase):
    action: Literal["special"]  # type: ignore
    name: str
    key: str
    pos: Tuple[int, int]

class SellStep(StepBase):
    action: Literal["sell"]  # type: ignore
    name: str
    key: str
    pos: Tuple[int, int]

class RemoveStep(StepBase):
    action: Literal["remove"]  # type: ignore
    pos: Tuple[int, int]

class AwaitRoundStep(StepBase):
    action: Literal["await_round"]  # type: ignore
    round: int

class SpeedStep(StepBase):
    action: Literal["speed"]  # type: ignore
    speed: str

class ClickStep(StepBase):
    action: Literal["click"]  # type: ignore
    name: NotRequired[str]
    pos: Tuple[int, int]

Step = Union[
    PlaceStep,
    UpgradeStep,
    RetargetStep,
    SpecialStep,
    SellStep,
    RemoveStep,
    AwaitRoundStep,
    SpeedStep,
    ClickStep,
    StepBase  # default "empty" step
]
