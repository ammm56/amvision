"""OpenCV 第五批工业量测节点测试。"""

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


def test_opencv_basic_batch5_line_pair_measurement_nodes_execute(tmp_path: Path) -> None:
    """验证点距、平行度和槽宽节点可接成量测链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/line-pair-measure.png", _build_line_pair_measure_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch5-line-pair-measure",
        template_version="1.0.0",
        display_name="OpenCV Batch5 Line Pair Measure",
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
                node_id="parallelism",
                node_type_id="custom.opencv.parallelism-metrics",
                parameters={
                    "line_a_strategy": "longest",
                    "line_b_strategy": "shortest",
                    "output_metric": "abs_delta_angle_deg",
                },
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
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-otsu-line-pair",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-otsu-contour-line-pair",
                source_node_id="otsu",
                source_port="image",
                target_node_id="contour",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-fit-line-pair",
                source_node_id="contour",
                source_port="contours",
                target_node_id="fit",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-fit-lines-value",
                source_node_id="fit",
                source_port="lines",
                target_node_id="lines_value",
                target_port="lines",
            ),
            WorkflowGraphEdge(
                edge_id="edge-lines-value-midpoint-1",
                source_node_id="lines_value",
                source_port="value",
                target_node_id="extract_line_1_midpoint",
                target_port="value",
            ),
            WorkflowGraphEdge(
                edge_id="edge-lines-value-midpoint-2",
                source_node_id="lines_value",
                source_port="value",
                target_node_id="extract_line_2_midpoint",
                target_port="value",
            ),
            WorkflowGraphEdge(
                edge_id="edge-midpoint-1-point-distance",
                source_node_id="extract_line_1_midpoint",
                source_port="value",
                target_node_id="point_distance",
                target_port="point_a",
            ),
            WorkflowGraphEdge(
                edge_id="edge-midpoint-2-point-distance",
                source_node_id="extract_line_2_midpoint",
                source_port="value",
                target_node_id="point_distance",
                target_port="point_b",
            ),
            WorkflowGraphEdge(
                edge_id="edge-fit-parallelism",
                source_node_id="fit",
                source_port="lines",
                target_node_id="parallelism",
                target_port="lines",
            ),
            WorkflowGraphEdge(
                edge_id="edge-fit-slot-width",
                source_node_id="fit",
                source_port="lines",
                target_node_id="slot_width",
                target_port="lines",
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
                output_id="point_distance_value",
                display_name="Point Distance Value",
                payload_type_id="value.v1",
                source_node_id="point_distance",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="parallelism_value",
                display_name="Parallelism Value",
                payload_type_id="value.v1",
                source_node_id="parallelism",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="parallelism_summary",
                display_name="Parallelism Summary",
                payload_type_id="value.v1",
                source_node_id="parallelism",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="slot_width_value",
                display_name="Slot Width Value",
                payload_type_id="value.v1",
                source_node_id="slot_width",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="slot_width_summary",
                display_name="Slot Width Summary",
                payload_type_id="value.v1",
                source_node_id="slot_width",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/line-pair-measure.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch5-line-pair-measure",
        },
    )

    point_distance_value = execution_result.outputs["point_distance_value"]
    parallelism_value = execution_result.outputs["parallelism_value"]
    parallelism_summary = execution_result.outputs["parallelism_summary"]
    slot_width_value = execution_result.outputs["slot_width_value"]
    slot_width_summary = execution_result.outputs["slot_width_summary"]

    assert 38.0 <= float(point_distance_value["value"]) <= 46.0
    assert float(parallelism_value["value"]) <= 2.0
    assert float(parallelism_summary["value"]["abs_delta_angle_deg"]) <= 2.0
    assert 38.0 <= float(slot_width_value["value"]) <= 46.0
    assert 38.0 <= float(slot_width_summary["value"]["mean_width_pixels"]) <= 46.0


def test_opencv_basic_batch5_circle_pair_measurement_nodes_execute(tmp_path: Path) -> None:
    """验证同心度和孔径量测节点可接成圆环量测链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/circle-pair-measure.png", _build_circle_pair_measure_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch5-circle-pair-measure",
        template_version="1.0.0",
        display_name="OpenCV Batch5 Circle Pair Measure",
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
                node_id="diameter",
                node_type_id="custom.opencv.circle-diameter",
                parameters={"circle_strategy": "smallest", "output_metric": "diameter"},
            ),
            WorkflowGraphNode(
                node_id="concentricity",
                node_type_id="custom.opencv.concentricity-metrics",
                parameters={
                    "circle_a_strategy": "largest",
                    "circle_b_strategy": "smallest",
                    "output_metric": "center_distance_pixels",
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-otsu-circle-pair",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-otsu-contour-circle-pair",
                source_node_id="otsu",
                source_port="image",
                target_node_id="contour",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-filter-circle-pair",
                source_node_id="contour",
                source_port="contours",
                target_node_id="filter",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-filter-circle-circle-pair",
                source_node_id="filter",
                source_port="contours",
                target_node_id="circle",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-circle-diameter-circle-pair",
                source_node_id="circle",
                source_port="circles",
                target_node_id="diameter",
                target_port="circles",
            ),
            WorkflowGraphEdge(
                edge_id="edge-circle-concentricity-circle-pair",
                source_node_id="circle",
                source_port="circles",
                target_node_id="concentricity",
                target_port="circles",
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
                output_id="diameter_value",
                display_name="Diameter Value",
                payload_type_id="value.v1",
                source_node_id="diameter",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="diameter_summary",
                display_name="Diameter Summary",
                payload_type_id="value.v1",
                source_node_id="diameter",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="concentricity_value",
                display_name="Concentricity Value",
                payload_type_id="value.v1",
                source_node_id="concentricity",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="concentricity_summary",
                display_name="Concentricity Summary",
                payload_type_id="value.v1",
                source_node_id="concentricity",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/circle-pair-measure.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch5-circle-pair-measure",
        },
    )

    diameter_value = execution_result.outputs["diameter_value"]
    diameter_summary = execution_result.outputs["diameter_summary"]
    concentricity_value = execution_result.outputs["concentricity_value"]
    concentricity_summary = execution_result.outputs["concentricity_summary"]

    assert 34.0 <= float(diameter_value["value"]) <= 40.0
    assert 34.0 <= float(diameter_summary["value"]["diameter"]) <= 40.0
    assert float(concentricity_value["value"]) <= 1.5
    assert float(concentricity_summary["value"]["center_distance_pixels"]) <= 1.5


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
