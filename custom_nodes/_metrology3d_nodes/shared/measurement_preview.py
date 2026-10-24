"""测量显示只附加有限持久证据，不建立历史原云会话。"""

from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.measurement3d_parameters import MeasureStepParameters
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.geometry_quality import (
    require_quality_result,
)
from custom_nodes._metrology3d_nodes.shared.preview import unavailable_body


def attach_measurements(cloud, body, values, *, policy, cancel):
    """核对观测/空间及实际质量比较后交付显示，不信任 passed 输入。"""
    groups = values.get("evidence") or ()
    items = []
    for raw in groups:
        cancel()
        evidence = MeasurementEvidence3d.model_validate(raw)
        if (evidence.observation_id, evidence.frame_id, evidence.length_unit) != (
            cloud.observation_id,
            cloud.spatial.frame_id,
            cloud.spatial.length_unit,
        ):
            raise InvalidRequestError("测量显示与点云观测、坐标或单位不一致")
        for item in evidence.items:
            parameters = item.method.parameters
            settings = (
                parameters.mode
                if isinstance(parameters, MeasureStepParameters)
                else parameters
            )
            require_quality_result(item.quality, settings.quality_policy)
            for side in item.support:
                if item.kind in {"height-query", "measure-step"} and side.plane:
                    require_quality_result(
                        side.plane.quality, side.plane.method.quality_policy
                    )
                elif item.kind not in {"height-query", "measure-step"} and side.feature:
                    feature = side.feature
                    require_quality_result(
                        feature.quality, feature.method.quality_policy
                    )
                    if feature.kind == "boundary":
                        for segment in feature.segments:
                            require_quality_result(
                                segment.quality, feature.method.quality_policy
                            )
            items.append(item)
            if len(items) > 8192:
                raise InvalidRequestError("测量显示数量超限")
    if not groups or body["state"] not in {"ready", "empty"}:
        return body
    merged = MeasurementEvidence3d(
        observation_id=cloud.observation_id,
        frame_id=cloud.spatial.frame_id,
        length_unit=cloud.spatial.length_unit,
        items=items,
    )
    output = {**body, "measurements": merged.model_dump(mode="json")}
    if len(canonical_cloud_json(output)) > policy.max_body_bytes:
        return unavailable_body(cloud, "preview_size_limit")
    cancel()
    return output
