"""OpenCV 第十三批几何标定节点测试。"""

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


def test_opencv_basic_batch13_undistort_with_value_config_execute(tmp_path: Path) -> None:
    """验证 undistort 可读取 value.v1 标定配置并稳定输出矫正图。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    source_image_bytes = _build_geometry_test_png_bytes()
    dataset_storage.write_bytes("inputs/undistort-b13.png", source_image_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch13-undistort",
        template_version="1.0.0",
        display_name="OpenCV Batch13 Undistort",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(node_id="config", node_type_id="core.io.template-input.value"),
                WorkflowGraphNode(
                    node_id="undistort",
                    node_type_id="custom.opencv.undistort",
                    parameters={
                        "use_optimal_new_camera_matrix": False,
                        "crop_to_valid_roi": False,
                        "border_mode": "constant",
                        "border_value": 0,
                    },
                ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-undistort-b13",
                source_node_id="input",
                source_port="image",
                target_node_id="undistort",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-config-undistort-b13",
                source_node_id="config",
                source_port="value",
                target_node_id="undistort",
                target_port="config",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
            WorkflowGraphInput(
                input_id="request_config",
                display_name="Request Config",
                payload_type_id="value.v1",
                target_node_id="config",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="undistorted_image",
                display_name="Undistorted Image",
                payload_type_id="image-ref.v1",
                source_node_id="undistort",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="undistort_summary",
                display_name="Undistort Summary",
                payload_type_id="value.v1",
                source_node_id="undistort",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/undistort-b13.png",
                "width": 64,
                "height": 48,
                "media_type": "image/png",
            },
            "request_config": {
                "value": {
                    "camera_matrix": [[42.0, 0.0, 32.0], [0.0, 42.0, 24.0], [0.0, 0.0, 1.0]],
                    "distortion_coefficients": [0.0, 0.0, 0.0, 0.0, 0.0]
                }
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch13-undistort",
        },
    )

    undistorted_image = execution_result.outputs["undistorted_image"]
    undistort_summary = execution_result.outputs["undistort_summary"]

    import cv2
    import numpy as np

    source_matrix = cv2.imdecode(
        np.frombuffer(source_image_bytes, dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )
    undistorted_matrix = cv2.imdecode(
        np.frombuffer(image_registry.read_bytes(str(undistorted_image["image_handle"])), dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )

    assert undistorted_image["transport_kind"] == "memory"
    assert undistorted_image["width"] == 64
    assert undistorted_image["height"] == 48
    assert undistort_summary["value"]["config_source"] == "input"
    assert undistort_summary["value"]["output_size_source"] == "source-image"
    assert undistort_summary["value"]["use_optimal_new_camera_matrix"] is False
    assert undistort_summary["value"]["distortion_coefficient_count"] == 5
    assert float(np.mean(np.abs(source_matrix.astype(np.int16) - undistorted_matrix.astype(np.int16)))) < 1.0


def test_opencv_basic_batch13_remap_with_value_mapping_execute(tmp_path: Path) -> None:
    """验证 remap 可读取 value.v1 map_xy 并执行像素级几何重映射。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/remap-b13.png", _build_remap_test_png_bytes())

    map_xy = _build_shift_map_xy(width=20, height=16, shift_x=3, shift_y=2)
    template = WorkflowGraphTemplate(
        template_id="opencv-batch13-remap",
        template_version="1.0.0",
        display_name="OpenCV Batch13 Remap",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(node_id="mapping", node_type_id="core.io.template-input.value"),
            WorkflowGraphNode(
                node_id="remap",
                node_type_id="custom.opencv.remap",
                parameters={"border_mode": "constant", "border_value": 0},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-remap-b13",
                source_node_id="input",
                source_port="image",
                target_node_id="remap",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-mapping-remap-b13",
                source_node_id="mapping",
                source_port="value",
                target_node_id="remap",
                target_port="mapping",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
            WorkflowGraphInput(
                input_id="request_mapping",
                display_name="Request Mapping",
                payload_type_id="value.v1",
                target_node_id="mapping",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="remapped_image",
                display_name="Remapped Image",
                payload_type_id="image-ref.v1",
                source_node_id="remap",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="remap_summary",
                display_name="Remap Summary",
                payload_type_id="value.v1",
                source_node_id="remap",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/remap-b13.png",
                "width": 20,
                "height": 16,
                "media_type": "image/png",
            },
            "request_mapping": {
                "value": {
                    "map_xy": map_xy
                }
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch13-remap",
        },
    )

    remapped_image = execution_result.outputs["remapped_image"]
    remap_summary = execution_result.outputs["remap_summary"]

    import cv2
    import numpy as np

    remapped_matrix = cv2.imdecode(
        np.frombuffer(image_registry.read_bytes(str(remapped_image["image_handle"])), dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )

    assert remapped_image["transport_kind"] == "memory"
    assert remapped_image["width"] == 20
    assert remapped_image["height"] == 16
    assert remap_summary["value"]["mapping_source"] == "input"
    assert remap_summary["value"]["map_kind"] == "map_xy"
    assert int(remapped_matrix[6, 7, 2]) > 150
    assert int(remapped_matrix[4, 4, 2]) < 20


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


def _build_geometry_test_png_bytes() -> bytes:
    """构造几何校正测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((48, 64, 3), dtype=np.uint8)
    cv2.rectangle(image, (8, 8), (56, 40), (220, 220, 220), thickness=-1)
    cv2.circle(image, (16, 16), 4, (0, 0, 255), thickness=-1)
    cv2.circle(image, (48, 16), 4, (0, 255, 0), thickness=-1)
    cv2.circle(image, (32, 32), 4, (255, 0, 0), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_remap_test_png_bytes() -> bytes:
    """构造 remap 位移测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((16, 20, 3), dtype=np.uint8)
    cv2.rectangle(image, (4, 4), (7, 7), (0, 0, 255), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_shift_map_xy(*, width: int, height: int, shift_x: int, shift_y: int) -> list[list[list[float]]]:
    """构造固定平移的 map_xy。"""

    map_xy: list[list[list[float]]] = []
    for output_y in range(height):
        row_values: list[list[float]] = []
        for output_x in range(width):
            row_values.append([float(output_x - shift_x), float(output_y - shift_y)])
        map_xy.append(row_values)
    return map_xy
