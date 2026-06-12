"""OpenCV 第十二批缺陷调试节点测试。"""

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


def test_opencv_defect_batch12_heatmap_preview_execute(tmp_path: Path) -> None:
    """验证 heatmap-preview 可把强度图渲染为带底图叠加的伪彩色预览。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    source_bytes, base_bytes = _build_heatmap_test_png_bytes()
    dataset_storage.write_bytes("inputs/heatmap-source-b12.png", source_bytes)
    dataset_storage.write_bytes("inputs/heatmap-base-b12.png", base_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch12-heatmap-preview",
        template_version="1.0.0",
        display_name="OpenCV Batch12 Heatmap Preview",
        nodes=(
            WorkflowGraphNode(
                node_id="heatmap",
                node_type_id="custom.opencv.heatmap-preview",
                parameters={"colormap": "turbo", "normalize_mode": "minmax", "blend_alpha": 0.5},
            ),
        ),
        edges=(),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="heatmap",
                target_port="image",
            ),
            WorkflowGraphInput(
                input_id="request_base_image",
                display_name="Request Base Image",
                payload_type_id="image-ref.v1",
                target_node_id="heatmap",
                target_port="base_image",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="heatmap_image",
                display_name="Heatmap Image",
                payload_type_id="image-ref.v1",
                source_node_id="heatmap",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="heatmap_summary",
                display_name="Heatmap Summary",
                payload_type_id="value.v1",
                source_node_id="heatmap",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/heatmap-source-b12.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            },
            "request_base_image": {
                "object_key": "inputs/heatmap-base-b12.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch12-heatmap-preview",
        },
    )

    heatmap_image = execution_result.outputs["heatmap_image"]
    heatmap_summary = execution_result.outputs["heatmap_summary"]

    import cv2
    import numpy as np

    preview_matrix = cv2.imdecode(
        np.frombuffer(image_registry.read_bytes(str(heatmap_image["image_handle"])), dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )

    assert heatmap_image["transport_kind"] == "memory"
    assert heatmap_image["width"] == 96
    assert heatmap_image["height"] == 96
    assert preview_matrix.shape == (96, 96, 3)
    assert heatmap_summary["value"]["colormap"] == "turbo"
    assert heatmap_summary["value"]["normalize_mode"] == "minmax"
    assert heatmap_summary["value"]["used_base_image"] is True
    assert heatmap_summary["value"]["normalized_max"] == 255
    assert heatmap_summary["value"]["hotspot_pixel_ratio"] > 0
    assert int(preview_matrix[48, 48, 0]) != int(preview_matrix[8, 8, 0])


def test_opencv_defect_batch12_watershed_execute(tmp_path: Path) -> None:
    """验证 watershed 可把粘连前景拆分后继续接 connected-components。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    watershed_input_bytes = _build_watershed_test_png_bytes()
    dataset_storage.write_bytes("inputs/watershed-source-b12.png", watershed_input_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch12-watershed",
        template_version="1.0.0",
        display_name="OpenCV Batch12 Watershed",
        nodes=(
                WorkflowGraphNode(
                    node_id="watershed",
                    node_type_id="custom.opencv.watershed",
                    parameters={"foreground_threshold": 1, "distance_threshold_ratio": 0.55},
                ),
            WorkflowGraphNode(
                node_id="components",
                node_type_id="custom.opencv.connected-components",
                parameters={"foreground_threshold": 0, "class_name_default": "blob"},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-watershed-components-b12",
                source_node_id="watershed",
                source_port="image",
                target_node_id="components",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-components-source-b12",
                source_node_id="watershed",
                source_port="image",
                target_node_id="components",
                target_port="source_image",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="watershed",
                target_port="image",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="watershed_image",
                display_name="Watershed Image",
                payload_type_id="image-ref.v1",
                source_node_id="watershed",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="watershed_summary",
                display_name="Watershed Summary",
                payload_type_id="value.v1",
                source_node_id="watershed",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
                source_node_id="components",
                source_port="regions",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/watershed-source-b12.png",
                "width": 128,
                "height": 96,
                "media_type": "image/png",
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-batch12-watershed",
        },
    )

    watershed_summary = execution_result.outputs["watershed_summary"]
    regions = execution_result.outputs["regions"]

    assert watershed_summary["value"]["seed_component_count"] >= 2
    assert watershed_summary["value"]["watershed_region_count"] >= 2
    assert watershed_summary["value"]["boundary_pixel_count"] > 0
    assert regions["count"] >= 2


def test_opencv_defect_batch12_skeletonize_execute(tmp_path: Path) -> None:
    """验证 skeletonize 可把粗线前景规整成更细的骨架图。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    skeleton_input_bytes = _build_skeleton_test_png_bytes()
    dataset_storage.write_bytes("inputs/skeleton-source-b12.png", skeleton_input_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch12-skeletonize",
        template_version="1.0.0",
        display_name="OpenCV Batch12 Skeletonize",
        nodes=(
            WorkflowGraphNode(
                node_id="skeleton",
                node_type_id="custom.opencv.skeletonize",
                parameters={"foreground_threshold": 1},
            ),
        ),
        edges=(),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="skeleton",
                target_port="image",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="skeleton_image",
                display_name="Skeleton Image",
                payload_type_id="image-ref.v1",
                source_node_id="skeleton",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="skeleton_summary",
                display_name="Skeleton Summary",
                payload_type_id="value.v1",
                source_node_id="skeleton",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/skeleton-source-b12.png",
                "width": 128,
                "height": 96,
                "media_type": "image/png",
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch12-skeletonize",
        },
    )

    skeleton_image = execution_result.outputs["skeleton_image"]
    skeleton_summary = execution_result.outputs["skeleton_summary"]

    import cv2
    import numpy as np

    skeleton_matrix = cv2.imdecode(
        np.frombuffer(image_registry.read_bytes(str(skeleton_image["image_handle"])), dtype=np.uint8),
        cv2.IMREAD_GRAYSCALE,
    )

    assert skeleton_summary["value"]["iteration_count"] > 0
    assert skeleton_summary["value"]["input_foreground_pixel_count"] > skeleton_summary["value"]["skeleton_pixel_count"]
    assert skeleton_summary["value"]["skeleton_ratio"] < 1.0
    assert int(np.count_nonzero(skeleton_matrix)) == skeleton_summary["value"]["skeleton_pixel_count"]


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


def _build_heatmap_test_png_bytes() -> tuple[bytes, bytes]:
    """构造热力图测试输入。"""

    import cv2
    import numpy as np

    source_image = np.zeros((96, 96), dtype=np.uint8)
    cv2.circle(source_image, (48, 48), 18, 180, thickness=-1)
    cv2.rectangle(source_image, (16, 62), (34, 82), 255, thickness=-1)
    cv2.line(source_image, (10, 16), (86, 16), 96, thickness=3)

    base_image = np.full((96, 96, 3), 36, dtype=np.uint8)
    cv2.rectangle(base_image, (12, 12), (84, 84), (72, 72, 72), thickness=2)
    cv2.circle(base_image, (48, 48), 20, (96, 96, 96), thickness=1)

    source_success, source_encoded = cv2.imencode(".png", source_image)
    base_success, base_encoded = cv2.imencode(".png", base_image)
    assert source_success is True
    assert base_success is True
    return source_encoded.tobytes(), base_encoded.tobytes()


def _build_watershed_test_png_bytes() -> bytes:
    """构造粘连前景测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((96, 128), dtype=np.uint8)
    cv2.circle(image, (42, 48), 20, 200, thickness=-1)
    cv2.circle(image, (86, 48), 20, 220, thickness=-1)
    cv2.rectangle(image, (58, 42), (70, 54), 170, thickness=-1)
    image = cv2.GaussianBlur(image, (7, 7), 0)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_skeleton_test_png_bytes() -> bytes:
    """构造骨架化测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((96, 128), dtype=np.uint8)
    cv2.line(image, (18, 72), (108, 20), 255, thickness=12)
    cv2.rectangle(image, (24, 24), (56, 48), 255, thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
