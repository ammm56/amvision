"""将本次关系计算转为平台公开证据；不再执行算法或保留 owner。"""

from dataclasses import asdict

from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.measurement3d_directional import PlaneSupportEvidence
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.relation3d_evidence import (
    RelationEvidenceItem,
    RelationGeometry,
    RelationMethod,
    RelationSupport,
)
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.dimension_runtime import dimension_support
from custom_nodes.metrology3d_nodes.shared.relation_runtime import measure_relation


def relation_evidence(runtime, cloud, groups, parameters, *, cancel):
    """沿原 Scope 读取快照；失败帧也不能延长借用数组生命周期。"""
    try:
        return _relation_evidence(runtime, cloud, groups, parameters, cancel)
    except BaseException as error:
        release_exception_frames(error)
        raise


def _relation_evidence(runtime, cloud, groups, parameters, cancel):
    """保留 A/B 全部状态，不能只输出成功对象或复用历史结果。"""
    result = measure_relation(runtime, cloud, groups, parameters, cancel=cancel)
    supports, origins = [], set()
    for role, operand in (("reference", result.reference), ("target", result.target)):
        cancel()
        feature = operand.feature
        reference = feature.support if feature is not None else cloud
        plane = feature is not None and feature.kind == "plane"
        base = dimension_support(
            runtime,
            reference,
            role,
            feature=feature if not plane else None,
            cancel=cancel,
        )
        supports.append(
            RelationSupport(
                **base.model_dump(),
                point=asdict(operand.point) if operand.point else None,
                plane=PlaneSupportEvidence.model_validate(
                    feature.model_dump(exclude={"kind", "feature_id", "support"})
                )
                if plane
                else None,
                coverage=result.plane_support.coverage
                if role == "target" and result.plane_support
                else None,
                coverage_quality=result.coverage_quality if role == "target" else None,
            )
        )
        origins.add(operand.point.origin if operand.point else "estimated")
    valid = result.reason is None
    raw = result.geometry
    geometry = (
        RelationGeometry(
            endpoints=(raw.reference_point, raw.target_point)
            if raw.reference_point is not None and raw.target_point is not None
            else None,
            contacts_unique=raw.contacts_unique,
            support_pairs=raw.support_pairs,
        )
        if valid
        else None
    )
    item = RelationEvidenceItem(
        item_id=parameters.item_id,
        component="angle" if parameters.relation.kind.endswith("angle") else "distance",
        value=result.value,
        valid=valid,
        reason=result.reason,
        quality=result.quality,
        support=tuple(supports),
        geometry=geometry,
        diagnostic=None if valid else dict(stage=result.stage, role=result.failed_role),
        sample_origin=next(iter(origins)) if len(origins) == 1 else "mixed",
        method=RelationMethod(
            parameters=parameters, parameters_sha256=parameter_digest(parameters)
        ),
    )
    cancel()
    return MeasurementEvidence3d(
        observation_id=cloud.observation_id,
        frame_id=parameters.frame_id,
        length_unit=parameters.length_unit,
        items=(item,),
    )
