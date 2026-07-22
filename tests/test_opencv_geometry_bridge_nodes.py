"""OpenCV 几何桥接节点运行时测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes import ExecutionImageRegistry
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_opencv_geometry_planar_transform_bridge_warp_and_roi_execute(tmp_path: Path) -> None:
    """验证 planar-transform-bridge 可把图片与 ROI 一起投影到目标参考帧。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/bridge-source.png", _build_bridge_source_png_bytes())

    execution_result = executor.execute(
        template=_build_planar_bridge_template(
            template_id="opencv-geometry-planar-bridge-forward",
            parameters={
                "direction": "source-a-to-source-b",
                "output_display_name": "Reference ROI",
            },
        ),
        input_values={
            "request_image_base64": {
                "object_key": "inputs/bridge-source.png",
                "width": 40,
                "height": 30,
                "media_type": "image/png",
            },
            "request_transform": _build_translation_planar_transform_payload(include_inverse_matrix=True),
            "request_roi": _build_source_roi_payload(),
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-geometry-planar-bridge-forward",
        },
    )

    warped_image = execution_result.outputs["warped_image"]
    projected_roi = execution_result.outputs["projected_roi"]
    bridge_summary = execution_result.outputs["bridge_summary"]

    warped_matrix = image_registry.read_matrix(str(warped_image["image_handle"]))
    assert warped_matrix is not None

    assert warped_image["transport_kind"] == "memory"
    assert warped_image["width"] == 70
    assert warped_image["height"] == 60
    assert bridge_summary["value"]["direction"] == "source-a-to-source-b"
    assert bridge_summary["value"]["matrix_source"] == "matrix_3x3"
    assert bridge_summary["value"]["output_size_source"] == "transform-target-image"
    assert bridge_summary["value"]["output_roi_id"] == "work-area-a2b"
    assert projected_roi["roi_id"] == "work-area-a2b"
    assert projected_roi["display_name"] == "Reference ROI"
    assert projected_roi["source_image"]["width"] == 70
    assert projected_roi["source_image"]["height"] == 60
    assert projected_roi["bbox_xyxy"] == [15.0, 11.0, 31.0, 23.0]
    assert projected_roi["area"] == 192
    assert int(warped_matrix[12, 17, 2]) > 180
    assert int(warped_matrix[21, 32, 1]) > 180


def test_opencv_geometry_planar_transform_bridge_reverse_roi_execute(tmp_path: Path) -> None:
    """验证 planar-transform-bridge 可在缺少 inverse 时按需要反向求逆投影 ROI。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)

    execution_result = executor.execute(
        template=_build_planar_bridge_template(
            template_id="opencv-geometry-planar-bridge-reverse",
            parameters={"direction": "source-b-to-source-a"},
            include_image_output=False,
        ),
        input_values={
            "request_transform": _build_translation_planar_transform_payload(include_inverse_matrix=False),
            "request_roi": _build_reference_roi_payload(),
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-geometry-planar-bridge-reverse",
        },
    )

    projected_roi = execution_result.outputs["projected_roi"]
    bridge_summary = execution_result.outputs["bridge_summary"]

    assert bridge_summary["value"]["direction"] == "source-b-to-source-a"
    assert bridge_summary["value"]["matrix_source"] == "computed-inverse"
    assert projected_roi["roi_id"] == "reference-work-area-b2a"
    assert projected_roi["bbox_xyxy"] == [5.0, 6.0, 21.0, 18.0]
    assert projected_roi["source_image"]["width"] == 40
    assert projected_roi["source_image"]["height"] == 30


def test_opencv_geometry_planar_transform_bridge_rejects_source_dimension_mismatch(
    tmp_path: Path,
) -> None:
    """验证 planar-transform-bridge 会显式拒绝与 transform 源图尺寸不一致的图片输入。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/bridge-source.png", _build_bridge_source_png_bytes())

    with pytest.raises(InvalidRequestError, match="分辨率与 transform 源图不一致"):
        executor.execute(
            template=_build_planar_bridge_template(
                template_id="opencv-geometry-planar-bridge-dimension-mismatch",
                parameters={"direction": "source-a-to-source-b"},
            ),
            input_values={
                "request_image_base64": {
                    "object_key": "inputs/bridge-source.png",
                    "width": 41,
                    "height": 30,
                    "media_type": "image/png",
                },
                "request_transform": _build_translation_planar_transform_payload(include_inverse_matrix=True),
                "request_roi": _build_source_roi_payload(),
            },
            execution_metadata={
                "dataset_storage": dataset_storage,
                "workflow_run_id": "opencv-geometry-planar-bridge-dimension-mismatch",
            },
        )


def _build_planar_bridge_template(
    *,
    template_id: str,
    parameters: dict[str, object],
    include_image_output: bool = True,
) -> WorkflowGraphTemplate:
    """构造用于 planar-transform-bridge 测试的最小模板。"""

    template_outputs = [
        WorkflowGraphOutput(
            output_id="projected_roi",
            display_name="Projected ROI",
            payload_type_id="roi.v1",
            source_node_id="bridge",
            source_port="roi",
        ),
        WorkflowGraphOutput(
            output_id="bridge_summary",
            display_name="Bridge Summary",
            payload_type_id="value.v1",
            source_node_id="bridge",
            source_port="summary",
        ),
    ]
    if include_image_output:
        template_outputs.insert(
            0,
            WorkflowGraphOutput(
                output_id="warped_image",
                display_name="Warped Image",
                payload_type_id="image-ref.v1",
                source_node_id="bridge",
                source_port="image",
            ),
        )

    template_inputs = [
        WorkflowGraphInput(
            input_id="request_transform",
            display_name="Request Transform",
            payload_type_id="planar-transform.v1",
            target_node_id="bridge",
            target_port="transform",
        ),
        WorkflowGraphInput(
            input_id="request_roi",
            display_name="Request ROI",
            payload_type_id="roi.v1",
            target_node_id="bridge",
            target_port="roi",
        ),
    ]
    if include_image_output:
        template_inputs.insert(
            0,
            WorkflowGraphInput(
                input_id="request_image_base64",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="bridge",
                target_port="image",
            ),
        )

    return WorkflowGraphTemplate(
        template_id=template_id,
        template_version="1.0.0",
        display_name="OpenCV Geometry Planar Transform Bridge",
        nodes=(
            WorkflowGraphNode(
                node_id="bridge",
                node_type_id="custom.opencv.planar-transform-bridge",
                parameters=parameters,
            ),
        ),
        template_inputs=tuple(template_inputs),
        template_outputs=tuple(template_outputs),
    )


def _build_translation_planar_transform_payload(*, include_inverse_matrix: bool) -> dict[str, object]:
    """构造纯平移的 planar-transform.v1。"""

    payload: dict[str, object] = {
        "transform_kind": "homography",
        "matrix_3x3": [[1.0, 0.0, 10.0], [0.0, 1.0, 5.0], [0.0, 0.0, 1.0]],
        "match_count": 24,
        "inlier_count": 20,
        "inlier_match_ids": ["m01", "m02", "m03", "m04"],
        "reprojection_error": 0.4,
        "source_a_image": {
            "transport_kind": "storage",
            "object_key": "inputs/bridge-source.png",
            "width": 40,
            "height": 30,
            "media_type": "image/png",
        },
        "source_b_image": {
            "transport_kind": "storage",
            "object_key": "inputs/bridge-reference.png",
            "width": 70,
            "height": 60,
            "media_type": "image/png",
        },
    }
    if include_inverse_matrix:
        payload["inverse_matrix_3x3"] = [[1.0, 0.0, -10.0], [0.0, 1.0, -5.0], [0.0, 0.0, 1.0]]
    return payload


def _build_source_roi_payload() -> dict[str, object]:
    """构造源图坐标系下的 ROI。"""

    return {
        "roi_id": "work-area",
        "roi_kind": "bbox",
        "bbox_xyxy": [5.0, 6.0, 21.0, 18.0],
        "polygon_xy": [[5.0, 6.0], [21.0, 6.0], [21.0, 18.0], [5.0, 18.0]],
        "area": 192,
        "source_image": {
            "transport_kind": "storage",
            "object_key": "inputs/bridge-source.png",
            "width": 40,
            "height": 30,
            "media_type": "image/png",
        },
    }


def _build_reference_roi_payload() -> dict[str, object]:
    """构造目标参考帧坐标系下的 ROI。"""

    return {
        "roi_id": "reference-work-area",
        "roi_kind": "bbox",
        "bbox_xyxy": [15.0, 11.0, 31.0, 23.0],
        "polygon_xy": [[15.0, 11.0], [31.0, 11.0], [31.0, 23.0], [15.0, 23.0]],
        "area": 192,
        "source_image": {
            "transport_kind": "storage",
            "object_key": "inputs/bridge-reference.png",
            "width": 70,
            "height": 60,
            "media_type": "image/png",
        },
    }


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


def _build_bridge_source_png_bytes() -> bytes:
    """构造用于平移桥接测试的彩色图片。"""

    import cv2
    import numpy as np

    image = np.zeros((30, 40, 3), dtype=np.uint8)
    image[4:12, 4:12] = (0, 0, 255)
    image[14:22, 19:27] = (0, 255, 0)
    image[8:14, 28:34] = (255, 0, 0)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
