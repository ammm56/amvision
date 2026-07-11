"""OpenCV 第一批工业扩展节点测试。"""

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


def test_opencv_basic_batch1_preprocess_nodes_execute(tmp_path: Path) -> None:
    """验证 grayscale、resize、adaptive-threshold 与 otsu-threshold 节点可执行。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/preprocess.png", _build_preprocess_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch1-preprocess",
        template_version="1.0.0",
        display_name="OpenCV Batch1 Preprocess",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(node_id="grayscale", node_type_id="custom.opencv.grayscale"),
            WorkflowGraphNode(
                node_id="resize",
                node_type_id="custom.opencv.resize",
                parameters={"width": 40},
            ),
            WorkflowGraphNode(
                node_id="adaptive",
                node_type_id="custom.opencv.adaptive-threshold",
                parameters={
                    "adaptive_method": "gaussian",
                    "threshold_type": "binary",
                    "block_size": 11,
                    "c_value": 2.0,
                },
            ),
            WorkflowGraphNode(
                node_id="otsu",
                node_type_id="custom.opencv.otsu-threshold",
                parameters={"threshold_type": "binary"},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-grayscale",
                source_node_id="input",
                source_port="image",
                target_node_id="grayscale",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-grayscale-resize",
                source_node_id="grayscale",
                source_port="image",
                target_node_id="resize",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-resize-adaptive",
                source_node_id="resize",
                source_port="image",
                target_node_id="adaptive",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-otsu",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
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
                output_id="grayscale_image",
                display_name="Grayscale Image",
                payload_type_id="image-ref.v1",
                source_node_id="grayscale",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="resized_image",
                display_name="Resized Image",
                payload_type_id="image-ref.v1",
                source_node_id="resize",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="adaptive_image",
                display_name="Adaptive Image",
                payload_type_id="image-ref.v1",
                source_node_id="adaptive",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="otsu_image",
                display_name="Otsu Image",
                payload_type_id="image-ref.v1",
                source_node_id="otsu",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/preprocess.png",
                "width": 80,
                "height": 40,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch1-preprocess",
        },
    )

    grayscale_image = execution_result.outputs["grayscale_image"]
    resized_image = execution_result.outputs["resized_image"]
    adaptive_image = execution_result.outputs["adaptive_image"]
    otsu_image = execution_result.outputs["otsu_image"]

    assert grayscale_image["transport_kind"] == "memory"
    assert grayscale_image["width"] == 80
    assert grayscale_image["height"] == 40
    assert resized_image["width"] == 40
    assert resized_image["height"] == 20
    assert adaptive_image["width"] == 40
    assert adaptive_image["height"] == 20
    assert otsu_image["width"] == 80
    assert otsu_image["height"] == 40
    _assert_bgr24_image_payload(image_registry, grayscale_image)
    _assert_bgr24_image_payload(image_registry, resized_image)
    _assert_bgr24_image_payload(image_registry, adaptive_image)
    _assert_bgr24_image_payload(image_registry, otsu_image)


def test_opencv_basic_batch1_contour_bridge_nodes_execute(tmp_path: Path) -> None:
    """验证 contour-filter、min-area-rect 与 contours-to-regions 可接成传统视觉链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/contours.png", _build_contour_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch1-contour-bridge",
        template_version="1.0.0",
        display_name="OpenCV Batch1 Contour Bridge",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="otsu",
                node_type_id="custom.opencv.otsu-threshold",
                parameters={"threshold_type": "binary"},
            ),
            WorkflowGraphNode(
                node_id="contour",
                node_type_id="custom.opencv.contour",
                parameters={
                    "retrieval_mode": "external",
                    "min_area": 10.0,
                    "debug_image_panel_enabled": True,
                },
            ),
            WorkflowGraphNode(
                node_id="filter",
                node_type_id="custom.opencv.contour-filter",
                parameters={
                    "min_area": 200.0,
                    "sort_by": "area",
                    "descending": True,
                    "debug_image_panel_enabled": True,
                },
            ),
            WorkflowGraphNode(
                node_id="measure",
                node_type_id="custom.opencv.measure",
                parameters={"sort_by": "area", "descending": True},
            ),
            WorkflowGraphNode(
                node_id="rect",
                node_type_id="custom.opencv.min-area-rect",
                parameters={
                    "sort_by": "rect_area",
                    "descending": True,
                    "debug_image_panel_enabled": True,
                },
            ),
            WorkflowGraphNode(
                node_id="regions",
                node_type_id="custom.opencv.contours-to-regions",
                parameters={
                    "region_id_prefix": "ctr",
                    "class_id_default": 7,
                    "class_name_default": "sealant",
                    "score_default": 0.95,
                },
            ),
            WorkflowGraphNode(
                node_id="value",
                node_type_id="custom.opencv.payload-to-value",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-otsu",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-otsu-contour",
                source_node_id="otsu",
                source_port="image",
                target_node_id="contour",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-filter",
                source_node_id="contour",
                source_port="contours",
                target_node_id="filter",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-filter-measure",
                source_node_id="filter",
                source_port="contours",
                target_node_id="measure",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-filter-rect",
                source_node_id="filter",
                source_port="contours",
                target_node_id="rect",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-filter-regions",
                source_node_id="filter",
                source_port="contours",
                target_node_id="regions",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-regions-image",
                source_node_id="input",
                source_port="image",
                target_node_id="regions",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-rect-value",
                source_node_id="rect",
                source_port="rotated_rects",
                target_node_id="value",
                target_port="rotated_rects",
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
                output_id="filtered_contours",
                display_name="Filtered Contours",
                payload_type_id="contours.v1",
                source_node_id="filter",
                source_port="contours",
            ),
            WorkflowGraphOutput(
                output_id="contour_summary",
                display_name="Contour Summary",
                payload_type_id="value.v1",
                source_node_id="filter",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="measurements",
                display_name="Measurements",
                payload_type_id="measurements.v1",
                source_node_id="measure",
                source_port="measurements",
            ),
            WorkflowGraphOutput(
                output_id="rotated_rects",
                display_name="Rotated Rects",
                payload_type_id="rotated-rects.v1",
                source_node_id="rect",
                source_port="rotated_rects",
            ),
            WorkflowGraphOutput(
                output_id="rect_summary",
                display_name="Rect Summary",
                payload_type_id="value.v1",
                source_node_id="rect",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
                source_node_id="regions",
                source_port="regions",
            ),
            WorkflowGraphOutput(
                output_id="regions_summary",
                display_name="Regions Summary",
                payload_type_id="value.v1",
                source_node_id="regions",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="rotated_rects_value",
                display_name="Rotated Rects Value",
                payload_type_id="value.v1",
                source_node_id="value",
                source_port="value",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/contours.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch1-contour-bridge",
            "debug_image_panels_enabled": True,
        },
    )

    filtered_contours = execution_result.outputs["filtered_contours"]
    contour_summary = execution_result.outputs["contour_summary"]
    measurements = execution_result.outputs["measurements"]
    rotated_rects = execution_result.outputs["rotated_rects"]
    rect_summary = execution_result.outputs["rect_summary"]
    regions = execution_result.outputs["regions"]
    regions_summary = execution_result.outputs["regions_summary"]
    rotated_rects_value = execution_result.outputs["rotated_rects_value"]
    contour_debug_preview = _read_record_output(execution_result, node_id="contour", output_name="debug_preview")
    filter_debug_preview = _read_record_output(execution_result, node_id="filter", output_name="debug_preview")
    rect_debug_preview = _read_record_output(execution_result, node_id="rect", output_name="debug_preview")

    assert filtered_contours["count"] == 2
    assert contour_summary["value"]["filtered_count"] == 2
    assert contour_summary["value"]["original_count"] == 2
    assert measurements["count"] == 2
    assert measurements["items"][0]["area"] >= measurements["items"][1]["area"]
    assert rotated_rects["count"] == 2
    assert len(rotated_rects["items"][0]["box_points"]) == 4
    assert rotated_rects["items"][0]["rect_area"] >= rotated_rects["items"][0]["contour_area"]
    assert rect_summary["value"]["count"] == 2
    assert regions["count"] == 2
    assert regions["source_image"]["object_key"] == "inputs/contours.png"
    assert regions["items"][0]["region_id"].startswith("ctr-")
    assert regions["items"][0]["class_id"] == 7
    assert regions["items"][0]["class_name"] == "sealant"
    assert regions["items"][0]["score"] == 0.95
    assert regions_summary["value"]["region_count"] == 2
    assert rotated_rects_value["value"]["count"] == 2
    assert rotated_rects_value["value"]["items"][0]["contour_index"] == rotated_rects["items"][0]["contour_index"]
    contour_tools_by_name = {
        tool["tool"]: tool
        for tool in contour_debug_preview["interaction"]["tools"]
    }
    contour_pick_overlay = next(
        overlay
        for overlay in contour_debug_preview["overlays"]
        if "selected_contour_index" in overlay.get("target_parameters", [])
    )
    rect_pick_overlay = next(
        overlay
        for overlay in rect_debug_preview["overlays"]
        if "selected_contour_index" in overlay.get("target_parameters", [])
    )
    filter_pick_overlay = next(
        overlay
        for overlay in filter_debug_preview["overlays"]
        if "selected_contour_index" in overlay.get("target_parameters", [])
    )
    assert contour_debug_preview["type"] == "image-preview"
    assert filter_debug_preview["type"] == "image-preview"
    assert rect_debug_preview["type"] == "image-preview"
    assert contour_tools_by_name["contour"]["target_parameters"] == [
        "search_bbox_xyxy",
        "selected_contour_index",
    ]
    assert isinstance(contour_pick_overlay["parameters"]["selected_contour_index"], int)
    assert filter_debug_preview["interaction"]["tools"][0]["target_parameters"] == ["selected_contour_index"]
    assert isinstance(filter_pick_overlay["parameters"]["selected_contour_index"], int)
    assert rect_debug_preview["interaction"]["tools"][0]["target_parameters"] == ["selected_contour_index"]
    assert isinstance(rect_pick_overlay["parameters"]["selected_contour_index"], int)


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


def _assert_bgr24_image_payload(image_registry: ExecutionImageRegistry, image_payload: dict[str, object]) -> None:
    """验证节点输出保留为内存 bgr24 图片，不做额外 PNG 编码。"""

    assert image_payload["transport_kind"] == "memory"
    assert image_payload["media_type"] == "image/raw"
    assert image_payload["pixel_format"] == "bgr24"
    assert image_payload["layout"] == "HWC"
    image_bytes = image_registry.read_bytes(str(image_payload["image_handle"]))
    assert len(image_bytes) == int(image_payload["width"]) * int(image_payload["height"]) * 3


def _build_preprocess_test_png_bytes() -> bytes:
    """构建预处理测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((40, 80, 3), dtype=np.uint8)
    image[:, :40] = (40, 40, 40)
    image[:, 40:] = (220, 220, 220)
    cv2.circle(image, (56, 20), 10, (255, 255, 255), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_contour_test_png_bytes() -> bytes:
    """构建可稳定提取两个矩形 contour 的测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((96, 96, 3), dtype=np.uint8)
    cv2.rectangle(image, (8, 8), (32, 40), (255, 255, 255), thickness=-1)
    cv2.rectangle(image, (48, 20), (80, 72), (255, 255, 255), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
