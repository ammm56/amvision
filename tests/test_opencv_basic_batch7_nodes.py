"""OpenCV 第七批 ROI 与 regions 绘制节点测试。"""

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


def test_opencv_basic_batch7_draw_roi_execute(tmp_path: Path) -> None:
    """验证 roi-create 与 draw-roi 可接成现场 ROI 复核链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    source_bytes = _build_roi_render_test_png_bytes()
    dataset_storage.write_bytes("inputs/roi-render.png", source_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch7-draw-roi",
        template_version="1.0.0",
        display_name="OpenCV Batch7 Draw ROI",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi",
                node_type_id="core.vision.roi-create",
                parameters={
                    "roi_kind": "polygon",
                    "roi_id": "roi-sealant-window",
                    "display_name": "sealant-window",
                    "polygon_xy": [[16, 18], [104, 20], [96, 94], [22, 88]],
                },
            ),
            WorkflowGraphNode(
                node_id="draw_roi",
                node_type_id="custom.opencv.draw-roi",
                parameters={"fill_alpha": 0.22, "draw_bbox": True},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-roi-image-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="roi",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-draw-roi-image-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="draw_roi",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-draw-roi-b7",
                source_node_id="roi",
                source_port="roi",
                target_node_id="draw_roi",
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
                output_id="roi_overlay",
                display_name="ROI Overlay",
                payload_type_id="image-ref.v1",
                source_node_id="draw_roi",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/roi-render.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch7-draw-roi",
        },
    )

    roi_overlay = execution_result.outputs["roi_overlay"]
    roi_overlay_bytes = image_registry.read_bytes(str(roi_overlay["image_handle"]))

    assert roi_overlay["transport_kind"] == "memory"
    assert roi_overlay["media_type"] == "image/raw"
    assert roi_overlay["pixel_format"] == "bgr24"
    assert len(roi_overlay_bytes) == 128 * 128 * 3
    assert roi_overlay_bytes != source_bytes


def test_opencv_basic_batch7_draw_rois_execute(tmp_path: Path) -> None:
    """验证 roi-list-create 与 draw-rois 可通过 roi-list.v1 批量绘制槽位 ROI。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    source_bytes = _build_roi_render_test_png_bytes()
    dataset_storage.write_bytes("inputs/roi-render-list.png", source_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch7-draw-rois",
        template_version="1.0.0",
        display_name="OpenCV Batch7 Draw ROIs",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi_a",
                node_type_id="core.vision.roi-create",
                parameters={
                    "roi_kind": "bbox",
                    "roi_id": "slot-a",
                    "bbox_xyxy": [14, 16, 52, 56],
                },
            ),
            WorkflowGraphNode(
                node_id="roi_b",
                node_type_id="core.vision.roi-create",
                parameters={
                    "roi_kind": "polygon",
                    "roi_id": "slot-b",
                    "polygon_xy": [[70, 22], [108, 28], [100, 74], [66, 70]],
                },
            ),
            WorkflowGraphNode(node_id="roi_list", node_type_id="core.vision.roi-list-create"),
            WorkflowGraphNode(
                node_id="draw_rois",
                node_type_id="custom.opencv.draw-rois",
                parameters={"fill_alpha": 0.18, "draw_bbox": True},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-roi-a-image-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="roi_a",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-roi-b-image-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="roi_b",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-a-list-b7",
                source_node_id="roi_a",
                source_port="roi",
                target_node_id="roi_list",
                target_port="roi",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-b-list-b7",
                source_node_id="roi_b",
                source_port="roi",
                target_node_id="roi_list",
                target_port="roi",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-draw-rois-image-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="draw_rois",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-list-draw-rois-b7",
                source_node_id="roi_list",
                source_port="rois",
                target_node_id="draw_rois",
                target_port="rois",
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
                output_id="roi_overlay",
                display_name="ROI Overlay",
                payload_type_id="image-ref.v1",
                source_node_id="draw_rois",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/roi-render-list.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch7-draw-rois",
        },
    )

    roi_overlay = execution_result.outputs["roi_overlay"]
    roi_overlay_bytes = image_registry.read_bytes(str(roi_overlay["image_handle"]))

    assert roi_overlay["transport_kind"] == "memory"
    assert roi_overlay["media_type"] == "image/raw"
    assert roi_overlay["pixel_format"] == "bgr24"
    assert len(roi_overlay_bytes) == 128 * 128 * 3
    assert roi_overlay_bytes != source_bytes


def test_opencv_basic_batch7_crop_export_rois_execute(tmp_path: Path) -> None:
    """验证 crop-export 可消费 ROI Grid Create.rois 批量输出裁剪图。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/roi-crop-export.png", _build_roi_render_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch7-crop-export-rois",
        template_version="1.0.0",
        display_name="OpenCV Batch7 Crop Export ROIs",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi_grid",
                node_type_id="core.vision.roi-grid-create",
                parameters={
                    "rows": 2,
                    "columns": 2,
                    "origin_x": 16,
                    "origin_y": 16,
                    "roi_width": 24,
                    "roi_height": 20,
                    "step_x": 36,
                    "step_y": 32,
                    "roi_id_prefix": "slot",
                },
            ),
            WorkflowGraphNode(node_id="crop_export", node_type_id="custom.opencv.crop-export"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-grid-image-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="roi_grid",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-crop-export-image-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="crop_export",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-grid-crop-export-rois-b7",
                source_node_id="roi_grid",
                source_port="rois",
                target_node_id="crop_export",
                target_port="rois",
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
                output_id="crops",
                display_name="Crops",
                payload_type_id="image-refs.v1",
                source_node_id="crop_export",
                source_port="crops",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/roi-crop-export.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch7-crop-export-rois",
        },
    )

    crops = execution_result.outputs["crops"]

    assert crops["count"] == 4
    assert crops["items"][0]["crop_source"] == "roi"
    assert crops["items"][0]["roi_id"] == "slot-01-01"
    assert crops["items"][0]["transport_kind"] == "memory"
    assert crops["items"][0]["media_type"] == "image/raw"
    assert crops["items"][0]["pixel_format"] == "bgr24"
    assert crops["items"][0]["width"] == 24
    assert crops["items"][0]["height"] == 20


def test_opencv_basic_batch7_image_refs_statistics_execute(tmp_path: Path) -> None:
    """验证 image-refs-statistics 可对批量 crop 计算指标并输出 empty 判断。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/roi-statistics.png", _build_image_refs_statistics_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch7-image-refs-statistics",
        template_version="1.0.0",
        display_name="OpenCV Batch7 Image Refs Statistics",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi_grid",
                node_type_id="core.vision.roi-grid-create",
                parameters={
                    "rows": 1,
                    "columns": 2,
                    "origin_x": 0,
                    "origin_y": 0,
                    "roi_width": 64,
                    "roi_height": 64,
                    "step_x": 64,
                    "step_y": 64,
                    "roi_id_prefix": "slot",
                },
            ),
            WorkflowGraphNode(node_id="crop_export", node_type_id="custom.opencv.crop-export"),
            WorkflowGraphNode(
                node_id="statistics",
                node_type_id="custom.opencv.image-refs-statistics",
                parameters={
                    "decision_metric": "edge_density",
                    "empty_max": 0.02,
                    "canny_low_threshold": 50,
                    "canny_high_threshold": 150,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-grid-image-b7-stat",
                source_node_id="input",
                source_port="image",
                target_node_id="roi_grid",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-crop-export-image-b7-stat",
                source_node_id="input",
                source_port="image",
                target_node_id="crop_export",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-grid-crop-export-rois-b7-stat",
                source_node_id="roi_grid",
                source_port="rois",
                target_node_id="crop_export",
                target_port="rois",
            ),
            WorkflowGraphEdge(
                edge_id="edge-crop-export-statistics-images-b7",
                source_node_id="crop_export",
                source_port="crops",
                target_node_id="statistics",
                target_port="images",
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
                output_id="statistics",
                display_name="Statistics",
                payload_type_id="value.v1",
                source_node_id="statistics",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/roi-statistics.png",
                "width": 128,
                "height": 64,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch7-image-refs-statistics",
        },
    )

    statistics = execution_result.outputs["statistics"]["value"]

    assert statistics["count"] == 2
    assert statistics["decision_enabled"] is True
    assert statistics["items"][0]["roi_id"] == "slot-01-01"
    assert statistics["items"][0]["is_empty"] is True
    assert statistics["items"][1]["roi_id"] == "slot-01-02"
    assert statistics["items"][1]["is_empty"] is False


def test_opencv_basic_batch7_image_refs_empty_check_execute(tmp_path: Path) -> None:
    """验证 image-refs-empty-check 可用多指标规则判断批量槽位是否为空。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/roi-empty-check.png", _build_image_refs_empty_check_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch7-image-refs-empty-check",
        template_version="1.0.0",
        display_name="OpenCV Batch7 Image Refs Empty Check",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi_grid",
                node_type_id="core.vision.roi-grid-create",
                parameters={
                    "rows": 1,
                    "columns": 2,
                    "origin_x": 0,
                    "origin_y": 0,
                    "roi_width": 72,
                    "roi_height": 72,
                    "step_x": 72,
                    "step_y": 72,
                    "roi_id_prefix": "slot",
                },
            ),
            WorkflowGraphNode(node_id="crop_export", node_type_id="custom.opencv.crop-export"),
            WorkflowGraphNode(
                node_id="slot_metrics",
                node_type_id="custom.opencv.image-refs-slot-metrics",
                parameters={
                    "dark_component_min_area": 12,
                },
            ),
            WorkflowGraphNode(
                node_id="empty_check",
                node_type_id="custom.opencv.image-refs-empty-check",
                parameters={
                    "expected_count": 2,
                    "std_gray_empty_max": 18,
                    "dark_ratio_empty_max": 0.02,
                    "edge_density_empty_max": 0.08,
                    "dark_component_area_ratio_empty_max": 0.02,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-grid-b7-empty",
                source_node_id="input",
                source_port="image",
                target_node_id="roi_grid",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-crop-export-b7-empty",
                source_node_id="input",
                source_port="image",
                target_node_id="crop_export",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-grid-crop-export-b7-empty",
                source_node_id="roi_grid",
                source_port="rois",
                target_node_id="crop_export",
                target_port="rois",
            ),
            WorkflowGraphEdge(
                edge_id="edge-crop-export-slot-metrics-b7",
                source_node_id="crop_export",
                source_port="crops",
                target_node_id="slot_metrics",
                target_port="images",
            ),
            WorkflowGraphEdge(
                edge_id="edge-slot-metrics-empty-check-b7",
                source_node_id="slot_metrics",
                source_port="summary",
                target_node_id="empty_check",
                target_port="metrics",
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
                output_id="slot_metrics",
                display_name="Slot Metrics",
                payload_type_id="value.v1",
                source_node_id="slot_metrics",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="empty_check",
                display_name="Empty Check",
                payload_type_id="value.v1",
                source_node_id="empty_check",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/roi-empty-check.png",
                "width": 144,
                "height": 72,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch7-image-refs-empty-check",
        },
    )

    slot_metrics = execution_result.outputs["slot_metrics"]["value"]
    empty_check = execution_result.outputs["empty_check"]["value"]

    assert slot_metrics["format_id"] == "amvision.image-refs-slot-metrics.v1"
    assert slot_metrics["count"] == 2
    assert empty_check["count"] == 2
    assert empty_check["expected_count_matched"] is True
    assert empty_check["empty_count"] == 1
    assert empty_check["non_empty_count"] == 1
    assert empty_check["state"] == "ng"
    assert empty_check["items"][0]["roi_id"] == "slot-01-01"
    assert empty_check["items"][0]["is_empty"] is True
    assert empty_check["items"][1]["roi_id"] == "slot-01-02"
    assert empty_check["items"][1]["is_empty"] is False
    assert "std_gray" in empty_check["items"][0]["metrics"]


def test_opencv_basic_batch7_slot_empty_occupied_state_execute(tmp_path: Path) -> None:
    """验证空槽检查、有料检查和批量状态节点可组合判断整批槽位状态。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/roi-slot-state.png", _build_image_refs_empty_check_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch7-slot-state",
        template_version="1.0.0",
        display_name="OpenCV Batch7 Slot State",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi_grid",
                node_type_id="core.vision.roi-grid-create",
                parameters={
                    "rows": 1,
                    "columns": 2,
                    "origin_x": 0,
                    "origin_y": 0,
                    "roi_width": 72,
                    "roi_height": 72,
                    "step_x": 72,
                    "step_y": 72,
                    "roi_id_prefix": "slot",
                },
            ),
            WorkflowGraphNode(node_id="crop_export", node_type_id="custom.opencv.crop-export"),
            WorkflowGraphNode(
                node_id="slot_metrics",
                node_type_id="custom.opencv.image-refs-slot-metrics",
                parameters={
                    "dark_component_min_area": 12,
                },
            ),
            WorkflowGraphNode(
                node_id="empty_check",
                node_type_id="custom.opencv.image-refs-empty-check",
                parameters={
                    "expected_count": 2,
                    "std_gray_empty_max": 18,
                    "dark_ratio_empty_max": 0.02,
                    "edge_density_empty_max": 0.08,
                    "dark_component_area_ratio_empty_max": 0.02,
                },
            ),
            WorkflowGraphNode(
                node_id="occupied_check",
                node_type_id="custom.opencv.image-refs-occupied-check",
                parameters={
                    "expected_count": 2,
                    "std_gray_occupied_min": 18,
                    "dark_ratio_occupied_min": 0.02,
                    "edge_density_occupied_min": 0.02,
                    "dark_component_area_ratio_occupied_min": 0.02,
                    "occupied_min_pass_count": 1,
                },
            ),
            WorkflowGraphNode(
                node_id="slot_state",
                node_type_id="custom.opencv.slot-batch-state",
                parameters={
                    "expected_count": 2,
                    "empty_min_empty_ratio": 1.0,
                    "full_min_occupied_ratio": 1.0,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-grid-b7-state",
                source_node_id="input",
                source_port="image",
                target_node_id="roi_grid",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-crop-export-b7-state",
                source_node_id="input",
                source_port="image",
                target_node_id="crop_export",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-grid-crop-export-b7-state",
                source_node_id="roi_grid",
                source_port="rois",
                target_node_id="crop_export",
                target_port="rois",
            ),
            WorkflowGraphEdge(
                edge_id="edge-crop-export-slot-metrics-b7-state",
                source_node_id="crop_export",
                source_port="crops",
                target_node_id="slot_metrics",
                target_port="images",
            ),
            WorkflowGraphEdge(
                edge_id="edge-slot-metrics-empty-check-b7-state",
                source_node_id="slot_metrics",
                source_port="summary",
                target_node_id="empty_check",
                target_port="metrics",
            ),
            WorkflowGraphEdge(
                edge_id="edge-slot-metrics-occupied-check-b7-state",
                source_node_id="slot_metrics",
                source_port="summary",
                target_node_id="occupied_check",
                target_port="metrics",
            ),
            WorkflowGraphEdge(
                edge_id="edge-crop-export-empty-check-b7-state",
                source_node_id="crop_export",
                source_port="crops",
                target_node_id="empty_check",
                target_port="images",
            ),
            WorkflowGraphEdge(
                edge_id="edge-crop-export-occupied-check-b7-state",
                source_node_id="crop_export",
                source_port="crops",
                target_node_id="occupied_check",
                target_port="images",
            ),
            WorkflowGraphEdge(
                edge_id="edge-empty-check-slot-state-b7",
                source_node_id="empty_check",
                source_port="summary",
                target_node_id="slot_state",
                target_port="empty_check",
            ),
            WorkflowGraphEdge(
                edge_id="edge-occupied-check-slot-state-b7",
                source_node_id="occupied_check",
                source_port="summary",
                target_node_id="slot_state",
                target_port="occupied_check",
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
                output_id="empty_check",
                display_name="Empty Check",
                payload_type_id="value.v1",
                source_node_id="empty_check",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="occupied_check",
                display_name="Occupied Check",
                payload_type_id="value.v1",
                source_node_id="occupied_check",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="slot_state",
                display_name="Slot State",
                payload_type_id="value.v1",
                source_node_id="slot_state",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/roi-slot-state.png",
                "width": 144,
                "height": 72,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch7-slot-state",
        },
    )

    empty_check = execution_result.outputs["empty_check"]["value"]
    occupied_check = execution_result.outputs["occupied_check"]["value"]
    slot_state = execution_result.outputs["slot_state"]["value"]

    assert empty_check["empty_count"] == 1
    assert empty_check["non_empty_count"] == 1
    assert occupied_check["occupied_count"] == 1
    assert occupied_check["empty_count"] == 1
    assert occupied_check["items"][0]["is_occupied"] is False
    assert occupied_check["items"][1]["is_occupied"] is True
    assert slot_state["tray_state"] == "partial-or-abnormal"
    assert slot_state["is_empty_tray"] is False
    assert slot_state["is_full_tray"] is False


def test_opencv_basic_batch7_draw_regions_execute(tmp_path: Path) -> None:
    """验证 connected-components 与 draw-regions 可接成分割覆盖层调试链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    source_bytes = _build_regions_overlay_test_png_bytes()
    dataset_storage.write_bytes("inputs/draw-regions.png", source_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch7-draw-regions",
        template_version="1.0.0",
        display_name="OpenCV Batch7 Draw Regions",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="otsu",
                node_type_id="custom.opencv.otsu-threshold",
                parameters={"threshold_type": "binary"},
            ),
            WorkflowGraphNode(
                node_id="components",
                node_type_id="custom.opencv.connected-components",
                parameters={"min_area": 40.0, "class_name_default": "defect-area"},
            ),
            WorkflowGraphNode(
                node_id="draw_regions",
                node_type_id="custom.opencv.draw-regions",
                parameters={"mask_alpha": 0.4, "draw_boxes": True, "draw_polygons": True},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-otsu-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-otsu-components-b7",
                source_node_id="otsu",
                source_port="image",
                target_node_id="components",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-components-source-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="components",
                target_port="source_image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-draw-regions-image-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="draw_regions",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-components-draw-regions-b7",
                source_node_id="components",
                source_port="regions",
                target_node_id="draw_regions",
                target_port="regions",
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
                output_id="draw_regions",
                display_name="Draw Regions",
                payload_type_id="image-ref.v1",
                source_node_id="draw_regions",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/draw-regions.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch7-draw-regions",
        },
    )

    draw_regions = execution_result.outputs["draw_regions"]
    draw_regions_bytes = image_registry.read_bytes(str(draw_regions["image_handle"]))

    assert draw_regions["transport_kind"] == "memory"
    assert draw_regions["media_type"] == "image/raw"
    assert draw_regions["pixel_format"] == "bgr24"
    assert len(draw_regions_bytes) == int(draw_regions["width"]) * int(draw_regions["height"]) * 3
    assert draw_regions_bytes != source_bytes


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


def _build_roi_render_test_png_bytes() -> bytes:
    """构造 ROI 调试测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((128, 128, 3), dtype=np.uint8)
    cv2.rectangle(image, (20, 24), (100, 92), (48, 48, 48), thickness=-1)
    cv2.line(image, (18, 96), (110, 96), (100, 100, 100), thickness=2)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_regions_overlay_test_png_bytes() -> bytes:
    """构造带两个明显前景块的分割覆盖层测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((128, 128, 3), dtype=np.uint8)
    cv2.rectangle(image, (18, 20), (56, 82), (255, 255, 255), thickness=-1)
    cv2.circle(image, (92, 70), 18, (255, 255, 255), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_image_refs_statistics_test_png_bytes() -> bytes:
    """构造左侧平滑、右侧高边缘密度的批量统计测试图片。"""

    import cv2
    import numpy as np

    image = np.full((64, 128, 3), 128, dtype=np.uint8)
    for x in range(72, 124, 8):
        cv2.line(image, (x, 4), (x, 60), (255, 255, 255), thickness=2)
    for y in range(8, 60, 8):
        cv2.line(image, (68, y), (124, y), (0, 0, 0), thickness=2)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_image_refs_empty_check_test_png_bytes() -> bytes:
    """构造左侧空槽、右侧有暗色物料的批量空槽检查测试图片。"""

    import cv2
    import numpy as np

    image = np.full((72, 144, 3), 186, dtype=np.uint8)
    cv2.rectangle(image, (82, 14), (132, 58), (32, 32, 32), thickness=-1)
    cv2.line(image, (82, 14), (132, 58), (88, 88, 88), thickness=2)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
