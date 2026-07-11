"""OpenCV 匹配节点运行时测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_opencv_matching_orb_homography_execute(tmp_path: Path) -> None:
    """验证 ORB 特征、匹配与 homography 可组成稳定的参考对位链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    reference_bytes, current_bytes, expected_homography = _build_orb_registration_pair_png_bytes()
    dataset_storage.write_bytes("inputs/orb-reference.png", reference_bytes)
    dataset_storage.write_bytes("inputs/orb-current.png", current_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-matching-orb-registration",
        template_version="1.0.0",
        display_name="OpenCV Matching ORB Registration",
        nodes=(
            WorkflowGraphNode(node_id="reference_input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(node_id="current_input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="orb_reference",
                node_type_id="custom.opencv.orb-keypoints",
                parameters={"max_features": 600},
            ),
            WorkflowGraphNode(
                node_id="orb_current",
                node_type_id="custom.opencv.orb-keypoints",
                parameters={"max_features": 600},
            ),
            WorkflowGraphNode(
                node_id="match",
                node_type_id="custom.opencv.orb-match",
                parameters={
                    "cross_check": False,
                    "ratio_test_threshold": 0.82,
                    "max_matches": 120,
                    "debug_image_panel_enabled": True,
                },
            ),
            WorkflowGraphNode(
                node_id="homography",
                node_type_id="custom.opencv.homography-estimate",
                parameters={
                    "method": "ransac",
                    "ransac_reprojection_threshold": 4.0,
                    "min_match_count": 12,
                    "debug_image_panel_enabled": True,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-reference-orb",
                source_node_id="reference_input",
                source_port="image",
                target_node_id="orb_reference",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-current-orb",
                source_node_id="current_input",
                source_port="image",
                target_node_id="orb_current",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-reference-match",
                source_node_id="orb_reference",
                source_port="features",
                target_node_id="match",
                target_port="features_a",
            ),
            WorkflowGraphEdge(
                edge_id="edge-current-match",
                source_node_id="orb_current",
                source_port="features",
                target_node_id="match",
                target_port="features_b",
            ),
            WorkflowGraphEdge(
                edge_id="edge-match-homography",
                source_node_id="match",
                source_port="matches",
                target_node_id="homography",
                target_port="matches",
            ),
            WorkflowGraphEdge(
                edge_id="edge-reference-homography",
                source_node_id="orb_reference",
                source_port="features",
                target_node_id="homography",
                target_port="features_a",
            ),
            WorkflowGraphEdge(
                edge_id="edge-current-homography",
                source_node_id="orb_current",
                source_port="features",
                target_node_id="homography",
                target_port="features_b",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_reference_image",
                display_name="Request Reference Image",
                payload_type_id="image-ref.v1",
                target_node_id="reference_input",
                target_port="payload",
            ),
            WorkflowGraphInput(
                input_id="request_current_image",
                display_name="Request Current Image",
                payload_type_id="image-ref.v1",
                target_node_id="current_input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="reference_features",
                display_name="Reference Features",
                payload_type_id="local-features.v1",
                source_node_id="orb_reference",
                source_port="features",
            ),
            WorkflowGraphOutput(
                output_id="current_features",
                display_name="Current Features",
                payload_type_id="local-features.v1",
                source_node_id="orb_current",
                source_port="features",
            ),
            WorkflowGraphOutput(
                output_id="matches",
                display_name="Matches",
                payload_type_id="feature-matches.v1",
                source_node_id="match",
                source_port="matches",
            ),
            WorkflowGraphOutput(
                output_id="transform",
                display_name="Transform",
                payload_type_id="planar-transform.v1",
                source_node_id="homography",
                source_port="transform",
            ),
            WorkflowGraphOutput(
                output_id="summary",
                display_name="Summary",
                payload_type_id="value.v1",
                source_node_id="homography",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_reference_image": {
                "object_key": "inputs/orb-reference.png",
                "width": 240,
                "height": 180,
                "media_type": "image/png",
            },
            "request_current_image": {
                "object_key": "inputs/orb-current.png",
                "width": 240,
                "height": 180,
                "media_type": "image/png",
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-matching-orb-registration",
            "debug_image_panels_enabled": True,
        },
    )

    reference_features = execution_result.outputs["reference_features"]
    current_features = execution_result.outputs["current_features"]
    matches = execution_result.outputs["matches"]
    transform = execution_result.outputs["transform"]
    summary = execution_result.outputs["summary"]

    assert reference_features["count"] >= 80
    assert current_features["count"] >= 80
    assert reference_features["descriptor_length"] == 32
    assert current_features["descriptor_norm"] == "hamming"
    assert matches["count"] >= 30
    assert matches["matcher_kind"] == "bf-hamming"
    assert transform["transform_kind"] == "homography"
    assert transform["match_count"] == matches["count"]
    assert transform["inlier_count"] >= 18
    assert summary["value"]["reprojection_error"] is not None
    assert float(summary["value"]["reprojection_error"]) < 4.0

    observed_homography = transform["matrix_3x3"]
    observed_corner_error = _compute_mean_corner_projection_error(
        homography_matrix=observed_homography,
        expected_homography=expected_homography,
        width=240,
        height=180,
    )
    assert observed_corner_error < 8.0
    match_debug_preview = _read_record_output(execution_result, node_id="match", output_name="debug_preview")
    homography_debug_preview = _read_record_output(
        execution_result,
        node_id="homography",
        output_name="debug_preview",
    )
    assert match_debug_preview["type"] == "image-preview"
    assert homography_debug_preview["type"] == "image-preview"
    assert len(match_debug_preview["overlays"]) > 0
    assert any(overlay.get("kind") == "line" for overlay in match_debug_preview["overlays"])
    assert any(overlay.get("kind") == "polygon" for overlay in homography_debug_preview["overlays"])


def test_opencv_matching_orb_keypoints_with_roi_execute(tmp_path: Path) -> None:
    """验证 ORB 特征提取可受 roi.v1 约束。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    reference_bytes, _current_bytes, _expected_homography = _build_orb_registration_pair_png_bytes()
    dataset_storage.write_bytes("inputs/orb-reference.png", reference_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-matching-orb-roi",
        template_version="1.0.0",
        display_name="OpenCV Matching ORB ROI",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi",
                node_type_id="core.vision.roi-create",
                parameters={
                    "roi_kind": "bbox",
                    "roi_id": "roi-left",
                    "bbox_xyxy": [10, 20, 110, 150],
                },
            ),
            WorkflowGraphNode(
                node_id="orb",
                node_type_id="custom.opencv.orb-keypoints",
                parameters={"max_features": 300, "use_roi_mask": True},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-roi-image",
                source_node_id="input",
                source_port="image",
                target_node_id="roi",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-orb-image",
                source_node_id="input",
                source_port="image",
                target_node_id="orb",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-orb",
                source_node_id="roi",
                source_port="roi",
                target_node_id="orb",
                target_port="roi",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image_base64",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="features",
                display_name="Features",
                payload_type_id="local-features.v1",
                source_node_id="orb",
                source_port="features",
            ),
            WorkflowGraphOutput(
                output_id="summary",
                display_name="Summary",
                payload_type_id="value.v1",
                source_node_id="orb",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/orb-reference.png",
                "width": 240,
                "height": 180,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-matching-orb-roi",
        },
    )

    features = execution_result.outputs["features"]
    summary = execution_result.outputs["summary"]
    assert features["count"] > 0
    assert features["roi_id"] == "roi-left"
    assert summary["value"]["roi_id"] == "roi-left"
    assert all(10.0 <= float(item["x"]) <= 110.0 for item in features["items"])
    assert all(20.0 <= float(item["y"]) <= 150.0 for item in features["items"])


def test_opencv_matching_orb_keypoints_with_search_bbox_execute(tmp_path: Path) -> None:
    """验证 ORB 特征提取可直接使用图片面板写回的 search_bbox_xyxy。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    reference_bytes, _current_bytes, _expected_homography = _build_orb_registration_pair_png_bytes()
    dataset_storage.write_bytes("inputs/orb-reference.png", reference_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-matching-orb-search-bbox",
        template_version="1.0.0",
        display_name="OpenCV Matching ORB Search BBox",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="orb",
                node_type_id="custom.opencv.orb-keypoints",
                parameters={
                    "max_features": 300,
                    "use_roi_mask": True,
                    "search_bbox_xyxy": [10, 20, 110, 150],
                    "debug_image_panel_enabled": True,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-orb-image",
                source_node_id="input",
                source_port="image",
                target_node_id="orb",
                target_port="image",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image_base64",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="features",
                display_name="Features",
                payload_type_id="local-features.v1",
                source_node_id="orb",
                source_port="features",
            ),
            WorkflowGraphOutput(
                output_id="summary",
                display_name="Summary",
                payload_type_id="value.v1",
                source_node_id="orb",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/orb-reference.png",
                "width": 240,
                "height": 180,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-matching-orb-search-bbox",
            "debug_image_panels_enabled": True,
        },
    )

    features = execution_result.outputs["features"]
    summary = execution_result.outputs["summary"]
    debug_preview = _read_record_output(execution_result, node_id="orb", output_name="debug_preview")
    interaction = debug_preview["interaction"]
    bbox_tool = next(tool for tool in interaction["tools"] if tool["tool"] == "bbox")

    assert features["count"] > 0
    assert summary["value"]["search_roi_source"] == "parameter"
    assert summary["value"]["search_bbox_xyxy"] == [10, 20, 110, 150]
    assert all(10.0 <= float(item["x"]) <= 110.0 for item in features["items"])
    assert all(20.0 <= float(item["y"]) <= 150.0 for item in features["items"])
    assert debug_preview["type"] == "image-preview"
    assert bbox_tool["target_parameters"] == ["search_bbox_xyxy"]
    assert any(overlay.get("id") == "search-roi" for overlay in debug_preview["overlays"])


def _create_repository_executor() -> WorkflowGraphExecutor:
    """创建绑定仓库 custom_nodes 的 workflow 执行器。"""

    custom_nodes_root_dir = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=NodeCatalogRegistry(node_pack_loader=node_pack_loader),
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()
    return WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())


def _read_record_output(
    execution_result,
    *,
    node_id: str,
    output_name: str,
) -> dict[str, object]:
    """从节点执行记录中读取指定输出。"""

    for record in execution_result.node_records:
        if record.node_id == node_id:
            output_payload = record.outputs.get(output_name)
            assert isinstance(output_payload, dict)
            return output_payload
    raise AssertionError(f"node record not found: {node_id}")


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建本地 dataset storage。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files")))


def _build_orb_registration_pair_png_bytes() -> tuple[bytes, bytes, list[list[float]]]:
    """构造可稳定生成 ORB 匹配与 homography 的测试图片对。"""

    import cv2
    import numpy as np

    reference_image = np.zeros((180, 240, 3), dtype=np.uint8)
    cv2.rectangle(reference_image, (18, 18), (86, 86), (255, 255, 255), thickness=2)
    cv2.circle(reference_image, (60, 52), 16, (255, 255, 255), thickness=2)
    cv2.line(reference_image, (22, 120), (108, 150), (255, 255, 255), thickness=2)
    cv2.putText(
        reference_image,
        "A7",
        (124, 54),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.rectangle(reference_image, (132, 76), (214, 144), (255, 255, 255), thickness=2)
    cv2.line(reference_image, (132, 76), (214, 144), (255, 255, 255), thickness=2)
    cv2.line(reference_image, (214, 76), (132, 144), (255, 255, 255), thickness=2)
    rng = np.random.default_rng(42)
    for _index in range(36):
        point_x = int(rng.integers(10, 230))
        point_y = int(rng.integers(10, 170))
        cv2.circle(reference_image, (point_x, point_y), 1, (255, 255, 255), thickness=-1)

    homography_matrix = np.array(
        [
            [1.015, 0.038, 12.0],
            [-0.028, 1.026, 10.0],
            [0.00018, 0.00052, 1.0],
        ],
        dtype=np.float32,
    )
    current_image = cv2.warpPerspective(reference_image, homography_matrix, (240, 180))

    reference_success, reference_encoded = cv2.imencode(".png", reference_image)
    current_success, current_encoded = cv2.imencode(".png", current_image)
    assert reference_success is True
    assert current_success is True
    return reference_encoded.tobytes(), current_encoded.tobytes(), homography_matrix.tolist()


def _compute_mean_corner_projection_error(
    *,
    homography_matrix: list[list[float]],
    expected_homography: list[list[float]],
    width: int,
    height: int,
) -> float:
    """比较观测 homography 与预期 homography 在四角投影上的平均偏差。"""

    import numpy as np

    corner_points = np.array(
        [
            [0.0, 0.0, 1.0],
            [float(width - 1), 0.0, 1.0],
            [float(width - 1), float(height - 1), 1.0],
            [0.0, float(height - 1), 1.0],
        ],
        dtype=np.float32,
    )
    observed_matrix = np.array(homography_matrix, dtype=np.float32)
    expected_matrix = np.array(expected_homography, dtype=np.float32)
    observed_projected = (observed_matrix @ corner_points.T).T
    expected_projected = (expected_matrix @ corner_points.T).T
    observed_projected = observed_projected[:, :2] / observed_projected[:, 2:3]
    expected_projected = expected_projected[:, :2] / expected_projected[:, 2:3]
    distances = np.linalg.norm(observed_projected - expected_projected, axis=1)
    return float(distances.mean())
