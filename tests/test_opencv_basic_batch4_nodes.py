"""OpenCV 第四批工业量测节点测试。"""

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


def test_opencv_basic_batch4_line_measurement_nodes_execute(tmp_path: Path) -> None:
    """验证 fit-line、point-to-line-distance 与 line-angle 可接成量测链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/line-measure.png", _build_line_measure_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch4-line-measure",
        template_version="1.0.0",
        display_name="OpenCV Batch4 Line Measure",
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
            WorkflowGraphNode(
                node_id="distance",
                node_type_id="custom.opencv.point-to-line-distance",
                parameters={"line_strategy": "longest", "output_metric": "distance_pixels"},
            ),
            WorkflowGraphNode(
                node_id="angle",
                node_type_id="custom.opencv.line-angle",
                parameters={
                    "line_strategy": "longest",
                    "reference_angle_deg": 0.0,
                    "output_metric": "delta_angle_deg",
                },
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
                edge_id="edge-contour-fit",
                source_node_id="contour",
                source_port="contours",
                target_node_id="fit",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-fit-distance-lines",
                source_node_id="fit",
                source_port="lines",
                target_node_id="distance",
                target_port="lines",
            ),
            WorkflowGraphEdge(
                edge_id="edge-fit-angle-lines",
                source_node_id="fit",
                source_port="lines",
                target_node_id="angle",
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
            WorkflowGraphInput(
                input_id="request_point",
                display_name="Request Point",
                payload_type_id="value.v1",
                target_node_id="distance",
                target_port="point",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="distance_value",
                display_name="Distance Value",
                payload_type_id="value.v1",
                source_node_id="distance",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="distance_summary",
                display_name="Distance Summary",
                payload_type_id="value.v1",
                source_node_id="distance",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="angle_value",
                display_name="Angle Value",
                payload_type_id="value.v1",
                source_node_id="angle",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="angle_summary",
                display_name="Angle Summary",
                payload_type_id="value.v1",
                source_node_id="angle",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/line-measure.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            },
            "request_point": {"value": [48.0, 52.0]},
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch4-line-measure",
        },
    )

    distance_value = execution_result.outputs["distance_value"]
    distance_summary = execution_result.outputs["distance_summary"]
    angle_value = execution_result.outputs["angle_value"]
    angle_summary = execution_result.outputs["angle_summary"]

    assert 15.0 <= float(distance_value["value"]) <= 25.0
    assert distance_summary["value"]["selected_line_index"] >= 1
    assert distance_summary["value"]["distance_pixels"] >= 15.0
    assert abs(float(angle_value["value"])) <= 3.0
    assert abs(float(angle_summary["value"]["delta_angle_deg"])) <= 3.0


def test_opencv_basic_batch4_circle_diameter_execute(tmp_path: Path) -> None:
    """验证 min-enclosing-circle 与 circle-diameter 可接成孔径量测链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/circle-measure.png", _build_circle_measure_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch4-circle-measure",
        template_version="1.0.0",
        display_name="OpenCV Batch4 Circle Measure",
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
                node_id="circle",
                node_type_id="custom.opencv.min-enclosing-circle",
                parameters={"sort_by": "radius", "descending": True},
            ),
            WorkflowGraphNode(
                node_id="diameter",
                node_type_id="custom.opencv.circle-diameter",
                parameters={"circle_strategy": "largest", "output_metric": "diameter"},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-otsu-circle",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-otsu-contour-circle",
                source_node_id="otsu",
                source_port="image",
                target_node_id="contour",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-circle",
                source_node_id="contour",
                source_port="contours",
                target_node_id="circle",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-circle-diameter",
                source_node_id="circle",
                source_port="circles",
                target_node_id="diameter",
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
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/circle-measure.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch4-circle-measure",
        },
    )

    diameter_value = execution_result.outputs["diameter_value"]
    diameter_summary = execution_result.outputs["diameter_summary"]

    assert 34.0 <= float(diameter_value["value"]) <= 40.0
    assert 34.0 <= float(diameter_summary["value"]["diameter"]) <= 40.0
    assert diameter_summary["value"]["selected_circle_index"] >= 1


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


def _build_line_measure_test_png_bytes() -> bytes:
    """构建可稳定拟合水平直线的测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((96, 96, 3), dtype=np.uint8)
    cv2.line(image, (10, 30), (84, 30), (255, 255, 255), thickness=6)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_circle_measure_test_png_bytes() -> bytes:
    """构建可稳定拟合圆的测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((96, 96, 3), dtype=np.uint8)
    cv2.circle(image, (48, 48), 18, (255, 255, 255), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
