"""OpenCV 第七批 ROI 与分割覆盖层节点测试。"""

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


def test_opencv_basic_batch7_draw_roi_execute(tmp_path: Path) -> None:
    """验证 roi-create 与 draw-roi 可接成现场 ROI 复核链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    source_bytes = _build_roi_render_test_png_bytes()
    dataset_storage.write_bytes("inputs/roi-render.png", source_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch7-draw-roi",
        template_version="1.0.0",
        display_name="OpenCV Batch7 Draw ROI",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi",
                node_type_id="core.vision.roi-create",
                parameters={
                    "roi_kind": "polygon",
                    "roi_id": "roi-sealant-window",
                    "display_name": "sealant-window",
                    "polygon_xy": [[16, 18], [104, 20], [96, 94], [22, 88]],
                },
            ),
            WorkflowGraphNode(
                node_id="draw_roi",
                node_type_id="custom.opencv.draw-roi",
                parameters={"fill_alpha": 0.22, "draw_bbox": True},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-roi-image-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="roi",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-draw-roi-image-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="draw_roi",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-draw-roi-b7",
                source_node_id="roi",
                source_port="roi",
                target_node_id="draw_roi",
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
                output_id="roi_overlay",
                display_name="ROI Overlay",
                payload_type_id="image-ref.v1",
                source_node_id="draw_roi",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/roi-render.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch7-draw-roi",
        },
    )

    roi_overlay = execution_result.outputs["roi_overlay"]
    roi_overlay_bytes = image_registry.read_bytes(str(roi_overlay["image_handle"]))

    assert roi_overlay["transport_kind"] == "memory"
    assert roi_overlay_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert roi_overlay_bytes != source_bytes


def test_opencv_basic_batch7_mask_overlay_execute(tmp_path: Path) -> None:
    """验证 connected-components 与 mask-overlay 可接成分割覆盖层调试链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    source_bytes = _build_mask_overlay_test_png_bytes()
    dataset_storage.write_bytes("inputs/mask-overlay.png", source_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch7-mask-overlay",
        template_version="1.0.0",
        display_name="OpenCV Batch7 Mask Overlay",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="otsu",
                node_type_id="custom.opencv.otsu-threshold",
                parameters={"threshold_type": "binary"},
            ),
            WorkflowGraphNode(
                node_id="components",
                node_type_id="custom.opencv.connected-components",
                parameters={"min_area": 40.0, "class_name_default": "defect-area"},
            ),
            WorkflowGraphNode(
                node_id="mask_overlay",
                node_type_id="custom.opencv.mask-overlay",
                parameters={"mask_alpha": 0.4, "draw_boxes": True, "draw_polygons": True},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-otsu-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-otsu-components-b7",
                source_node_id="otsu",
                source_port="image",
                target_node_id="components",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-components-source-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="components",
                target_port="source_image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-mask-overlay-image-b7",
                source_node_id="input",
                source_port="image",
                target_node_id="mask_overlay",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-components-mask-overlay-b7",
                source_node_id="components",
                source_port="regions",
                target_node_id="mask_overlay",
                target_port="regions",
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
                output_id="mask_overlay",
                display_name="Mask Overlay",
                payload_type_id="image-ref.v1",
                source_node_id="mask_overlay",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/mask-overlay.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch7-mask-overlay",
        },
    )

    mask_overlay = execution_result.outputs["mask_overlay"]
    mask_overlay_bytes = image_registry.read_bytes(str(mask_overlay["image_handle"]))

    assert mask_overlay["transport_kind"] == "memory"
    assert mask_overlay_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert mask_overlay_bytes != source_bytes


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


def _build_roi_render_test_png_bytes() -> bytes:
    """构造 ROI 调试测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((128, 128, 3), dtype=np.uint8)
    cv2.rectangle(image, (20, 24), (100, 92), (48, 48, 48), thickness=-1)
    cv2.line(image, (18, 96), (110, 96), (100, 100, 100), thickness=2)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_mask_overlay_test_png_bytes() -> bytes:
    """构造带两个明显前景块的分割覆盖层测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((128, 128, 3), dtype=np.uint8)
    cv2.rectangle(image, (18, 20), (56, 82), (255, 255, 255), thickness=-1)
    cv2.circle(image, (92, 70), 18, (255, 255, 255), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
