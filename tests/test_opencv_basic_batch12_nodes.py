"""OpenCV 第十二批透视矫正节点测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes import ExecutionImageRegistry
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


def test_opencv_basic_batch12_perspective_transform_with_parameters_execute(tmp_path: Path) -> None:
    """验证 perspective-transform 可按固定四点把斜拍区域矫正到规则矩形。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/perspective-b12.png", _build_perspective_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch12-perspective-parameters",
        template_version="1.0.0",
        display_name="OpenCV Batch12 Perspective Parameters",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="warp",
                node_type_id="custom.opencv.perspective-transform",
                parameters={
                    "source_points": [[20, 20], [95, 12], [105, 70], [18, 78]],
                    "output_width": 80,
                    "output_height": 60,
                    "border_mode": "constant",
                    "border_value": 0,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-warp-b12",
                source_node_id="input",
                source_port="image",
                target_node_id="warp",
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
                output_id="warped_image",
                display_name="Warped Image",
                payload_type_id="image-ref.v1",
                source_node_id="warp",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="warp_summary",
                display_name="Warp Summary",
                payload_type_id="value.v1",
                source_node_id="warp",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/perspective-b12.png",
                "width": 120,
                "height": 90,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch12-perspective-parameters",
        },
    )

    warped_image = execution_result.outputs["warped_image"]
    warp_summary = execution_result.outputs["warp_summary"]

    warped_matrix = image_registry.read_matrix(str(warped_image["image_handle"]))
    assert warped_matrix is not None

    assert warped_image["transport_kind"] == "memory"
    assert warped_image["width"] == 80
    assert warped_image["height"] == 60
    assert warp_summary["value"]["source_kind"] == "parameters"
    assert warp_summary["value"]["output_width"] == 80
    assert warp_summary["value"]["output_height"] == 60
    assert warp_summary["value"]["output_size_source"] == "parameters"
    assert warped_matrix.shape[1] == 80
    assert warped_matrix.shape[0] == 60
    assert int(warped_matrix[3, 3, 2]) > 150
    assert int(warped_matrix[3, 76, 1]) > 150
    assert int(warped_matrix[56, 76, 0]) > 150
    assert int(warped_matrix[56, 3, 1]) > 150 and int(warped_matrix[56, 3, 2]) > 150


def test_opencv_basic_batch12_perspective_transform_with_roi_execute(tmp_path: Path) -> None:
    """验证 perspective-transform 可直接读取上游 roi.v1 polygon 输入。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/perspective-b12.png", _build_perspective_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch12-perspective-roi",
        template_version="1.0.0",
        display_name="OpenCV Batch12 Perspective ROI",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(node_id="roi_value", node_type_id="core.io.template-input.value"),
            WorkflowGraphNode(node_id="roi", node_type_id="core.vision.roi-create"),
            WorkflowGraphNode(node_id="warp", node_type_id="custom.opencv.perspective-transform"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-warp-roi-b12",
                source_node_id="input",
                source_port="image",
                target_node_id="warp",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-value-create-b12",
                source_node_id="roi_value",
                source_port="value",
                target_node_id="roi",
                target_port="value",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-warp-b12",
                source_node_id="roi",
                source_port="roi",
                target_node_id="warp",
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
            WorkflowGraphInput(
                input_id="request_roi",
                display_name="Request ROI",
                payload_type_id="value.v1",
                target_node_id="roi_value",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="warped_image",
                display_name="Warped Image",
                payload_type_id="image-ref.v1",
                source_node_id="warp",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="warp_summary",
                display_name="Warp Summary",
                payload_type_id="value.v1",
                source_node_id="warp",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/perspective-b12.png",
                "width": 120,
                "height": 90,
                "media_type": "image/png",
            },
            "request_roi": {
                "value": {
                    "roi_kind": "polygon",
                    "roi_id": "fixture-plane",
                    "display_name": "fixture-plane",
                    "polygon_xy": [[20, 20], [95, 12], [105, 70], [18, 78]],
                }
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch12-perspective-roi",
        },
    )

    warped_image = execution_result.outputs["warped_image"]
    warp_summary = execution_result.outputs["warp_summary"]

    warped_matrix = image_registry.read_matrix(str(warped_image["image_handle"]))
    assert warped_matrix is not None

    assert warped_image["transport_kind"] == "memory"
    assert warped_image["width"] == warp_summary["value"]["estimated_output_width"]
    assert warped_image["height"] == warp_summary["value"]["estimated_output_height"]
    assert warp_summary["value"]["source_kind"] == "roi"
    assert warp_summary["value"]["roi_id"] == "fixture-plane"
    assert warp_summary["value"]["roi_kind"] == "polygon"
    assert warp_summary["value"]["output_size_source"] == "estimated"
    assert int(warped_matrix[3, 3, 2]) > 150
    assert int(warped_matrix[3, warped_matrix.shape[1] - 4, 1]) > 150


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


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建本地 dataset storage。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files")))


def _build_perspective_test_png_bytes() -> bytes:
    """构造透视矫正测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((90, 120, 3), dtype=np.uint8)
    quadrilateral = np.array([[20, 20], [95, 12], [105, 70], [18, 78]], dtype=np.int32)
    cv2.fillConvexPoly(image, quadrilateral, (220, 220, 220))
    cv2.circle(image, (20, 20), 6, (0, 0, 255), thickness=-1)
    cv2.circle(image, (95, 12), 6, (0, 255, 0), thickness=-1)
    cv2.circle(image, (105, 70), 6, (255, 0, 0), thickness=-1)
    cv2.circle(image, (18, 78), 6, (0, 255, 255), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
