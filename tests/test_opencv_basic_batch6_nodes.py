"""OpenCV 第六批渲染与调试节点测试。"""

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


def test_opencv_basic_batch6_draw_contours_lines_and_measurements_execute(tmp_path: Path) -> None:
    """验证 contours、lines 与 measurement 渲染节点可接成几何调试链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    source_bytes = _build_line_pair_measure_test_png_bytes()
    dataset_storage.write_bytes("inputs/line-pair-render.png", source_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch6-geometry-render",
        template_version="1.0.0",
        display_name="OpenCV Batch6 Geometry Render",
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
                parameters={"retrieval_mode": "external", "min_area": 20.0},
            ),
            WorkflowGraphNode(
                node_id="fit",
                node_type_id="custom.opencv.fit-line",
                parameters={"sort_by": "length_pixels", "descending": True},
            ),
            WorkflowGraphNode(node_id="lines_value", node_type_id="custom.opencv.payload-to-value"),
            WorkflowGraphNode(
                node_id="extract_line_1_midpoint",
                node_type_id="core.logic.value-field-extract",
                parameters={"path": "items.0.midpoint_xy"},
            ),
            WorkflowGraphNode(
                node_id="extract_line_2_midpoint",
                node_type_id="core.logic.value-field-extract",
                parameters={"path": "items.1.midpoint_xy"},
            ),
            WorkflowGraphNode(
                node_id="point_distance",
                node_type_id="custom.opencv.point-distance",
                parameters={"output_metric": "distance_pixels"},
            ),
            WorkflowGraphNode(
                node_id="slot_width",
                node_type_id="custom.opencv.slot-width",
                parameters={
                    "line_a_strategy": "longest",
                    "line_b_strategy": "shortest",
                    "output_metric": "mean_width_pixels",
                },
            ),
            WorkflowGraphNode(node_id="measurement_list", node_type_id="core.logic.list-create"),
            WorkflowGraphNode(node_id="draw_contours", node_type_id="custom.opencv.draw-contours"),
            WorkflowGraphNode(node_id="draw_lines", node_type_id="custom.opencv.draw-lines"),
            WorkflowGraphNode(node_id="draw_measurements", node_type_id="custom.opencv.draw-measurements"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-otsu-b6",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-otsu-contour-b6",
                source_node_id="otsu",
                source_port="image",
                target_node_id="contour",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-fit-b6",
                source_node_id="contour",
                source_port="contours",
                target_node_id="fit",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-fit-lines-value-b6",
                source_node_id="fit",
                source_port="lines",
                target_node_id="lines_value",
                target_port="lines",
            ),
            WorkflowGraphEdge(
                edge_id="edge-lines-value-midpoint-1-b6",
                source_node_id="lines_value",
                source_port="value",
                target_node_id="extract_line_1_midpoint",
                target_port="value",
            ),
            WorkflowGraphEdge(
                edge_id="edge-lines-value-midpoint-2-b6",
                source_node_id="lines_value",
                source_port="value",
                target_node_id="extract_line_2_midpoint",
                target_port="value",
            ),
            WorkflowGraphEdge(
                edge_id="edge-midpoint-1-point-distance-b6",
                source_node_id="extract_line_1_midpoint",
                source_port="value",
                target_node_id="point_distance",
                target_port="point_a",
            ),
            WorkflowGraphEdge(
                edge_id="edge-midpoint-2-point-distance-b6",
                source_node_id="extract_line_2_midpoint",
                source_port="value",
                target_node_id="point_distance",
                target_port="point_b",
            ),
            WorkflowGraphEdge(
                edge_id="edge-fit-slot-width-b6",
                source_node_id="fit",
                source_port="lines",
                target_node_id="slot_width",
                target_port="lines",
            ),
            WorkflowGraphEdge(
                edge_id="edge-point-distance-list-b6",
                source_node_id="point_distance",
                source_port="summary",
                target_node_id="measurement_list",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-slot-width-list-b6",
                source_node_id="slot_width",
                source_port="summary",
                target_node_id="measurement_list",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-draw-contours-image-b6",
                source_node_id="input",
                source_port="image",
                target_node_id="draw_contours",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-draw-contours-b6",
                source_node_id="contour",
                source_port="contours",
                target_node_id="draw_contours",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-draw-lines-image-b6",
                source_node_id="input",
                source_port="image",
                target_node_id="draw_lines",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-fit-draw-lines-b6",
                source_node_id="fit",
                source_port="lines",
                target_node_id="draw_lines",
                target_port="lines",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-draw-measurements-image-b6",
                source_node_id="input",
                source_port="image",
                target_node_id="draw_measurements",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-measurement-list-draw-b6",
                source_node_id="measurement_list",
                source_port="value",
                target_node_id="draw_measurements",
                target_port="measurement",
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
                output_id="contour_overlay",
                display_name="Contour Overlay",
                payload_type_id="image-ref.v1",
                source_node_id="draw_contours",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="line_overlay",
                display_name="Line Overlay",
                payload_type_id="image-ref.v1",
                source_node_id="draw_lines",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="measurement_overlay",
                display_name="Measurement Overlay",
                payload_type_id="image-ref.v1",
                source_node_id="draw_measurements",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/line-pair-render.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch6-geometry-render",
        },
    )

    contour_overlay = execution_result.outputs["contour_overlay"]
    line_overlay = execution_result.outputs["line_overlay"]
    measurement_overlay = execution_result.outputs["measurement_overlay"]
    contour_bytes = image_registry.read_bytes(str(contour_overlay["image_handle"]))
    line_bytes = image_registry.read_bytes(str(line_overlay["image_handle"]))
    measurement_bytes = image_registry.read_bytes(str(measurement_overlay["image_handle"]))

    _assert_bgr24_image_payload(image_registry, contour_overlay)
    _assert_bgr24_image_payload(image_registry, line_overlay)
    _assert_bgr24_image_payload(image_registry, measurement_overlay)
    assert contour_bytes != source_bytes
    assert line_bytes != source_bytes
    assert measurement_bytes != source_bytes


def test_opencv_basic_batch6_draw_circles_and_measurements_execute(tmp_path: Path) -> None:
    """验证 circles 与 concentricity 渲染节点可接成圆形量测调试链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    source_bytes = _build_circle_pair_measure_test_png_bytes()
    dataset_storage.write_bytes("inputs/circle-render.png", source_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch6-circle-render",
        template_version="1.0.0",
        display_name="OpenCV Batch6 Circle Render",
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
                parameters={"retrieval_mode": "tree", "min_area": 50.0},
            ),
            WorkflowGraphNode(
                node_id="filter",
                node_type_id="custom.opencv.contour-filter",
                parameters={"sort_by": "area", "descending": True, "limit": 2},
            ),
            WorkflowGraphNode(
                node_id="circle",
                node_type_id="custom.opencv.min-enclosing-circle",
                parameters={"sort_by": "radius", "descending": True},
            ),
            WorkflowGraphNode(
                node_id="concentricity",
                node_type_id="custom.opencv.concentricity-metrics",
                parameters={
                    "circle_a_strategy": "largest",
                    "circle_b_strategy": "smallest",
                    "output_metric": "center_distance_pixels"
                },
            ),
            WorkflowGraphNode(node_id="draw_circles", node_type_id="custom.opencv.draw-circles"),
            WorkflowGraphNode(node_id="draw_measurements", node_type_id="custom.opencv.draw-measurements"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-otsu-circle-b6",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-otsu-contour-circle-b6",
                source_node_id="otsu",
                source_port="image",
                target_node_id="contour",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-filter-circle-b6",
                source_node_id="contour",
                source_port="contours",
                target_node_id="filter",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-filter-circle-b6",
                source_node_id="filter",
                source_port="contours",
                target_node_id="circle",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-circle-concentricity-b6",
                source_node_id="circle",
                source_port="circles",
                target_node_id="concentricity",
                target_port="circles",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-draw-circles-image-b6",
                source_node_id="input",
                source_port="image",
                target_node_id="draw_circles",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-circle-draw-circles-b6",
                source_node_id="circle",
                source_port="circles",
                target_node_id="draw_circles",
                target_port="circles",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-draw-concentricity-image-b6",
                source_node_id="input",
                source_port="image",
                target_node_id="draw_measurements",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-concentricity-draw-b6",
                source_node_id="concentricity",
                source_port="summary",
                target_node_id="draw_measurements",
                target_port="measurement",
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
                output_id="circle_overlay",
                display_name="Circle Overlay",
                payload_type_id="image-ref.v1",
                source_node_id="draw_circles",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="measurement_overlay",
                display_name="Measurement Overlay",
                payload_type_id="image-ref.v1",
                source_node_id="draw_measurements",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/circle-render.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch6-circle-render",
        },
    )

    circle_overlay = execution_result.outputs["circle_overlay"]
    measurement_overlay = execution_result.outputs["measurement_overlay"]
    circle_bytes = image_registry.read_bytes(str(circle_overlay["image_handle"]))
    measurement_bytes = image_registry.read_bytes(str(measurement_overlay["image_handle"]))

    _assert_bgr24_image_payload(image_registry, circle_overlay)
    _assert_bgr24_image_payload(image_registry, measurement_overlay)
    assert circle_bytes != source_bytes
    assert measurement_bytes != source_bytes


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


def _assert_bgr24_image_payload(image_registry: ExecutionImageRegistry, image_payload: dict[str, object]) -> None:
    """验证 OpenCV 渲染输出默认保留为 memory/raw BGR24，不做额外 PNG 编码。"""

    assert image_payload["transport_kind"] == "memory"
    assert image_payload["media_type"] == "image/raw"
    assert image_payload["pixel_format"] == "bgr24"
    assert image_payload["layout"] == "HWC"
    image_bytes = image_registry.read_bytes(str(image_payload["image_handle"]))
    assert len(image_bytes) == int(image_payload["width"]) * int(image_payload["height"]) * 3


def _build_line_pair_measure_test_png_bytes() -> bytes:
    """构建可稳定提取双边线的测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((128, 128, 3), dtype=np.uint8)
    cv2.line(image, (18, 42), (110, 42), (255, 255, 255), thickness=6)
    cv2.line(image, (20, 84), (108, 84), (255, 255, 255), thickness=6)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_circle_pair_measure_test_png_bytes() -> bytes:
    """构建可稳定提取同心双圆的测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((128, 128, 3), dtype=np.uint8)
    cv2.circle(image, (64, 64), 36, (255, 255, 255), thickness=-1)
    cv2.circle(image, (64, 64), 18, (0, 0, 0), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
