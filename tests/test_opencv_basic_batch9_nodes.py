"""OpenCV 第九批 caliper-edge 节点测试。"""

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


def test_opencv_basic_batch9_caliper_edge_vertical_execute(tmp_path: Path) -> None:
    """验证 caliper-edge 可检测纵向台阶边并输出单条 line。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    source_bytes = _build_caliper_vertical_test_png_bytes()
    dataset_storage.write_bytes("inputs/caliper-vertical.png", source_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch9-caliper-vertical",
        template_version="1.0.0",
        display_name="OpenCV Batch9 Caliper Vertical",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="caliper",
                node_type_id="custom.opencv.caliper-edge",
                parameters={
                    "edge_orientation": "vertical",
                    "edge_polarity": "dark-to-bright",
                    "profile_reduction": "mean",
                    "smoothing_kernel_size": 5,
                    "gradient_threshold": 5.0,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-caliper-b9",
                source_node_id="input",
                source_port="image",
                target_node_id="caliper",
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
                output_id="lines",
                display_name="Lines",
                payload_type_id="lines.v1",
                source_node_id="caliper",
                source_port="lines",
            ),
            WorkflowGraphOutput(
                output_id="summary",
                display_name="Summary",
                payload_type_id="value.v1",
                source_node_id="caliper",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/caliper-vertical.png",
                "width": 128,
                "height": 96,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-batch9-caliper-vertical",
        },
    )

    lines = execution_result.outputs["lines"]
    summary = execution_result.outputs["summary"]

    assert lines["count"] == 1
    line_item = lines["items"][0]
    assert 47.0 <= float(line_item["start_xy"][0]) <= 49.5
    assert 47.0 <= float(line_item["end_xy"][0]) <= 49.5
    assert float(line_item["length_pixels"]) >= 95.0
    assert round(abs(float(line_item["angle_deg"])), 4) == 90.0
    assert summary["value"]["found"] is True
    assert summary["value"]["edge_orientation"] == "vertical"
    assert summary["value"]["edge_polarity"] == "dark-to-bright"
    assert summary["value"]["line_count"] == 1
    assert 47.0 <= float(summary["value"]["best_edge_coordinate"]) <= 49.5
    assert "roi_id" not in summary["value"]


def test_opencv_basic_batch9_caliper_edge_horizontal_with_roi_execute(tmp_path: Path) -> None:
    """验证 caliper-edge 可在 ROI 内检测横向边。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    source_bytes = _build_caliper_horizontal_test_png_bytes()
    dataset_storage.write_bytes("inputs/caliper-horizontal.png", source_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch9-caliper-horizontal",
        template_version="1.0.0",
        display_name="OpenCV Batch9 Caliper Horizontal",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi",
                node_type_id="core.vision.roi-create",
                parameters={
                    "roi_kind": "bbox",
                    "roi_id": "step-window",
                    "display_name": "step-window",
                    "bbox_xyxy": [12, 40, 112, 96],
                },
            ),
            WorkflowGraphNode(
                node_id="caliper",
                node_type_id="custom.opencv.caliper-edge",
                parameters={
                    "edge_orientation": "horizontal",
                    "edge_polarity": "dark-to-bright",
                    "profile_reduction": "mean",
                    "smoothing_kernel_size": 5,
                    "gradient_threshold": 5.0,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-roi-image-b9",
                source_node_id="input",
                source_port="image",
                target_node_id="roi",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-caliper-horizontal-b9",
                source_node_id="input",
                source_port="image",
                target_node_id="caliper",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-caliper-horizontal-b9",
                source_node_id="roi",
                source_port="roi",
                target_node_id="caliper",
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
                output_id="lines",
                display_name="Lines",
                payload_type_id="lines.v1",
                source_node_id="caliper",
                source_port="lines",
            ),
            WorkflowGraphOutput(
                output_id="summary",
                display_name="Summary",
                payload_type_id="value.v1",
                source_node_id="caliper",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/caliper-horizontal.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-batch9-caliper-horizontal",
        },
    )

    lines = execution_result.outputs["lines"]
    summary = execution_result.outputs["summary"]

    assert lines["count"] == 1
    line_item = lines["items"][0]
    assert 71.0 <= float(line_item["start_xy"][1]) <= 73.5
    assert 71.0 <= float(line_item["end_xy"][1]) <= 73.5
    assert float(line_item["length_pixels"]) >= 99.0
    assert round(abs(float(line_item["angle_deg"])), 4) == 0.0
    assert summary["value"]["found"] is True
    assert summary["value"]["edge_orientation"] == "horizontal"
    assert summary["value"]["roi_id"] == "step-window"
    assert summary["value"]["roi_kind"] == "bbox"
    assert summary["value"]["search_bbox_xyxy"] == [12, 40, 112, 96]
    assert summary["value"]["roi_polygon_bbox_only"] is False
    assert 71.0 <= float(summary["value"]["best_edge_coordinate"]) <= 73.5


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


def _build_caliper_vertical_test_png_bytes() -> bytes:
    """构造纵向台阶边测试图。"""

    import cv2
    import numpy as np

    image = np.zeros((96, 128, 3), dtype=np.uint8)
    image[:, 48:] = (220, 220, 220)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_caliper_horizontal_test_png_bytes() -> bytes:
    """构造横向台阶边测试图。"""

    import cv2
    import numpy as np

    image = np.zeros((128, 128, 3), dtype=np.uint8)
    image[72:, :] = (235, 235, 235)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
