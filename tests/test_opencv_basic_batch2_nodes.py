"""OpenCV 第二批工业扩展节点测试。"""

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


def test_opencv_basic_batch2_diff_component_nodes_execute(tmp_path: Path) -> None:
    """验证 image-diff、absdiff-threshold 与 connected-components 可接成缺陷区域链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    reference_image_bytes, current_image_bytes = _build_diff_pair_test_png_bytes()
    dataset_storage.write_bytes("inputs/reference.png", reference_image_bytes)
    dataset_storage.write_bytes("inputs/current.png", current_image_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch2-diff-components",
        template_version="1.0.0",
        display_name="OpenCV Batch2 Diff Components",
        nodes=(
            WorkflowGraphNode(
                node_id="diff",
                node_type_id="custom.opencv.image-diff",
                parameters={"diff_mode": "grayscale"},
            ),
            WorkflowGraphNode(
                node_id="threshold",
                node_type_id="custom.opencv.absdiff-threshold",
                parameters={"threshold": 20, "threshold_type": "binary"},
            ),
            WorkflowGraphNode(
                node_id="components",
                node_type_id="custom.opencv.connected-components",
                parameters={
                    "foreground_threshold": 0,
                    "connectivity": 8,
                    "min_area": 20.0,
                    "region_id_prefix": "def",
                    "class_id_default": 11,
                    "class_name_default": "difference",
                    "score_default": 0.88,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-diff-threshold",
                source_node_id="diff",
                source_port="image",
                target_node_id="threshold",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-threshold-components",
                source_node_id="threshold",
                source_port="image",
                target_node_id="components",
                target_port="image",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image_base64",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="diff",
                target_port="image",
            ),
            WorkflowGraphInput(
                input_id="request_reference_image",
                display_name="Request Reference Image",
                payload_type_id="image-ref.v1",
                target_node_id="diff",
                target_port="reference_image",
            ),
            WorkflowGraphInput(
                input_id="request_source_image",
                display_name="Request Source Image",
                payload_type_id="image-ref.v1",
                target_node_id="components",
                target_port="source_image",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="diff_image",
                display_name="Diff Image",
                payload_type_id="image-ref.v1",
                source_node_id="diff",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="diff_summary",
                display_name="Diff Summary",
                payload_type_id="value.v1",
                source_node_id="diff",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="threshold_image",
                display_name="Threshold Image",
                payload_type_id="image-ref.v1",
                source_node_id="threshold",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="threshold_summary",
                display_name="Threshold Summary",
                payload_type_id="value.v1",
                source_node_id="threshold",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
                source_node_id="components",
                source_port="regions",
            ),
            WorkflowGraphOutput(
                output_id="regions_summary",
                display_name="Regions Summary",
                payload_type_id="value.v1",
                source_node_id="components",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/current.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            },
            "request_reference_image": {
                "object_key": "inputs/reference.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            },
            "request_source_image": {
                "object_key": "inputs/current.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch2-diff-components",
        },
    )

    diff_image = execution_result.outputs["diff_image"]
    diff_summary = execution_result.outputs["diff_summary"]
    threshold_image = execution_result.outputs["threshold_image"]
    threshold_summary = execution_result.outputs["threshold_summary"]
    regions = execution_result.outputs["regions"]
    regions_summary = execution_result.outputs["regions_summary"]

    assert diff_image["transport_kind"] == "memory"
    assert threshold_image["transport_kind"] == "memory"
    assert image_registry.read_matrix(str(diff_image["image_handle"])) is not None
    assert image_registry.read_matrix(str(threshold_image["image_handle"])) is not None
    assert diff_summary["value"]["diff_mode"] == "grayscale"
    assert diff_summary["value"]["non_zero_pixel_count"] > 0
    assert threshold_summary["value"]["foreground_pixel_count"] > 0
    assert threshold_summary["value"]["foreground_ratio"] > 0
    assert regions["count"] == 2
    assert regions["source_image"]["object_key"] == "inputs/current.png"
    assert regions_summary["value"]["region_count"] == 2
    assert regions_summary["value"]["class_name_default"] == "difference"
    assert regions_summary["value"]["total_area"] > 0
    assert regions["items"][0]["class_id"] == 11
    assert regions["items"][0]["class_name"] == "difference"
    assert regions["items"][0]["score"] == 0.88
    assert regions["items"][0]["region_id"].startswith("def-")
    assert regions["items"][0]["mask_image"]["transport_kind"] == "memory"
    assert len(regions["items"][0]["polygon_xy"]) >= 3


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


def _build_diff_pair_test_png_bytes() -> tuple[bytes, bytes]:
    """构建一对可稳定产生两个差异区域的测试图片。"""

    import cv2
    import numpy as np

    reference_image = np.zeros((96, 96, 3), dtype=np.uint8)
    current_image = np.zeros((96, 96, 3), dtype=np.uint8)
    cv2.rectangle(reference_image, (10, 10), (30, 30), (200, 200, 200), thickness=-1)
    cv2.rectangle(current_image, (10, 10), (30, 30), (200, 200, 200), thickness=-1)
    cv2.circle(current_image, (68, 24), 8, (255, 255, 255), thickness=-1)
    cv2.rectangle(current_image, (56, 60), (80, 78), (180, 180, 180), thickness=-1)

    reference_success, reference_encoded = cv2.imencode(".png", reference_image)
    current_success, current_encoded = cv2.imencode(".png", current_image)
    assert reference_success is True
    assert current_success is True
    return reference_encoded.tobytes(), current_encoded.tobytes()
