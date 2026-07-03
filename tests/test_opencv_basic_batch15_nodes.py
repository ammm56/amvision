"""OpenCV 第十五批边缘增强节点测试。"""

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


def test_opencv_basic_batch15_sobel_xy_execute(tmp_path: Path) -> None:
    """验证 sobel 可输出稳定的 xy 边缘增强图和摘要。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/sobel-b15.png", _build_edge_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch15-sobel",
        template_version="1.0.0",
        display_name="OpenCV Batch15 Sobel",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="sobel",
                node_type_id="custom.opencv.sobel",
                parameters={"direction": "xy", "kernel_size": 3},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-sobel-b15",
                source_node_id="input",
                source_port="image",
                target_node_id="sobel",
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
                output_id="edge_image",
                display_name="Edge Image",
                payload_type_id="image-ref.v1",
                source_node_id="sobel",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="edge_summary",
                display_name="Edge Summary",
                payload_type_id="value.v1",
                source_node_id="sobel",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/sobel-b15.png",
                "width": 32,
                "height": 24,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch15-sobel",
        },
    )

    edge_image = execution_result.outputs["edge_image"]
    edge_summary = execution_result.outputs["edge_summary"]

    import cv2
    import numpy as np

    edge_matrix = cv2.imdecode(
        np.frombuffer(image_registry.read_bytes(str(edge_image["image_handle"])), dtype=np.uint8),
        cv2.IMREAD_GRAYSCALE,
    )

    assert edge_image["transport_kind"] == "memory"
    assert edge_image["width"] == 32
    assert edge_image["height"] == 24
    assert edge_summary["value"]["direction"] == "xy"
    assert edge_summary["value"]["kernel_size"] == 3
    assert edge_summary["value"]["convert_to_grayscale"] is True
    assert edge_summary["value"]["max_edge_intensity"] > 200
    assert edge_summary["value"]["non_zero_pixel_count"] > 0
    assert int(edge_matrix[6, 14]) > 150
    assert int(edge_matrix[12, 8]) > 150
    assert int(edge_matrix[12, 16]) < 20


def test_opencv_basic_batch15_laplacian_color_execute(tmp_path: Path) -> None:
    """验证 laplacian 可在彩色模式下输出稳定边缘增强图和摘要。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/laplacian-b15.png", _build_color_edge_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch15-laplacian",
        template_version="1.0.0",
        display_name="OpenCV Batch15 Laplacian",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="laplacian",
                node_type_id="custom.opencv.laplacian",
                parameters={"kernel_size": 3, "convert_to_grayscale": False},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-laplacian-b15",
                source_node_id="input",
                source_port="image",
                target_node_id="laplacian",
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
                output_id="edge_image",
                display_name="Edge Image",
                payload_type_id="image-ref.v1",
                source_node_id="laplacian",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="edge_summary",
                display_name="Edge Summary",
                payload_type_id="value.v1",
                source_node_id="laplacian",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/laplacian-b15.png",
                "width": 32,
                "height": 24,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch15-laplacian",
        },
    )

    edge_image = execution_result.outputs["edge_image"]
    edge_summary = execution_result.outputs["edge_summary"]

    import cv2
    import numpy as np

    edge_matrix = cv2.imdecode(
        np.frombuffer(image_registry.read_bytes(str(edge_image["image_handle"])), dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )

    assert edge_image["transport_kind"] == "memory"
    assert edge_image["width"] == 32
    assert edge_image["height"] == 24
    assert edge_summary["value"]["kernel_size"] == 3
    assert edge_summary["value"]["convert_to_grayscale"] is False
    assert edge_summary["value"]["max_edge_intensity"] > 200
    assert edge_summary["value"]["non_zero_pixel_count"] > 0
    assert int(edge_matrix[12, 8, 1]) > 150
    assert int(edge_matrix[12, 16, 1]) < 20


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


def _build_edge_test_png_bytes() -> bytes:
    """构造 Sobel 测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((24, 32), dtype=np.uint8)
    cv2.rectangle(image, (8, 6), (24, 18), 220, thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_color_edge_test_png_bytes() -> bytes:
    """构造 Laplacian 彩色测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((24, 32, 3), dtype=np.uint8)
    cv2.rectangle(image, (8, 6), (24, 18), (0, 220, 0), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
