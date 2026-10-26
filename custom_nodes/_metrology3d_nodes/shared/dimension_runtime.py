"""尺寸节点共享身份、有限支持快照和结果封装，不包含几何算法。"""

import numpy as np

from backend.contracts.workflows.boundary3d_observations import BoundaryEvidence
from backend.contracts.workflows.dimension3d_evidence import (
    CircleSnapshot,
    DimensionSupport,
    EdgePairEvidenceItem,
    EdgePairMethod,
    ExtentsEvidenceItem,
    ExtentsMethod,
    HoleEvidenceItem,
    HoleMethod,
    LineSnapshot,
)
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.evaluation3d import FeatureEvaluation3d
from backend.contracts.workflows.dimension3d_parameters import (
    resolve_dimension_parameters,
)
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes._metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent
from custom_nodes._metrology3d_nodes.shared.fit_plane import _positions, _rows
from custom_nodes._metrology3d_nodes.shared.geometry_quality import (
    geometry_quality,
    require_quality_result,
)
from custom_nodes._metrology3d_nodes.shared.measurement_support import require_cloud


def dimension_evaluation(parameters, feature):
    """长宽/孔取选中特征，边对取 reference，并沿原门禁核对 target。"""
    if isinstance(parameters.evaluation, FeatureEvaluation3d):
        if feature is None:
            raise InvalidRequestError("继承评价面需要选中特征")
        evaluation = (
            (
                feature.method.resolution.evaluation
                if feature.kind == "boundary"
                else feature.method.evaluation
            )
            if feature.valid
            else None
        )
    else:
        evaluation = parameters.evaluation
    try:
        return evaluation, resolve_dimension_parameters(parameters, evaluation)
    except ValueError as error:
        raise InvalidRequestError(str(error)) from error


def select_features(runtime, groups, parameters, identities, kind):
    """显式 ID、精确类型及质量复核；接线错误不伪装正常缺测。"""
    if not groups:
        raise InvalidRequestError("尺寸测量缺少 features 输入")
    observation = groups[0].observation_id
    available = {}
    for group in groups:
        if (group.run_id, group.observation_id, group.frame_id, group.length_unit) != (
            runtime.run_id,
            observation,
            parameters.frame_id,
            parameters.length_unit,
        ):
            raise InvalidRequestError("尺寸特征运行、观测或空间不一致")
        for feature in group.items:
            if feature.feature_id in available:
                raise InvalidRequestError("尺寸输入特征 ID 重复")
            available[feature.feature_id] = feature
    selected = []
    for identity in identities:
        feature = available.get(identity)
        if feature is None or feature.kind != kind:
            raise InvalidRequestError("尺寸指定特征不存在或类型错误")
        require_cloud(runtime, feature.support, parameters, observation)
        require_quality_result(feature.quality, feature.method.quality_policy)
        if kind == "boundary":
            for segment in feature.segments:
                require_quality_result(segment.quality, feature.method.quality_policy)
        selected.append(feature)
    return selected


def dimension_support(runtime, cloud, role, *, feature=None, cancel):
    """沿原 Scope 借用支持，不持有租约或复制整云。"""
    try:
        return _dimension_support(runtime, cloud, role, feature=feature, cancel=cancel)
    except BaseException as error:
        release_exception_frames(error)
        raise


def _dimension_support(runtime, cloud, role, *, feature, cancel):
    """扫描块只在当前调用内持有，异常栈不能延长数组寿命。"""
    ready, bounds = cloud.state == "ready", None
    if ready and cloud.point_count:
        low, high = np.full(3, np.inf), np.full(3, -np.inf)
        rows = _rows(runtime, cloud)
        with runtime.borrow(cloud) as view:
            for start in range(0, cloud.point_count, rows):
                cancel()
                block = _positions(view, start, min(start + rows, cloud.point_count))
                low, high = (
                    np.minimum(low, block.min(axis=0)),
                    np.maximum(high, block.max(axis=0)),
                )
        bounds = dict(min=low, max=high)
    snapshot = None
    if feature is not None:
        cls = {
            "boundary": BoundaryEvidence,
            "line": LineSnapshot,
            "circle": CircleSnapshot,
        }[feature.kind]
        snapshot = cls.model_validate(feature.model_dump(exclude={"support"}))
    return DimensionSupport(
        role=role,
        content_sha256=freeze_cloud_parent(runtime, cloud)["content_sha256"]
        if ready
        else None,
        point_count=cloud.point_count if ready else None,
        source_point_count=runtime.source_point_count(cloud) if ready else None,
        vertex_kind=cloud.vertex_kind if ready else None,
        sample_origin=cloud.sample_origin if ready else None,
        bounds=bounds,
        topology=cloud.topology if ready else None,
        feature=snapshot,
    )


def dimension_result(
    kind,
    parameters,
    observation,
    support,
    *,
    geometry,
    metrics,
    values,
    reason=None,
    stage="geometry",
    candidates=None,
    feature_id=None,
    evaluation,
):
    """唯一量值来源；失败保留全部启用项，质量比较复用 check_limits。"""
    metric_values = {"geometry_usable": (int(reason is None), "1"), **metrics}
    for rule in parameters.quality_policy.rules:
        if (
            rule.item_id not in metric_values
            or rule.unit != metric_values[rule.item_id][1]
        ):
            raise InvalidRequestError("尺寸质量包含未知指标或错误单位")
    quality = geometry_quality(
        observation,
        metric_values,
        parameters.quality_policy,
        reason=reason or "metric_unavailable",
    )
    if reason is None and not quality.usable:
        reason, stage = "insufficient_quality", "quality"
    method_type, item_type = {
        "measure-extents": (ExtentsMethod, ExtentsEvidenceItem),
        "measure-edge-pair": (EdgePairMethod, EdgePairEvidenceItem),
        "measure-hole": (HoleMethod, HoleEvidenceItem),
    }[kind]
    origins = {s.sample_origin for s in support if s.sample_origin is not None}
    origin = (
        (next(iter(origins)) if len(origins) == 1 else "mixed")
        if kind == "measure-extents"
        else "interpolated"
    )
    method = method_type(
        parameters=parameters,
        parameters_sha256=parameter_digest(parameters),
        evaluation=evaluation,
    )
    items = tuple(
        item_type(
            item_id=o.item_id,
            component=o.component,
            value=values[o.component] if reason is None else None,
            valid=reason is None,
            reason=reason,
            quality=quality,
            support=support,
            geometry=geometry if reason is None else None,
            method=method,
            sample_origin=origin,
            diagnostic=None
            if reason is None
            else dict(stage=stage, feature_id=feature_id, candidates=candidates),
        )
        for o in parameters.outputs
    )
    return MeasurementEvidence3d(
        observation_id=observation,
        frame_id=parameters.frame_id,
        length_unit=parameters.length_unit,
        items=items,
    )
