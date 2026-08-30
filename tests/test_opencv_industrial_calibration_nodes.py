"""工业单目诊断、双目标定和校正 map 链路测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
from jsonschema import Draft202012Validator
import numpy as np
import pytest

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import register_image_matrix
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.camera_calibrate import (
    handle_node as handle_camera_calibrate,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.industrial_calibration import (
    INDUSTRIAL_CALIBRATION_NODE_HANDLERS,
    handle_calibration_diagnose,
    handle_image_rectify_stereo,
    handle_observation_filter,
    handle_rectification_map,
    handle_stereo_calibrate,
    handle_stereo_rectify,
)
from custom_nodes.opencv_nodes.shared.workflow.payload_contracts import (
    load_shared_opencv_payload_contracts_payload,
)


def _request(
    registry: ExecutionImageRegistry,
    *,
    parameters: dict[str, object] | None = None,
    input_values: dict[str, object] | None = None,
    storage: LocalDatasetStorage | None = None,
) -> WorkflowNodeExecutionRequest:
    """构造标定节点执行请求。"""

    metadata: dict[str, object] = {"execution_image_registry": registry}
    if storage is not None:
        metadata["dataset_storage"] = storage
    return WorkflowNodeExecutionRequest(
        node_id="calibration-phase4-test",
        node_definition=object(),
        parameters=dict(parameters or {}),
        input_values=dict(input_values or {}),
        execution_metadata=metadata,
    )


def _synthetic_observations() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """生成已知内参和 120 mm baseline 的配对棋盘观察。"""

    camera_matrix = np.asarray(
        [[800.0, 0.0, 320.0], [0.0, 805.0, 240.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    distortion = np.zeros(5, dtype=np.float64)
    object_points = np.zeros((30, 3), dtype=np.float32)
    object_points[:, :2] = np.mgrid[0:6, 0:5].T.reshape(-1, 2) * 20.0
    monocular = []
    paired = []
    stereo_rotation = np.eye(3, dtype=np.float64)
    stereo_translation = np.asarray([-120.0, 0.0, 0.0], dtype=np.float64)
    for index in range(6):
        rotation_vector = np.asarray(
            [0.03 * index, -0.02 * index, 0.01 * index],
            dtype=np.float64,
        )
        translation_vector = np.asarray(
            [-40.0 + 14.0 * index, -30.0 + 8.0 * index, 850.0 + 35.0 * index],
            dtype=np.float64,
        )
        left_points, _ = cv2.projectPoints(
            object_points,
            rotation_vector,
            translation_vector,
            camera_matrix,
            distortion,
        )
        object_rotation, _ = cv2.Rodrigues(rotation_vector)
        right_rotation = stereo_rotation @ object_rotation
        right_rotation_vector, _ = cv2.Rodrigues(right_rotation)
        right_translation = stereo_rotation @ translation_vector + stereo_translation
        right_points, _ = cv2.projectPoints(
            object_points,
            right_rotation_vector,
            right_translation,
            camera_matrix,
            distortion,
        )
        common = {
            "observation_id": f"view-{index + 1}",
            "image_size": [640, 480],
            "object_points": object_points.astype(float).tolist(),
        }
        monocular.append(
            {**common, "image_points": left_points.reshape(-1, 2).astype(float).tolist()}
        )
        paired.append(
            {
                **common,
                "left_image_points": left_points.reshape(-1, 2).astype(float).tolist(),
                "right_image_points": right_points.reshape(-1, 2).astype(float).tolist(),
            }
        )
    return monocular, paired


def _calibrate_camera(
    registry: ExecutionImageRegistry,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    """从结构化观察建立 canonical camera-calibration.v1。"""

    return handle_camera_calibrate(
        _request(
            registry,
            parameters={"min_views": 3, "object_point_unit": "millimeter"},
            input_values={"observations": build_value_payload({"items": observations})},
        )
    )["camera_calibration"]


def test_calibration_catalog_handler_set_is_complete() -> None:
    """验证阶段 4 六个新节点 handler 完整。"""

    assert {item[0] for item in INDUSTRIAL_CALIBRATION_NODE_HANDLERS} == {
        "custom.opencv.calibration-observation-filter",
        "custom.opencv.calibration-diagnose",
        "custom.opencv.stereo-calibrate",
        "custom.opencv.stereo-rectify",
        "custom.opencv.rectification-map",
        "custom.opencv.image-rectify-stereo",
    }


def test_camera_calibration_filter_and_diagnose_use_canonical_payload() -> None:
    """验证观察筛选、单目标定与误差诊断完整闭环。"""

    registry = ExecutionImageRegistry()
    observations, _ = _synthetic_observations()
    duplicate = dict(observations[0])
    duplicate["observation_id"] = "duplicate"
    filtered = handle_observation_filter(
        _request(
            registry,
            parameters={
                "minimum_coverage_ratio": 0.0,
                "minimum_center_distance_ratio": 1e-9,
            },
            input_values={
                "observations": build_value_payload(
                    {"items": [*observations, duplicate]}
                )
            },
        )
    )
    assert filtered["observations"]["value"]["count"] == len(observations)
    assert filtered["diagnostics"]["value"]["rejected_count"] == 1

    calibration = _calibrate_camera(registry, observations)
    assert calibration["camera_model"] == "pinhole"
    assert calibration["observation_count"] == len(observations)
    assert calibration["rms_reprojection_error"] < 1e-3
    diagnostics = handle_calibration_diagnose(
        _request(
            registry,
            parameters={"maximum_reprojection_error": 0.01},
            input_values={
                "camera_calibration": calibration,
                "observations": build_value_payload({"items": observations}),
            },
        )
    )["diagnostics"]["value"]
    assert diagnostics["overall_rms_reprojection_error"] < 1e-3
    assert diagnostics["outlier_indices"] == []


def test_stereo_calibration_rectification_map_and_apply(tmp_path: Path) -> None:
    """验证双目标定、校正参数、ObjectStore map 和每帧应用。"""

    registry = ExecutionImageRegistry()
    observations, paired = _synthetic_observations()
    left = _calibrate_camera(registry, observations)
    right_observations = [
        {
            **item,
            "image_points": paired[index]["right_image_points"],
        }
        for index, item in enumerate(observations)
    ]
    right = _calibrate_camera(registry, right_observations)
    stereo = handle_stereo_calibrate(
        _request(
            registry,
            input_values={
                "left_camera": left,
                "right_camera": right,
                "observations": build_value_payload({"items": paired}),
            },
        )
    )["stereo_calibration"]
    assert stereo["translation_3"][0] == pytest.approx(-120.0, abs=1.0)
    assert stereo["rms_epipolar_error"] < 1e-3

    rectified = handle_stereo_rectify(
        _request(
            registry,
            input_values={"stereo_calibration": stereo},
        )
    )["stereo_calibration"]
    assert len(rectified["rectification"]["disparity_to_depth_4x4"]) == 4

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=tmp_path / "objects"))
    with_maps = handle_rectification_map(
        _request(
            registry,
            storage=storage,
            parameters={"save_location": "calibration/stereo-test"},
            input_values={"stereo_calibration": rectified},
        )
    )
    map_keys = with_maps["stereo_calibration"]["rectification"]["map_object_keys"]
    assert set(map_keys) == {
        "left_map_x",
        "left_map_y",
        "right_map_x",
        "right_map_y",
    }
    assert all(storage.resolve(str(key)).is_file() for key in map_keys.values())

    image = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.circle(image, (320, 240), 80, (0, 255, 0), 5)
    left_payload = register_image_matrix(_request(registry), image_matrix=image)
    right_payload = register_image_matrix(_request(registry), image_matrix=image)
    output = handle_image_rectify_stereo(
        _request(
            registry,
            storage=storage,
            input_values={
                "left_image": left_payload,
                "right_image": right_payload,
                "stereo_calibration": with_maps["stereo_calibration"],
            },
        )
    )
    left_matrix = registry.read_matrix(str(output["left_image"]["image_handle"]))
    right_matrix = registry.read_matrix(str(output["right_image"]["image_handle"]))
    assert left_matrix.shape == image.shape
    assert right_matrix.shape == image.shape

    contracts = {
        item["payload_type_id"]: item
        for item in load_shared_opencv_payload_contracts_payload()
    }
    camera_validator = Draft202012Validator(
        contracts["camera-calibration.v1"]["json_schema"]
    )
    stereo_validator = Draft202012Validator(
        contracts["stereo-calibration.v1"]["json_schema"]
    )
    assert list(camera_validator.iter_errors(left)) == []
    assert list(stereo_validator.iter_errors(with_maps["stereo_calibration"])) == []
