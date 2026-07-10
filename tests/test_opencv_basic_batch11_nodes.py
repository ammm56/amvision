"""OpenCV 第十一批形状与形态节点测试。"""

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


def test_opencv_basic_batch11_contour_shape_nodes_execute(tmp_path: Path) -> None:
    """验证 contour-approx、convex-hull、fit-ellipse 与 payload-to-value 可接成形状分析链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/shape-b11.png", _build_shape_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch11-contour-shape",
        template_version="1.0.0",
        display_name="OpenCV Batch11 Contour Shape",
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
                parameters={"retrieval_mode": "external", "min_area": 50.0},
            ),
            WorkflowGraphNode(
                node_id="approx",
                node_type_id="custom.opencv.contour-approx",
                parameters={"epsilon_mode": "perimeter-ratio", "epsilon_value": 0.03},
            ),
            WorkflowGraphNode(
                node_id="hull",
                node_type_id="custom.opencv.convex-hull",
                parameters={"sort_by": "hull_area", "descending": True},
            ),
            WorkflowGraphNode(
                node_id="ellipse",
                node_type_id="custom.opencv.fit-ellipse",
                parameters={"sort_by": "major_axis", "descending": True},
            ),
            WorkflowGraphNode(node_id="ellipse_value", node_type_id="custom.opencv.payload-to-value"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-otsu-b11",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-otsu-contour-b11",
                source_node_id="otsu",
                source_port="image",
                target_node_id="contour",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-approx-b11",
                source_node_id="contour",
                source_port="contours",
                target_node_id="approx",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-approx-hull-b11",
                source_node_id="approx",
                source_port="contours",
                target_node_id="hull",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-ellipse-b11",
                source_node_id="contour",
                source_port="contours",
                target_node_id="ellipse",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-ellipse-value-b11",
                source_node_id="ellipse",
                source_port="ellipses",
                target_node_id="ellipse_value",
                target_port="ellipses",
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
                output_id="original_contours",
                display_name="Original Contours",
                payload_type_id="contours.v1",
                source_node_id="contour",
                source_port="contours",
            ),
            WorkflowGraphOutput(
                output_id="approx_contours",
                display_name="Approx Contours",
                payload_type_id="contours.v1",
                source_node_id="approx",
                source_port="contours",
            ),
            WorkflowGraphOutput(
                output_id="approx_summary",
                display_name="Approx Summary",
                payload_type_id="value.v1",
                source_node_id="approx",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="hull_contours",
                display_name="Hull Contours",
                payload_type_id="contours.v1",
                source_node_id="hull",
                source_port="contours",
            ),
            WorkflowGraphOutput(
                output_id="hull_summary",
                display_name="Hull Summary",
                payload_type_id="value.v1",
                source_node_id="hull",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="ellipses",
                display_name="Ellipses",
                payload_type_id="ellipses.v1",
                source_node_id="ellipse",
                source_port="ellipses",
            ),
            WorkflowGraphOutput(
                output_id="ellipse_summary",
                display_name="Ellipse Summary",
                payload_type_id="value.v1",
                source_node_id="ellipse",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="ellipse_value",
                display_name="Ellipse Value",
                payload_type_id="value.v1",
                source_node_id="ellipse_value",
                source_port="value",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/shape-b11.png",
                "width": 160,
                "height": 120,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-batch11-contour-shape",
        },
    )

    original_contours = execution_result.outputs["original_contours"]
    approx_contours = execution_result.outputs["approx_contours"]
    approx_summary = execution_result.outputs["approx_summary"]
    hull_contours = execution_result.outputs["hull_contours"]
    hull_summary = execution_result.outputs["hull_summary"]
    ellipses = execution_result.outputs["ellipses"]
    ellipse_summary = execution_result.outputs["ellipse_summary"]
    ellipse_value = execution_result.outputs["ellipse_value"]

    assert original_contours["count"] == 2
    assert approx_contours["count"] == 2
    assert approx_summary["value"]["epsilon_mode"] == "perimeter-ratio"
    assert approx_summary["value"]["mean_reduced_point_ratio"] > 0
    assert approx_contours["items"][0]["point_count"] <= original_contours["items"][0]["point_count"]
    assert hull_contours["count"] == 2
    assert float(hull_contours["items"][0]["hull_area"]) >= float(hull_contours["items"][0]["contour_area"])
    assert 0.0 < float(hull_contours["items"][0]["solidity"]) <= 1.0
    assert hull_summary["value"]["count"] == 2
    assert ellipses["count"] >= 1
    assert float(ellipses["items"][0]["major_axis"]) >= float(ellipses["items"][0]["minor_axis"])
    assert float(ellipses["items"][0]["area"]) > 0
    assert ellipse_summary["value"]["count"] == ellipses["count"]
    assert ellipse_value["value"]["count"] == ellipses["count"]


def test_opencv_basic_batch11_fill_holes_and_distance_transform_execute(tmp_path: Path) -> None:
    """验证 fill-holes 与 distance-transform 可组成形态学预处理链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/hole-b11.png", _build_hole_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch11-holes-distance",
        template_version="1.0.0",
        display_name="OpenCV Batch11 Holes Distance",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(node_id="fill", node_type_id="custom.opencv.fill-holes"),
            WorkflowGraphNode(
                node_id="distance",
                node_type_id="custom.opencv.distance-transform",
                parameters={"distance_type": "l2", "mask_size": 5, "normalize_output": True},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-fill-b11",
                source_node_id="input",
                source_port="image",
                target_node_id="fill",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-fill-distance-b11",
                source_node_id="fill",
                source_port="image",
                target_node_id="distance",
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
                output_id="filled_image",
                display_name="Filled Image",
                payload_type_id="image-ref.v1",
                source_node_id="fill",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="fill_summary",
                display_name="Fill Summary",
                payload_type_id="value.v1",
                source_node_id="fill",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="distance_image",
                display_name="Distance Image",
                payload_type_id="image-ref.v1",
                source_node_id="distance",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="distance_summary",
                display_name="Distance Summary",
                payload_type_id="value.v1",
                source_node_id="distance",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/hole-b11.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch11-holes-distance",
        },
    )

    filled_image = execution_result.outputs["filled_image"]
    fill_summary = execution_result.outputs["fill_summary"]
    distance_image = execution_result.outputs["distance_image"]
    distance_summary = execution_result.outputs["distance_summary"]

    import numpy as np

    assert filled_image["media_type"] == "image/raw"
    assert filled_image["pixel_format"] == "bgr24"
    filled_shape = tuple(int(value) for value in filled_image["shape"])
    filled_matrix = np.frombuffer(
        image_registry.read_bytes(str(filled_image["image_handle"])),
        dtype=np.uint8,
    ).reshape(filled_shape)

    assert filled_image["width"] == 96
    assert filled_image["height"] == 96
    assert fill_summary["value"]["filled_hole_pixel_count"] > 0
    assert fill_summary["value"]["output_foreground_pixel_count"] > fill_summary["value"]["input_foreground_pixel_count"]
    assert int(filled_matrix[48, 48, 0]) == 255
    assert distance_image["width"] == 96
    assert distance_image["height"] == 96
    assert distance_image["media_type"] == "image/raw"
    assert distance_image["pixel_format"] == "bgr24"
    assert distance_summary["value"]["distance_type"] == "l2"
    assert distance_summary["value"]["mask_size"] == 5
    assert distance_summary["value"]["normalize_output"] is True
    assert distance_summary["value"]["max_distance"] > 0
    assert distance_summary["value"]["non_zero_distance_pixels"] > 0


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


def _build_shape_test_png_bytes() -> bytes:
    """构造形状分析测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.ellipse(image, (48, 60), (20, 32), 20, 0, 360, (255, 255, 255), thickness=-1)
    polygon = np.array(
        [[104, 24], [144, 24], [144, 48], [128, 48], [128, 76], [116, 76], [116, 48], [104, 48]],
        dtype=np.int32,
    )
    cv2.fillPoly(image, [polygon], (255, 255, 255))
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_hole_test_png_bytes() -> bytes:
    """构造带孔洞前景测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((96, 96, 3), dtype=np.uint8)
    cv2.circle(image, (48, 48), 26, (255, 255, 255), thickness=-1)
    cv2.circle(image, (48, 48), 10, (0, 0, 0), thickness=-1)
    cv2.rectangle(image, (18, 18), (28, 28), (255, 255, 255), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
