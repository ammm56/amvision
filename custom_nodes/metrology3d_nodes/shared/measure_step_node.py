"""节点级量项组织，数值、支持和质量计算沿用 measure_step。"""

from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.measurement3d_multi_reference import (
    MultiReferenceStepParameters,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.measure_step import measure_step
from custom_nodes.metrology3d_nodes.shared.measurement_support import select_planes


def measure_step_node(
    runtime, parameters, *, groups=(), reference=None, target=None, pose=None, cancel
):
    """先核对全部来源，再逐项执行；任何无效量项均保留，不输出部分成功集。"""
    if not isinstance(parameters, MultiReferenceStepParameters):
        return measure_step(
            runtime,
            parameters,
            groups=groups,
            reference=reference,
            target=target,
            pose=pose,
            cancel=cancel,
        )
    if reference is not None or target is not None:
        raise InvalidRequestError("同线多基准模式不能连接统计点云端口")
    measurements = parameters.measurements()
    observation = None
    for item in measurements:
        cancel()
        planes = select_planes(
            runtime,
            groups,
            item,
            [item.mode.reference_feature_id, item.mode.target_feature_id],
        )
        current = planes[0].support.observation_id
        if observation is not None and current != observation:
            raise InvalidRequestError("同线多基准来源不属于同次观测")
        observation = current
    items = []
    for item in measurements:
        cancel()
        evidence = measure_step(runtime, item, groups=groups, pose=pose, cancel=cancel)
        items.extend(evidence.items)
    cancel()
    return MeasurementEvidence3d(
        observation_id=observation,
        frame_id=parameters.frame_id,
        length_unit=parameters.length_unit,
        items=tuple(items),
    )
