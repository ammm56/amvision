"""高差节点可以执行单项或同线多基准，不改变单项证据契约。"""

from backend.contracts.workflows.metrology import Contract
from backend.contracts.workflows.measurement3d_parameters import MeasureStepParameters
from backend.contracts.workflows.measurement3d_multi_reference import (
    MultiReferenceStepParameters,
)


class StepNodeParameters(Contract):
    """模式及全部量项原子更新。"""

    settings: MeasureStepParameters | MultiReferenceStepParameters
