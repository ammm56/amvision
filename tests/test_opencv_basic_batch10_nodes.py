"""OpenCV 第十批预处理与对齐节点测试。"""

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


def test_opencv_basic_batch10_preprocess_nodes_execute(tmp_path: Path) -> None:
    """验证 crop、invert、clahe、median-blur、bilateral-filter 与 normalize 可串成预处理链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/preprocess-b10.png", _build_preprocess_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch10-preprocess",
        template_version="1.0.0",
        display_name="OpenCV Batch10 Preprocess",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi",
                node_type_id="core.vision.roi-create",
                parameters={
                    "roi_kind": "bbox",
                    "roi_id": "station-window",
                    "display_name": "station-window",
                    "bbox_xyxy": [12, 8, 84, 56],
                },
            ),
            WorkflowGraphNode(node_id="crop", node_type_id="custom.opencv.crop"),
            WorkflowGraphNode(node_id="invert", node_type_id="custom.opencv.invert"),
            WorkflowGraphNode(
                node_id="clahe",
                node_type_id="custom.opencv.clahe",
                parameters={"clip_limit": 2.5, "tile_grid_size": 4, "apply_to_luminance": True},
            ),
            WorkflowGraphNode(
                node_id="median",
                node_type_id="custom.opencv.median-blur",
                parameters={"kernel_size": 5},
            ),
            WorkflowGraphNode(
                node_id="bilateral",
                node_type_id="custom.opencv.bilateral-filter",
                parameters={
                    "diameter": 7,
                    "sigma_color": 60.0,
                    "sigma_space": 60.0,
                    "search_bbox_xyxy": [5, 4, 50, 30],
                },
            ),
            WorkflowGraphNode(
                node_id="normalize",
                node_type_id="custom.opencv.normalize",
                parameters={"alpha": 10.0, "beta": 240.0, "per_channel": True},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-roi-b10",
                source_node_id="input",
                source_port="image",
                target_node_id="roi",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-crop-b10",
                source_node_id="input",
                source_port="image",
                target_node_id="crop",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-crop-b10",
                source_node_id="roi",
                source_port="roi",
                target_node_id="crop",
                target_port="roi",
            ),
            WorkflowGraphEdge(
                edge_id="edge-crop-invert-b10",
                source_node_id="crop",
                source_port="image",
                target_node_id="invert",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-invert-clahe-b10",
                source_node_id="invert",
                source_port="image",
                target_node_id="clahe",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-clahe-median-b10",
                source_node_id="clahe",
                source_port="image",
                target_node_id="median",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-median-bilateral-b10",
                source_node_id="median",
                source_port="image",
                target_node_id="bilateral",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-bilateral-normalize-b10",
                source_node_id="bilateral",
                source_port="image",
                target_node_id="normalize",
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
                output_id="cropped_image",
                display_name="Cropped Image",
                payload_type_id="image-ref.v1",
                source_node_id="crop",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="crop_summary",
                display_name="Crop Summary",
                payload_type_id="value.v1",
                source_node_id="crop",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="normalized_image",
                display_name="Normalized Image",
                payload_type_id="image-ref.v1",
                source_node_id="normalize",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="median_image",
                display_name="Median Image",
                payload_type_id="image-ref.v1",
                source_node_id="median",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="bilateral_image",
                display_name="Bilateral Image",
                payload_type_id="image-ref.v1",
                source_node_id="bilateral",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="bilateral_summary",
                display_name="Bilateral Summary",
                payload_type_id="value.v1",
                source_node_id="bilateral",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/preprocess-b10.png",
                "width": 96,
                "height": 64,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch10-preprocess",
        },
    )

    cropped_image = execution_result.outputs["cropped_image"]
    crop_summary = execution_result.outputs["crop_summary"]
    normalized_image = execution_result.outputs["normalized_image"]
    median_image = execution_result.outputs["median_image"]
    bilateral_image = execution_result.outputs["bilateral_image"]
    bilateral_summary = execution_result.outputs["bilateral_summary"]

    assert cropped_image["transport_kind"] == "memory"
    assert cropped_image["width"] == 72
    assert cropped_image["height"] == 48
    assert crop_summary["value"]["crop_source"] == "roi"
    assert crop_summary["value"]["roi_id"] == "station-window"
    assert crop_summary["value"]["crop_bbox_xyxy"] == [12, 8, 84, 56]
    assert crop_summary["value"]["output_width"] == 72
    assert crop_summary["value"]["output_height"] == 48
    assert normalized_image["transport_kind"] == "memory"
    assert normalized_image["width"] == 72
    assert normalized_image["height"] == 48
    cropped_entry = image_registry.get_entry(str(cropped_image["image_handle"]))
    assert cropped_image["media_type"] == "image/raw"
    assert cropped_image["pixel_format"] == "bgr24"
    assert cropped_entry.byte_length == 72 * 48 * 3
    normalized_entry = image_registry.get_entry(str(normalized_image["image_handle"]))
    assert normalized_image["media_type"] == "image/raw"
    assert normalized_image["pixel_format"] == "bgr24"
    assert normalized_entry.byte_length == 72 * 48 * 3
    median_entry = image_registry.get_entry(str(median_image["image_handle"]))
    bilateral_entry = image_registry.get_entry(str(bilateral_image["image_handle"]))
    assert bilateral_image["pixel_format"] == "bgr24"
    assert bilateral_summary["value"]["search_roi_source"] == "parameter"
    assert bilateral_summary["value"]["search_bbox_xyxy"] == [5, 4, 50, 30]
    assert bilateral_summary["value"]["processing_width"] == 45
    assert bilateral_summary["value"]["processing_height"] == 26
    assert bilateral_summary["value"]["processing_pixel_count"] == 45 * 26
    # ROI 外保持完整原始 BGR24 像素，不能为了局部滤波改变下游坐标或通道协议。
    assert (bilateral_entry.matrix[:4] == median_entry.matrix[:4]).all()
    assert (bilateral_entry.matrix[30:] == median_entry.matrix[30:]).all()
    assert (bilateral_entry.matrix[:, :5] == median_entry.matrix[:, :5]).all()
    assert (bilateral_entry.matrix[:, 50:] == median_entry.matrix[:, 50:]).all()


def test_opencv_basic_crop_polygon_roi_masks_background_execute(tmp_path: Path) -> None:
    """验证 crop 使用 polygon ROI 时会裁外接矩形并填充 polygon 外部背景。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/polygon-crop-b10.png", _build_polygon_crop_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch10-polygon-crop",
        template_version="1.0.0",
        display_name="OpenCV Batch10 Polygon Crop",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi",
                node_type_id="core.vision.roi-create",
                parameters={
                    "roi_kind": "polygon",
                    "roi_id": "triangle-window",
                    "polygon_xy": [[10, 10], [50, 10], [10, 50]],
                },
            ),
            WorkflowGraphNode(
                node_id="crop",
                node_type_id="custom.opencv.crop",
                parameters={"polygon_background_fill": "white"},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-roi-polygon-b10",
                source_node_id="input",
                source_port="image",
                target_node_id="roi",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-crop-polygon-b10",
                source_node_id="input",
                source_port="image",
                target_node_id="crop",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-crop-polygon-b10",
                source_node_id="roi",
                source_port="roi",
                target_node_id="crop",
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
                output_id="cropped_image",
                display_name="Cropped Image",
                payload_type_id="image-ref.v1",
                source_node_id="crop",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="crop_summary",
                display_name="Crop Summary",
                payload_type_id="value.v1",
                source_node_id="crop",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/polygon-crop-b10.png",
                "width": 64,
                "height": 64,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch10-polygon-crop",
        },
    )

    cropped_image = execution_result.outputs["cropped_image"]
    crop_summary = execution_result.outputs["crop_summary"]
    cropped_matrix = image_registry.read_matrix(str(cropped_image["image_handle"]))

    assert cropped_image["transport_kind"] == "memory"
    assert cropped_image["media_type"] == "image/raw"
    assert cropped_image["pixel_format"] == "bgr24"
    assert cropped_image["width"] == 40
    assert cropped_image["height"] == 40
    assert crop_summary["value"]["roi_kind"] == "polygon"
    assert crop_summary["value"]["polygon_mask_applied"] is True
    assert crop_summary["value"]["polygon_background_fill"] == "white"
    assert cropped_matrix[2, 2].tolist() == [10, 20, 30]
    assert cropped_matrix[38, 38].tolist() == [255, 255, 255]


def test_opencv_basic_batch10_rotation_correct_with_value_input_execute(tmp_path: Path) -> None:
    """验证 rotation-correct 可读取 value.v1 角度输入并交换输出尺寸。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/rotation-b10.png", _build_rotation_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch10-rotation-correct",
        template_version="1.0.0",
        display_name="OpenCV Batch10 Rotation Correct",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(node_id="angle", node_type_id="core.io.template-input.value"),
            WorkflowGraphNode(
                node_id="rotate",
                node_type_id="custom.opencv.rotation-correct",
                parameters={
                    "angle_path": "rotation.angle_deg",
                    "expand_canvas": True,
                    "border_mode": "constant",
                    "border_value": 5,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-rotate-b10",
                source_node_id="input",
                source_port="image",
                target_node_id="rotate",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-angle-rotate-b10",
                source_node_id="angle",
                source_port="value",
                target_node_id="rotate",
                target_port="angle",
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
                input_id="request_angle",
                display_name="Request Angle",
                payload_type_id="value.v1",
                target_node_id="angle",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="rotated_image",
                display_name="Rotated Image",
                payload_type_id="image-ref.v1",
                source_node_id="rotate",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="rotation_summary",
                display_name="Rotation Summary",
                payload_type_id="value.v1",
                source_node_id="rotate",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/rotation-b10.png",
                "width": 80,
                "height": 30,
                "media_type": "image/png",
            },
            "request_angle": {
                "value": {
                    "rotation": {
                        "angle_deg": 90.0,
                    }
                }
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch10-rotation-correct",
        },
    )

    rotated_image = execution_result.outputs["rotated_image"]
    rotation_summary = execution_result.outputs["rotation_summary"]

    assert rotated_image["transport_kind"] == "memory"
    assert rotated_image["width"] == 31
    assert rotated_image["height"] == 80
    assert rotation_summary["value"]["angle_source"] == "input"
    assert rotation_summary["value"]["requested_angle_deg"] == 90.0
    assert rotation_summary["value"]["applied_angle_deg"] == -90.0
    assert rotation_summary["value"]["negate_angle"] is True
    assert rotation_summary["value"]["expand_canvas"] is True
    assert rotation_summary["value"]["source_width"] == 80
    assert rotation_summary["value"]["source_height"] == 30
    assert rotation_summary["value"]["output_width"] == 31
    assert rotation_summary["value"]["output_height"] == 80
    rotated_entry = image_registry.get_entry(str(rotated_image["image_handle"]))
    assert rotated_image["media_type"] == "image/raw"
    assert rotated_image["pixel_format"] == "bgr24"
    assert rotated_entry.byte_length == 31 * 80 * 3


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


def _build_preprocess_test_png_bytes() -> bytes:
    """构造预处理链测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((64, 96, 3), dtype=np.uint8)
    for row_index in range(64):
        image[row_index, :, 0] = 30 + row_index
        image[row_index, :, 1] = 60 + row_index
        image[row_index, :, 2] = 90 + row_index
    cv2.rectangle(image, (18, 12), (76, 52), (220, 220, 220), thickness=-1)
    cv2.circle(image, (48, 32), 10, (15, 15, 15), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_polygon_crop_test_png_bytes() -> bytes:
    """构造 polygon crop 测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[:, :] = (10, 20, 30)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_rotation_test_png_bytes() -> bytes:
    """构造旋转矫正测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((30, 80, 3), dtype=np.uint8)
    cv2.rectangle(image, (6, 8), (70, 20), (255, 255, 255), thickness=-1)
    cv2.line(image, (10, 4), (10, 26), (120, 120, 120), thickness=2)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
