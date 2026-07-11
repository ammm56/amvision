"""OpenCV 第八批模板匹配节点测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
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


def test_opencv_basic_batch8_template_match_execute(tmp_path: Path) -> None:
    """验证 template-match 可输出多目标 regions 并进入工业规则链入口形状。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    source_bytes, template_bytes = _build_template_match_test_png_bytes()
    dataset_storage.write_bytes("inputs/template-match-source.png", source_bytes)
    dataset_storage.write_bytes("inputs/template-match-template.png", template_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch8-template-match",
        template_version="1.0.0",
        display_name="OpenCV Batch8 Template Match",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(node_id="template_input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="match",
                node_type_id="custom.opencv.template-match",
                parameters={
                    "method": "ccoeff-normed",
                    "score_threshold": 0.99,
                    "max_matches": 4,
                    "nms_iou_threshold": 0.2,
                    "class_name_default": "fixture",
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-match-image-b8",
                source_node_id="input",
                source_port="image",
                target_node_id="match",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-template-input-match-template-b8",
                source_node_id="template_input",
                source_port="image",
                target_node_id="match",
                target_port="template_image",
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
                input_id="request_template_image",
                display_name="Request Template Image",
                payload_type_id="image-ref.v1",
                target_node_id="template_input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
                source_node_id="match",
                source_port="regions",
            ),
            WorkflowGraphOutput(
                output_id="summary",
                display_name="Summary",
                payload_type_id="value.v1",
                source_node_id="match",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/template-match-source.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            },
            "request_template_image": {
                "object_key": "inputs/template-match-template.png",
                "width": 18,
                "height": 18,
                "media_type": "image/png",
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-batch8-template-match",
        },
    )

    regions = execution_result.outputs["regions"]
    summary = execution_result.outputs["summary"]

    assert regions["count"] == 2
    assert [item["class_name"] for item in regions["items"]] == ["fixture", "fixture"]
    assert [item["region_id"] for item in regions["items"]] == ["tmpl-1", "tmpl-2"]
    assert [item["bbox_xyxy"] for item in regions["items"]] == [
        [16.0, 20.0, 34.0, 38.0],
        [74.0, 58.0, 92.0, 76.0],
    ]
    assert all(float(item["score"]) >= 0.99 for item in regions["items"])
    assert summary["value"]["match_count"] == 2
    assert summary["value"]["candidate_count"] >= 2
    assert summary["value"]["template_width"] == 18
    assert summary["value"]["template_height"] == 18
    assert summary["value"]["search_bbox_xyxy"] == [0, 0, 128, 128]
    assert "roi_polygon_bbox_only" not in summary["value"]


def test_opencv_basic_batch8_template_match_with_template_bbox_execute(tmp_path: Path) -> None:
    """验证 template-match 可直接从输入图 template_bbox_xyxy 裁出模板。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    source_bytes, _template_bytes = _build_template_match_test_png_bytes()
    dataset_storage.write_bytes("inputs/template-match-source.png", source_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch8-template-match-template-bbox",
        template_version="1.0.0",
        display_name="OpenCV Batch8 Template Match Template Bbox",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="match",
                node_type_id="custom.opencv.template-match",
                parameters={
                    "method": "ccoeff-normed",
                    "score_threshold": 0.99,
                    "max_matches": 4,
                    "nms_iou_threshold": 0.2,
                    "template_bbox_xyxy": [16, 20, 34, 38],
                    "search_bbox_xyxy": [0, 0, 128, 128],
                    "debug_image_panel_enabled": True,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-match-image-template-bbox-b8",
                source_node_id="input",
                source_port="image",
                target_node_id="match",
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
                output_id="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
                source_node_id="match",
                source_port="regions",
            ),
            WorkflowGraphOutput(
                output_id="summary",
                display_name="Summary",
                payload_type_id="value.v1",
                source_node_id="match",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/template-match-source.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-batch8-template-match-template-bbox",
            "debug_image_panels_enabled": True,
        },
    )

    regions = execution_result.outputs["regions"]
    summary = execution_result.outputs["summary"]
    debug_preview = _read_record_output(execution_result, node_id="match", output_name="debug_preview")
    interaction = debug_preview["interaction"]
    tools_by_name = {tool["tool"]: tool for tool in interaction["tools"]}

    assert regions["count"] == 2
    assert [item["bbox_xyxy"] for item in regions["items"]] == [
        [16.0, 20.0, 34.0, 38.0],
        [74.0, 58.0, 92.0, 76.0],
    ]
    assert summary["value"]["template_source"] == "template-bbox"
    assert summary["value"]["template_bbox_xyxy"] == [16, 20, 34, 38]
    assert summary["value"]["search_bbox_xyxy"] == [0, 0, 128, 128]
    assert set(tools_by_name["template-region"]["target_parameters"]) == {
        "template_bbox_xyxy",
        "search_bbox_xyxy",
    }


def test_opencv_basic_batch8_template_match_with_roi_execute(tmp_path: Path) -> None:
    """验证 template-match 可通过 roi.v1 只搜索局部窗口。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    source_bytes, template_bytes = _build_template_match_test_png_bytes()
    dataset_storage.write_bytes("inputs/template-match-source.png", source_bytes)
    dataset_storage.write_bytes("inputs/template-match-template.png", template_bytes)

    template = WorkflowGraphTemplate(
        template_id="opencv-batch8-template-match-roi",
        template_version="1.0.0",
        display_name="OpenCV Batch8 Template Match ROI",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(node_id="template_input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="roi",
                node_type_id="core.vision.roi-create",
                parameters={
                    "roi_kind": "bbox",
                    "roi_id": "fixture-window",
                    "display_name": "fixture-window",
                    "bbox_xyxy": [8, 10, 48, 48],
                },
            ),
            WorkflowGraphNode(
                node_id="match",
                node_type_id="custom.opencv.template-match",
                parameters={
                    "method": "ccoeff-normed",
                    "score_threshold": 0.99,
                    "max_matches": 2,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-roi-image-b8",
                source_node_id="input",
                source_port="image",
                target_node_id="roi",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-input-match-image-roi-b8",
                source_node_id="input",
                source_port="image",
                target_node_id="match",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-template-input-match-template-roi-b8",
                source_node_id="template_input",
                source_port="image",
                target_node_id="match",
                target_port="template_image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-roi-match-roi-b8",
                source_node_id="roi",
                source_port="roi",
                target_node_id="match",
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
            WorkflowGraphInput(
                input_id="request_template_image",
                display_name="Request Template Image",
                payload_type_id="image-ref.v1",
                target_node_id="template_input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
                source_node_id="match",
                source_port="regions",
            ),
            WorkflowGraphOutput(
                output_id="summary",
                display_name="Summary",
                payload_type_id="value.v1",
                source_node_id="match",
                source_port="summary",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/template-match-source.png",
                "width": 128,
                "height": 128,
                "media_type": "image/png",
            },
            "request_template_image": {
                "object_key": "inputs/template-match-template.png",
                "width": 18,
                "height": 18,
                "media_type": "image/png",
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-batch8-template-match-roi",
        },
    )

    regions = execution_result.outputs["regions"]
    summary = execution_result.outputs["summary"]

    assert regions["count"] == 1
    assert regions["items"][0]["bbox_xyxy"] == [16.0, 20.0, 34.0, 38.0]
    assert summary["value"]["match_count"] == 1
    assert summary["value"]["roi_id"] == "fixture-window"
    assert summary["value"]["roi_kind"] == "bbox"
    assert summary["value"]["search_bbox_xyxy"] == [8, 10, 48, 48]
    assert summary["value"]["roi_polygon_bbox_only"] is False


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


def _read_record_output(execution_result: object, *, node_id: str, output_name: str) -> dict[str, object]:
    """读取节点记录中的调试输出，避免把 debug preview 当成业务输出强绑定。"""

    node_records = getattr(execution_result, "node_records")
    for node_record in node_records:
        if node_record.node_id != node_id:
            continue
        output_payload = node_record.outputs.get(output_name)
        assert isinstance(output_payload, dict)
        return output_payload
    raise AssertionError(f"node record output not found: {node_id}.{output_name}")


def _build_template_match_test_png_bytes() -> tuple[bytes, bytes]:
    """构造模板匹配测试图片与模板图片。"""

    import cv2
    import numpy as np

    source_image = np.zeros((128, 128, 3), dtype=np.uint8)
    template_image = np.zeros((18, 18, 3), dtype=np.uint8)
    cv2.rectangle(template_image, (2, 3), (14, 14), (210, 210, 210), thickness=-1)
    cv2.rectangle(template_image, (4, 5), (8, 9), (30, 30, 30), thickness=-1)
    cv2.circle(template_image, (12, 12), 2, (255, 255, 255), thickness=-1)
    cv2.line(template_image, (3, 14), (14, 4), (120, 120, 120), thickness=1)
    source_image[20:38, 16:34] = template_image
    source_image[58:76, 74:92] = template_image

    source_success, source_encoded = cv2.imencode(".png", source_image)
    template_success, template_encoded = cv2.imencode(".png", template_image)
    assert source_success is True
    assert template_success is True
    return source_encoded.tobytes(), template_encoded.tobytes()
