"""OpenCV 第十四批 affine-transform 节点测试。"""

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


def test_opencv_basic_batch14_affine_transform_with_point_pairs_execute(tmp_path: Path) -> None:
    """验证 affine-transform 可按三对点把平行四边形收正到规则矩形。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/affine-b14.png", _build_affine_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch14-affine-point-pairs",
        template_version="1.0.0",
        display_name="OpenCV Batch14 Affine Point Pairs",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="warp",
                node_type_id="custom.opencv.affine-transform",
                parameters={
                    "source_points": [[20, 20], [95, 18], [108, 70]],
                    "target_points": [[0, 0], [79, 0], [79, 59]],
                    "output_width": 80,
                    "output_height": 60,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-affine-b14",
                source_node_id="input",
                source_port="image",
                target_node_id="warp",
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
                output_id="warped_image",
                display_name="Warped Image",
                payload_type_id="image-ref.v1",
                source_node_id="warp",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="warp_summary",
                display_name="Warp Summary",
                payload_type_id="value.v1",
                source_node_id="warp",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/affine-b14.png",
                "width": 140,
                "height": 100,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch14-affine-point-pairs",
        },
    )

    warped_image = execution_result.outputs["warped_image"]
    warp_summary = execution_result.outputs["warp_summary"]

    warped_matrix = image_registry.read_matrix(str(warped_image["image_handle"]))
    assert warped_matrix is not None

    assert warped_image["transport_kind"] == "memory"
    assert warped_image["width"] == 80
    assert warped_image["height"] == 60
    assert warp_summary["value"]["source_kind"] == "parameters"
    assert warp_summary["value"]["transform_kind"] == "point-pairs"
    assert warp_summary["value"]["output_size_source"] == "parameters"
    assert warped_matrix.shape[1] == 80
    assert warped_matrix.shape[0] == 60
    assert int(warped_matrix[3, 3, 2]) > 150
    assert int(warped_matrix[3, 76, 1]) > 150
    assert int(warped_matrix[56, 76, 0]) > 150
    assert int(warped_matrix[56, 3, 1]) > 150 and int(warped_matrix[56, 3, 2]) > 150


def test_opencv_basic_batch14_affine_transform_with_input_matrix_execute(tmp_path: Path) -> None:
    """验证 affine-transform 可读取 value.v1 里的仿射矩阵并按 fit_output_bounds 扩展输出。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/affine-b14-scale.png", _build_affine_scale_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch14-affine-input-matrix",
        template_version="1.0.0",
        display_name="OpenCV Batch14 Affine Input Matrix",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(node_id="transform", node_type_id="core.io.template-input.value"),
            WorkflowGraphNode(
                node_id="warp",
                node_type_id="custom.opencv.affine-transform",
                parameters={"transform_path": "ops.affine"},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-affine-input-b14",
                source_node_id="input",
                source_port="image",
                target_node_id="warp",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-transform-affine-input-b14",
                source_node_id="transform",
                source_port="value",
                target_node_id="warp",
                target_port="transform",
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
                input_id="request_transform",
                display_name="Request Transform",
                payload_type_id="value.v1",
                target_node_id="transform",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="warped_image",
                display_name="Warped Image",
                payload_type_id="image-ref.v1",
                source_node_id="warp",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="warp_summary",
                display_name="Warp Summary",
                payload_type_id="value.v1",
                source_node_id="warp",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/affine-b14-scale.png",
                "width": 30,
                "height": 20,
                "media_type": "image/png",
            },
            "request_transform": {
                "value": {
                    "ops": {
                        "affine": {
                            "matrix_2x3": [[1.5, 0.0, 0.0], [0.0, 1.25, 0.0]],
                            "fit_output_bounds": True,
                        }
                    }
                }
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch14-affine-input-matrix",
        },
    )

    warped_image = execution_result.outputs["warped_image"]
    warp_summary = execution_result.outputs["warp_summary"]

    warped_matrix = image_registry.read_matrix(str(warped_image["image_handle"]))
    assert warped_matrix is not None

    assert warped_image["transport_kind"] == "memory"
    assert warped_image["width"] == 45
    assert warped_image["height"] == 25
    assert warp_summary["value"]["source_kind"] == "input"
    assert warp_summary["value"]["transform_kind"] == "matrix"
    assert warp_summary["value"]["output_size_source"] == "fit-bounds"
    assert warp_summary["value"]["fit_output_bounds"] is True
    assert warped_matrix.shape[1] == 45
    assert warped_matrix.shape[0] == 25
    assert int(warped_matrix[1, 1, 2]) > 150
    assert int(warped_matrix[15, 30, 2]) > 150
    assert int(warped_matrix[10, 10, 1]) > 150


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


def _build_affine_test_png_bytes() -> bytes:
    """构造平行四边形仿射矫正测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((100, 140, 3), dtype=np.uint8)
    polygon = np.array([[20, 20], [95, 18], [108, 70], [33, 72]], dtype=np.int32)
    cv2.fillConvexPoly(image, polygon, (220, 220, 220))
    cv2.circle(image, (20, 20), 6, (0, 0, 255), thickness=-1)
    cv2.circle(image, (95, 18), 6, (0, 255, 0), thickness=-1)
    cv2.circle(image, (108, 70), 6, (255, 0, 0), thickness=-1)
    cv2.circle(image, (33, 72), 6, (0, 255, 255), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_affine_scale_test_png_bytes() -> bytes:
    """构造仿射缩放测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((20, 30, 3), dtype=np.uint8)
    cv2.rectangle(image, (0, 0), (24, 14), (0, 0, 220), thickness=-1)
    cv2.rectangle(image, (6, 4), (18, 10), (0, 255, 0), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
