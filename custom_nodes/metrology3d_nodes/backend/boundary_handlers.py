"""M3.2 三节点接线；复用既有 Scope、参数 Schema 和执行控制。"""

from backend.contracts.workflows.boundary3d import (
    FitLineNodeParameters,
    FitCircleNodeParameters,
)
from backend.contracts.workflows.edge_extraction import (
    BoundaryExtractionNodeParameters,
    MeasuredEdgeParameters,
    SamplingExtractionParameters,
)
from backend.contracts.workflows.geometry3d_observations import Features3d, Pose3d
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.measurement3d_directional import (
    MeasurementEvidenceItem,
)
from custom_nodes.metrology3d_nodes.shared.measurement_support import select_planes
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.node_runtime import (
    require_node_runtime,
    cloud_input,
)
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes.metrology3d_nodes.shared.fit_boundary import fit_boundary


def extract(request):
    """按显式方法校验输入；未连接的多输入端口由执行器传空列表。"""
    node_parameters = BoundaryExtractionNodeParameters.model_validate(
        request.parameters
    )
    parameters = node_parameters.settings
    env = require_node_runtime(request)
    values = request.input_values
    groups = [Features3d.model_validate(raw) for raw in values.get("features") or ()]
    reference = cloud_input(request, env.runtime)
    if isinstance(parameters, (MeasuredEdgeParameters, SamplingExtractionParameters)):
        if values.get("pose") is not None or any(
            values.get(key) not in (None, [], ()) for key in ("features", "evidence")
        ):
            raise InvalidRequestError(
                "实测边和采样诊断不接受额外的平面、位姿或尺寸输入"
            )
        if isinstance(parameters, SamplingExtractionParameters):
            if values.get("height_map") is not None:
                raise InvalidRequestError("采样诊断不接受高度图")
            from custom_nodes.metrology3d_nodes.shared.edge_sampling import (
                sampling_candidates,
            )
            from custom_nodes.metrology3d_nodes.shared.edge_sampling_context import (
                sampling_context,
            )
            from custom_nodes.metrology3d_nodes.shared.edge_reference import (
                publish_edge_diagnostic,
            )

            candidates = sampling_candidates(
                env.runtime, reference, parameters.method, cancel=env.cancel
            )
            result = None
            try:
                result = sampling_context(env.runtime, candidates, cancel=env.cancel)
                diagnostic = publish_edge_diagnostic(
                    env.runtime, reference, sampling_result=result
                )
            except BaseException:
                if result is not None:
                    env.runtime.storage_scope.close_resource(result.resource_key)
                env.runtime.storage_scope.close_resource(candidates.resource_key)
                raise
            return {
                "cloud": reference.model_dump(mode="json"),
                "source_cloud": reference.model_dump(mode="json"),
                "diagnostics": diagnostic.model_dump(mode="json"),
            }
        from backend.contracts.workflows.height_map_reference import HeightMapReference
        from custom_nodes.metrology3d_nodes.shared.edge_extraction import (
            extract_measured_edge,
        )

        height = (
            HeightMapReference.model_validate(values["height_map"])
            if values.get("height_map") is not None
            else None
        )
        result, diagnostic = extract_measured_edge(
            env.runtime, reference, parameters, height_map=height, cancel=env.cancel
        )
        feature = result.items[0]
        cloud = (
            feature.support
            if feature.valid
            else feature.support.unavailable(feature.reason)
        )
        return {
            "cloud": cloud.model_dump(mode="json"),
            "source_cloud": reference.model_dump(mode="json"),
            "features": result.model_dump(mode="json"),
            "diagnostics": diagnostic.model_dump(mode="json"),
        }
    if values.get("height_map") is not None:
        raise InvalidRequestError("该边界方法不接受高度图")
    pose = (
        Pose3d.model_validate(values["pose"])
        if values.get("pose") is not None
        else None
    )
    evidence = [
        MeasurementEvidence3d.model_validate(raw)
        for raw in values.get("evidence") or ()
    ]
    plane, measurement, measurement_planes = None, None, ()
    method = parameters.method
    if method.kind in {"contour", "pose-contour", "visible-envelope"}:
        ids = [method.reference_feature_id]
        ratio = (
            method.kind in {"pose-contour", "visible-envelope"}
            and method.height.kind == "measurement-ratio"
        )
        if ratio:
            ids.extend(
                (method.height.reference_feature_id, method.height.target_feature_id)
            )
        unique = list(dict.fromkeys(ids))
        planes = dict(
            zip(
                unique,
                select_planes(
                    env.runtime,
                    groups,
                    parameters.evaluation,
                    unique,
                    observation_id=reference.observation_id,
                ),
            )
        )
        plane = planes[ids[0]]
        if ratio:
            selected = []
            seen = set()
            for group in evidence:
                if (group.observation_id, group.frame_id, group.length_unit) != (
                    reference.observation_id,
                    parameters.evaluation.frame_id,
                    parameters.evaluation.length_unit,
                ):
                    raise InvalidRequestError("等高测量证据观测或空间不一致")
                for item in group.items:
                    if item.item_id in seen:
                        raise InvalidRequestError("等高测量证据 ID 重复")
                    seen.add(item.item_id)
                    if item.item_id == method.height.item_id:
                        selected.append(item)
            if len(selected) != 1 or not isinstance(
                selected[0], MeasurementEvidenceItem
            ):
                raise InvalidRequestError("比例等高必须选择唯一的高度或方向高差")
            measurement = selected[0]
            measurement_planes = tuple(planes[key] for key in ids[1:])
        elif evidence:
            raise InvalidRequestError("固定等高不能连接测量证据")
    elif groups or pose is not None or evidence:
        raise InvalidRequestError("投影和截面不接受多余基准特征输入")
    capture = None
    if node_parameters.capture_debug:
        from custom_nodes.metrology3d_nodes.shared.boundary_debug import BoundaryCapture

        capture = BoundaryCapture(
            env.runtime,
            reference,
            parameters,
            policy=env.policy.preview,
            directory=env.service.storage.root_dir,
            node_id=request.node_id,
            invocation_id=request.node_invocation_id,
            cancel=env.cancel,
        )
    result = extract_boundary(
        env.runtime,
        reference,
        parameters,
        cancel=env.cancel,
        contour_plane=plane,
        pose=pose,
        measurement=measurement,
        measurement_planes=measurement_planes,
        capture=capture,
    )
    feature = result.items[0]
    cloud = feature.support
    if not feature.valid:
        cloud = cloud.unavailable(feature.reason)
    return {
        "features": result.model_dump(mode="json"),
        "cloud": cloud.model_dump(mode="json"),
    }


def line(request):
    """直线只消费完整边界特征。"""
    return _fit(request, FitLineNodeParameters)


def circle(request):
    """圆只消费完整边界特征。"""
    return _fit(request, FitCircleNodeParameters)


def _fit(request, model):
    """两个拟合入口共用输入和运行身份核验。"""
    parameters = model.model_validate(request.parameters).settings
    env = require_node_runtime(request)
    result = fit_boundary(
        env.runtime,
        Features3d.model_validate(request.input_values.get("features")),
        parameters,
        cancel=env.cancel,
    )
    output = {"features": result.model_dump(mode="json")}
    if model is FitCircleNodeParameters:
        feature = result.items[0]
        # 模型质量与支持资源状态分开；失败圆仍可保存实际存在的支持证据。
        output["cloud"] = feature.support.model_dump(mode="json")
    return output
