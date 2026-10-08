"""Pin Array Locate：固定身份的有界局部观测，不计算最终业务 OK/NG。"""

from dataclasses import fields
import math
from uuid import uuid4

import cv2
import numpy as np

from backend.contracts.workflows.metrology import (
    FeatureObservations,
    GeometricFeature,
    NumericItem,
    NumericTable,
    PoseObservation,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    is_debug_image_panel_enabled,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from custom_nodes.opencv_nodes.shared.backend.metrology import (
    EdgePairSettings,
    extract_band_pairs,
    extract_edge_pair,
    map_points,
    measure_section,
    prepare_gray,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.connector_nodes.shared.contracts import (
    PinLayout,
    PinObservation,
    PinObservations,
)
from custom_nodes.connector_nodes.shared.runtime import image_identity, parse

NODE_TYPE_ID = "custom.connector.pin-array-locate"


def handle_node(request) -> dict:
    """按显式布局与位姿扫描；原图只借用一次，未发现不更改 PIN 身份。"""
    control = build_node_execution_control(request)
    control.raise_if_cancelled_or_expired()
    layout = parse(PinLayout, request.parameters.get("layout"))
    mode = request.parameters.get("pose_mode", "input")
    if mode not in {"fixed", "input"}:
        raise InvalidRequestError("Pose Mode 必须为 fixed 或 input")
    payload, _, image = load_image_matrix(request, imdecode_flags=cv2.IMREAD_UNCHANGED)
    identity = image_identity(request, payload, image)
    matrix = np.eye(3)
    pose_reason = None
    if mode == "input":
        pose = parse(PoseObservation, request.input_values.get("pose"))
        if (
            pose.image != identity
            or pose.reference_id != layout.reference_id
            or pose.reference_sha256 != layout.reference_sha256
        ):
            raise InvalidRequestError("Pose 与原图/参考布局身份不一致")
        pose_reason = pose.reason
        if pose.state == "found":
            matrix = np.asarray(pose.image_from_reference)
    observation_id = uuid4().hex
    try:
        gray = prepare_gray(image) if pose_reason is None else None
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    types = {t.type_id: t for t in layout.types}
    positions = map_points([p.center for p in layout.pins], matrix)
    features, pins, checks, regions = [], [], [], []
    claims = []
    samples_used = 0
    debug_enabled = is_debug_image_panel_enabled(request)
    selected_diagnostic = {} if debug_enabled and layout.diagnostic_pin_id else None

    def consume_samples(count):
        """候选复核与名义扫描共用单次预算，发现过量时失败而非截断。"""
        nonlocal samples_used
        samples_used += count
        if samples_used > 4_000_000:
            raise InvalidRequestError("本次扫描总量超过 4000000，请缩小候选范围")

    def settings_for(scan):
        """行业采样类型转换为通用算法配置。"""
        return EdgePairSettings(
            **{f.name: getattr(scan, f.name) for f in fields(EdgePairSettings)}
        )

    def direction_for(scan):
        """参考方向只随本次刚性定位旋转。"""
        angle = math.radians(scan.angle_degrees)
        return matrix[:2, :2] @ np.array([math.cos(angle), math.sin(angle)])

    def scan_pair(scan, center, diagnostics=None):
        """在共享预算中提取一次边缘对。"""
        consume_samples(
            (math.ceil(scan.search_length / scan.sample_step) + 1) * scan.scan_lines
        )
        try:
            return extract_edge_pair(
                gray,
                center,
                direction_for(scan),
                settings_for(scan),
                check=control.raise_if_cancelled_or_expired,
                diagnostics=diagnostics,
            )
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc

    for pin, center in zip(layout.pins, positions):
        control.raise_if_cancelled_or_expired()
        scan = types[pin.pin_type]
        if pose_reason is None:
            result = scan_pair(
                scan,
                center,
                selected_diagnostic if pin.pin_id == layout.diagnostic_pin_id else None,
            )
        else:
            result = {"state": "not_evaluated", "reason": pose_reason}
        pin_features = []
        if result["state"] == "found":
            # 局部搜索窗口即使重叠，同一个物理候选也不能分配给两个 PIN。
            duplicate = next(
                (
                    index
                    for index, point in claims
                    if np.linalg.norm(np.array(point) - result["center"]) < 1.0
                ),
                None,
            )
            if duplicate is not None:
                old = pins[duplicate]
                features = [f for f in features if f.feature_id not in old.feature_ids]
                pins[duplicate] = PinObservation(
                    **(
                        old.model_dump()
                        | {
                            "state": "ambiguous",
                            "center_image_point": None,
                            "feature_ids": (),
                            "reason": "candidate_already_assigned",
                        }
                    )
                )
                checks[duplicate] = NumericItem(
                    item_id="presence:" + old.pin_id,
                    unit="unitless",
                    value=None,
                    valid=False,
                    reason="candidate_already_assigned",
                )
                regions[duplicate] = regions[duplicate] | {
                    "state": "ambiguous",
                    "center": None,
                }
                result = {"state": "ambiguous", "reason": "candidate_already_assigned"}
            else:
                for name in ("left", "right"):
                    feature_id = pin.pin_id + ":" + name
                    features.append(
                        GeometricFeature(
                            feature_id=feature_id,
                            kind="edge",
                            points=result[name],
                            residual_px=result["residual_px"],
                        )
                    )
                    pin_features.append(feature_id)
                feature_id = pin.pin_id + ":center"
                features.append(
                    GeometricFeature(
                        feature_id=feature_id, kind="point", points=(result["center"],)
                    )
                )
                pin_features.append(feature_id)
                for pair in pin.endpoint_pairs:
                    endpoint_scan = types[pair.sampling_type]
                    endpoint_center = center + matrix[:2, :2] @ np.asarray(
                        pair.center_offset
                    )
                    endpoints = scan_pair(endpoint_scan, endpoint_center)
                    if endpoints["state"] != "found":
                        continue
                    axis = direction_for(endpoint_scan)
                    section = float(endpoint_center @ np.array([-axis[1], axis[0]]))
                    for name, side in (
                        (pair.first_id, "left"),
                        (pair.second_id, "right"),
                    ):
                        point = measure_section(endpoints[side], axis, section)
                        if point is not None:
                            identifier = pin.pin_id + ":" + name
                            features.append(
                                GeometricFeature(
                                    feature_id=identifier,
                                    kind="point",
                                    points=[point.tolist()],
                                    residual_px=endpoints["residual_px"],
                                )
                            )
                            pin_features.append(identifier)
                claims.append((len(pins), result["center"]))
        state = result["state"]
        pins.append(
            PinObservation(
                pin_id=pin.pin_id,
                row_id=pin.row_id,
                pin_type=pin.pin_type,
                expected_present=pin.expected_present,
                nominal_image_point=center.tolist(),
                state=state,
                center_image_point=result.get("center"),
                feature_ids=pin_features,
                reason=result["reason"],
            )
        )
        valid = state in {"found", "not_found"}
        matches = (state == "found") == pin.expected_present
        checks.append(
            NumericItem(
                item_id="presence:" + pin.pin_id,
                unit="unitless",
                value=float(matches) if valid else None,
                valid=valid,
                reason=None if valid else result["reason"],
            )
        )
        regions.append(
            {
                "pin_id": pin.pin_id,
                "state": state,
                "center": result.get("center"),
                "expected_present": pin.expected_present,
            }
        )
    unassigned, band_results = [], []
    feature_index = {feature.feature_id: feature for feature in features}

    def owns_candidate(pin, candidate, axis):
        """仅在已观测有限边缘内比较同截面的两侧；不把不同截面的中心误当额外 PIN。"""
        if pin.state != "found":
            return False
        point = np.asarray(candidate["center"])
        section = float(point @ np.array([-axis[1], axis[0]]))
        for side in ("left", "right"):
            feature = feature_index.get(pin.pin_id + ":" + side)
            if feature is None:
                return False
            observed = measure_section(feature.points, axis, section)
            candidate_point = measure_section(candidate[side], axis, section)
            if (
                observed is None
                or candidate_point is None
                or np.linalg.norm(observed - candidate_point) > 1.5
            ):
                return False
        return True

    for band in layout.candidate_bands:
        control.raise_if_cancelled_or_expired()
        if pose_reason is not None:
            band_result = {
                "state": "not_evaluated",
                "reason": pose_reason,
                "candidates": [],
            }
        else:
            scan = types[band.sampling_type]
            consume_samples(
                (math.ceil(band.length / scan.sample_step) + 1) * scan.scan_lines
            )
            try:
                band_result = extract_band_pairs(
                    gray,
                    map_points([band.center], matrix)[0],
                    direction_for(scan),
                    band.length,
                    settings_for(scan),
                    check=control.raise_if_cancelled_or_expired,
                    consume_samples=consume_samples,
                )
            except ValueError as exc:
                raise InvalidRequestError(str(exc)) from exc
        extras = []
        for candidate in band_result["candidates"]:
            point = np.asarray(candidate["center"])
            owners = [
                p
                for p in pins
                if owns_candidate(
                    p, candidate, direction_for(types[band.sampling_type])
                )
            ]
            if len(owners) > 1:
                band_result["state"], band_result["reason"] = (
                    "ambiguous",
                    "candidate_already_assigned",
                )
            if not owners:
                extras.append(point.tolist())
                if not any(
                    np.linalg.norm(point - other) <= 1.5 for other in unassigned
                ):
                    unassigned.append(point.tolist())
        if len(unassigned) > 2048:
            raise InvalidRequestError("未归属候选超过 2048")
        valid = band_result["state"] == "found"
        checks.append(
            NumericItem(
                item_id="extra:" + band.band_id,
                unit="unitless",
                value=float(len(extras)) if valid else None,
                valid=valid,
                reason=band_result["reason"],
            )
        )
        band_results.append(
            {
                "band_id": band.band_id,
                "state": band_result["state"],
                "reason": band_result["reason"],
                "extra_count": len(extras) if valid else None,
            }
        )
    observations = PinObservations(
        observation_id=observation_id,
        image=identity,
        reference_id=layout.reference_id,
        pins=pins,
        image_from_reference=matrix.tolist(),
        unassigned_points=unassigned,
    )
    geometry = FeatureObservations(
        observation_id=observation_id,
        image=identity,
        reference_id=layout.reference_id,
        features=features,
    )
    observations.require_matching_features(geometry)
    outputs = {
        "pins": observations.model_dump(mode="json"),
        "features": geometry.model_dump(mode="json"),
        "checks": NumericTable(observation_id=observation_id, items=checks).model_dump(
            mode="json"
        ),
        "summary": build_value_payload(
            {
                "observation_id": observation_id,
                "pins": regions,
                "found_count": sum(p.state == "found" for p in pins),
                "extra_search_performed": bool(layout.candidate_bands),
                "candidate_bands": band_results,
                "unassigned_points": unassigned,
            }
        ),
    }
    if debug_enabled:
        # 原图和几何走既有 Preview 内存显示通道；生产调用没有此分支。
        overlays = [
            {
                "kind": "point",
                "id": pin.pin_id,
                "label": f"{pin.pin_id}: {pin.state}",
                "points_xy": [pin.center_image_point or pin.nominal_image_point],
            }
            for pin in pins
        ]
        overlays.extend(
            {
                "kind": "line",
                "id": feature.feature_id,
                "label": feature.feature_id,
                "line_xyxy": [*feature.points[0], *feature.points[-1]],
            }
            for feature in features
            if feature.kind == "edge"
        )
        outputs.update(
            build_debug_image_preview_output(
                request,
                image_payload=payload,
                title="Pin Array Locate",
                overlays=overlays,
            )
        )
        body = outputs["debug_preview"]
        body["layout_snapshot"] = request.parameters["layout"]
        if selected_diagnostic is not None:
            selected = next(
                pin for pin in pins if pin.pin_id == layout.diagnostic_pin_id
            )
            body["sampling_diagnostic"] = {
                **selected_diagnostic,
                "pin_id": selected.pin_id,
                "state": selected.state,
                "reason": selected.reason,
                "image": identity.model_dump(mode="json"),
                "observation_id": observation_id,
            }
    return outputs
