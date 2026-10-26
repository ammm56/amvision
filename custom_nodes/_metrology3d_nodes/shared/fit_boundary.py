"""直线/圆节点的真实边界消费，数值内核不读取显示证据。"""

from backend.contracts.workflows.boundary3d import FitLineParameters
from backend.contracts.workflows.boundary3d_observations import (
    BoundaryFeature,
    BoundaryEvidence,
    LineFeature,
    CircleFeature,
    LineMethod,
    CircleMethod,
)
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_observations import Features3d
from backend.contracts.workflows.evaluation3d import FeatureEvaluation3d
from custom_nodes._metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes._metrology3d_nodes.shared.boundary_runtime import (
    require_space,
    select_boundary,
    materialize_positions,
)
from custom_nodes._metrology3d_nodes.shared.boundary_fitting import (
    BoundaryFit,
    fit_boundary_line,
    fit_boundary_circle,
    evaluate_fit_quality,
    fit_metric_units,
)
from custom_nodes._metrology3d_nodes.shared.geometry_quality import (
    require_quality_result,
)


def fit_boundary(runtime, group, parameters, *, cancel):
    """明确 ID 和全部支持，质量失败时清除几何与可用区间。"""
    selected = [
        item
        for item in group.items
        if item.feature_id == parameters.selection.feature_id
    ]
    if len(selected) != 1 or not isinstance(selected[0], BoundaryFeature):
        raise InvalidRequestError("拟合输入必须包含指定的唯一边界特征")
    boundary = selected[0]
    require_space(runtime, boundary.support, parameters.evaluation)
    require_quality_result(boundary.quality, boundary.method.quality_policy)
    for item in boundary.segments:
        require_quality_result(item.quality, boundary.method.quality_policy)
    support = boundary.support
    line = isinstance(parameters, FitLineParameters)
    method_type, feature_type = (
        (LineMethod, LineFeature) if line else (CircleMethod, CircleFeature)
    )
    evaluation = (
        (boundary.method.resolution.evaluation if boundary.valid else None)
        if isinstance(parameters.evaluation, FeatureEvaluation3d)
        else parameters.evaluation
    )
    method = method_type(
        parameters=parameters,
        parameters_sha256=parameter_digest(parameters),
        evaluation=evaluation,
        boundary=BoundaryEvidence.model_validate(
            boundary.model_dump(exclude={"support"})
        ),
        boundary_content_sha256=freeze_cloud_parent(runtime, support)["content_sha256"]
        if support.state == "ready"
        else None,
    )
    positions = None
    try:
        if boundary.valid:
            support = select_boundary(
                runtime, support, parameters.selection, cancel=cancel
            )
            positions, _ = materialize_positions(
                runtime, support, factor=1152, cancel=cancel
            )
            kernel = fit_boundary_line if line else fit_boundary_circle
            result = kernel(
                positions,
                support.topology,
                method.resolved_parameters(),
                max_working_bytes=runtime.policy.max_working_bytes - positions.nbytes,
                cancel=cancel,
            )
        else:
            result = BoundaryFit(
                boundary.reason,
                None,
                {key: None for key in fit_metric_units(parameters)},
                (),
            )
        quality = evaluate_fit_quality(
            result, parameters, observation_id=support.observation_id
        )
        reason = result.reason or (None if quality.usable else "insufficient_quality")
        feature = feature_type(
            feature_id=parameters.feature_id,
            valid=reason is None,
            reason=reason,
            geometry=result.geometry if reason is None else None,
            support=support,
            quality=quality,
            method=method,
            intervals=result.intervals if reason is None else (),
            **({} if line else {"solver": result.solver}),
        )
        cancel()
        return Features3d(
            run_id=runtime.run_id,
            observation_id=support.observation_id,
            frame_id=parameters.evaluation.frame_id,
            length_unit=parameters.evaluation.length_unit,
            items=(feature,),
        )
    except BaseException as error:
        positions = None
        release_exception_frames(error)
        raise
