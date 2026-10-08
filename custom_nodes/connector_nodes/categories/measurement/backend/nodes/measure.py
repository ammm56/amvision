"""Connector Measure：仅消费命名几何，不读取图片或隐式重新检测。"""

import numpy as np
from pydantic import TypeAdapter, ValidationError

from backend.contracts.workflows.metrology import (
    FeatureObservations,
    NumericItem,
    NumericTable,
    unique_ids,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.measurement import numeric_table_to_value
from backend.nodes.measurement_resources import require_prepared_measurement_resource
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from custom_nodes.connector_nodes.shared.contracts import (
    MeasurementDefinition,
    PinObservations,
)
from custom_nodes.connector_nodes.shared.runtime import parse
from custom_nodes.opencv_nodes.shared.backend.metrology import (
    map_points,
    measure_section,
)
from custom_nodes.opencv_nodes.shared.backend.metrology.geometry import (
    calibrated_points,
    map_unit_direction,
)

NODE_TYPE_ID = "custom.connector.measure"


def handle_node(request) -> dict:
    """展开显式尺寸项；缺特征与区间外结果无效，错误接线直接失败。"""
    control = build_node_execution_control(request)
    observations = parse(PinObservations, request.input_values.get("pins"))
    features = parse(FeatureObservations, request.input_values.get("features"))
    try:
        observations.require_matching_features(features)
        definitions = TypeAdapter(tuple[MeasurementDefinition, ...]).validate_python(
            request.parameters.get("items", [])
        )
        unique_ids([d.item_id for d in definitions], "items")
        if not 1 <= len(definitions) <= 8192:
            raise ValueError("尺寸项数量必须为 1–8192")
    except (ValidationError, ValueError) as exc:
        raise InvalidRequestError(str(exc)) from exc
    requested_unit = request.parameters.get("unit", "pixel")
    calibration = None
    if requested_unit != "pixel":
        prepared = require_prepared_measurement_resource(
            request, "calibration_resource", "planar-calibration"
        )
        calibration = prepared["content"].calibration
        if calibration.unit != requested_unit or (
            calibration.image_width,
            calibration.image_height,
        ) != (observations.image.width, observations.image.height):
            raise InvalidRequestError("标定单位或图像尺寸与当前测量不匹配")
    elif request.parameters.get("calibration_resource") is not None:
        raise InvalidRequestError("Pixel 模式不能配置未使用的物理标定资源")
    pins = {p.pin_id: p for p in observations.pins}
    # 配方方向和截面在 reference 像素坐标定义；先去位姿，不能把参考截面用于旋转后的原图。
    reference_from_image = np.linalg.inv(np.asarray(observations.image_from_reference))
    geometry = {
        f.feature_id: map_points(f.points, reference_from_image)
        for f in features.features
    }
    feature_kinds = {f.feature_id: f.kind for f in features.features}

    def reference_point(point):
        """将本次原图中的单点转换到配方参考像素坐标。"""
        return map_points([point], reference_from_image)[0]

    values, annotations = [], []
    for definition in definitions:
        control.raise_if_cancelled_or_expired()
        if not definition.enabled:
            continue
        if definition.pin_a not in pins or (
            definition.pin_b is not None and definition.pin_b not in pins
        ):
            raise InvalidRequestError("尺寸定义引用了不存在的 PIN ID")
        a = pins[definition.pin_a]
        b = pins.get(definition.pin_b)
        reason = None
        value = None
        endpoints = None
        unit = "degrees" if definition.kind == "angle" else requested_unit
        if a.state != "found" or (b is not None and b.state != "found"):
            reason = "pin_not_found"
        else:
            axis = np.asarray(definition.direction)
            if definition.kind in {"width", "gap"}:
                first_key = a.pin_id + (
                    ":left" if definition.kind == "width" else ":right"
                )
                second_key = (a.pin_id if b is None else b.pin_id) + (
                    ":right" if definition.kind == "width" else ":left"
                )
                if (
                    first_key not in a.feature_ids
                    or second_key not in (a if b is None else b).feature_ids
                    or any(
                        feature_kinds.get(key) != "edge"
                        for key in (first_key, second_key)
                    )
                ):
                    reason = "feature_missing"
                else:
                    first = measure_section(
                        geometry[first_key], axis, definition.section
                    )
                    second = measure_section(
                        geometry[second_key], axis, definition.section
                    )
                    if first is None or second is None:
                        reason = "section_not_observed"
                    else:
                        endpoints = (first, second)
            elif definition.kind == "offset":
                endpoints = (
                    reference_point(a.nominal_image_point),
                    reference_point(a.center_image_point),
                )
            elif definition.kind == "length":
                keys = (definition.feature_a, definition.feature_b)
                if (
                    keys[0] not in a.feature_ids
                    or keys[1] not in b.feature_ids
                    or any(feature_kinds.get(key) != "point" for key in keys)
                ):
                    reason = "endpoint_not_observed"
                else:
                    endpoints = (geometry[keys[0]][0], geometry[keys[1]][0])
            elif definition.kind == "angle":
                keys = (a.pin_id + ":left", b.pin_id + ":left")
                if (
                    keys[0] not in a.feature_ids
                    or keys[1] not in b.feature_ids
                    or any(feature_kinds.get(key) != "edge" for key in keys)
                ):
                    reason = "feature_missing"
                else:
                    edges = [geometry[key] for key in keys]
                    if calibration is not None:
                        try:
                            edges = [
                                calibrated_points(
                                    map_points(edge, observations.image_from_reference),
                                    calibration,
                                )
                                for edge in edges
                            ]
                        except ValueError as exc:
                            reason = str(exc)
                    vectors = [edge[-1] - edge[0] for edge in edges]
                    product = np.linalg.norm(vectors[0]) * np.linalg.norm(vectors[1])
                    if product < 1e-10:
                        reason = "degenerate_direction"
                    elif reason is None:
                        value = float(
                            np.degrees(
                                np.arccos(
                                    np.clip(abs(np.dot(*vectors)) / product, -1, 1)
                                )
                            )
                        )
            else:
                endpoints = (
                    reference_point(a.center_image_point),
                    reference_point(b.center_image_point),
                )
            if endpoints is not None:
                delta = endpoints[1] - endpoints[0]
                image_points = map_points(endpoints, observations.image_from_reference)
                if calibration is not None:
                    try:
                        world = calibrated_points(image_points, calibration)
                        delta = world[1] - world[0]
                        if definition.distance_mode == "projected":
                            # 方向是 reference 像素方向；映射起点处的局部方向后进行有符号投影。
                            axis = map_unit_direction(
                                endpoints[0],
                                axis,
                                np.asarray(calibration.world_from_image)
                                @ np.asarray(observations.image_from_reference),
                            )
                    except ValueError as exc:
                        reason = str(exc)
                if reason is None:
                    value = float(
                        np.linalg.norm(delta)
                        if definition.distance_mode == "euclidean"
                        else delta @ axis
                    )
                    annotations.append(
                        {
                            "item_id": definition.item_id,
                            "point_a_xy": image_points[0].tolist(),
                            "point_b_xy": image_points[1].tolist(),
                            "label": f"{definition.item_id}: {value:.3f} {unit}",
                        }
                    )
        values.append(
            NumericItem(
                item_id=definition.item_id,
                unit=unit,
                value=value,
                valid=reason is None,
                reason=reason,
            )
        )
    table = NumericTable(observation_id=observations.observation_id, items=values)
    return {
        "measurements": table.model_dump(mode="json"),
        "summary": build_value_payload(numeric_table_to_value(table)),
        "annotations": build_value_payload(annotations),
    }
