"""Barcode/QR 协议节点 workflow 执行测试。"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

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
from backend.service.application.workflows.runtime_registry_loader import WorkflowNodeRuntimeRegistryLoader
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from custom_nodes.barcode_protocol_nodes.backend.nodes import NODE_DEFINITION_PAYLOADS
from custom_nodes.barcode_protocol_nodes.specs import DRAW_BARCODE_RESULTS_NODE_TYPE_ID


@pytest.mark.parametrize(
    (
        "node_type_id",
        "barcode_format_name",
        "expected_format_text",
        "payload_text",
        "expected_text",
        "expected_reported_format",
    ),
    (
        (
            "custom.barcode.qr-code-decode",
            "QRCode",
            "QR Code",
            "qr-node-sample",
            "qr-node-sample",
            "QR Code",
        ),
        (
            "custom.barcode.datamatrix-decode",
            "DataMatrix",
            "Data Matrix ECC200",
            "datamatrix-node-sample",
            "datamatrix-node-sample",
            "Data Matrix",
        ),
        (
            "custom.barcode.code128-decode",
            "Code128",
            "Code 128",
            "code128-node-sample",
            "code128-node-sample",
            "Code 128",
        ),
        (
            "custom.barcode.ean13-decode",
            "EAN13",
            "EAN-13",
            "5901234123457",
            "5901234123457",
            "EAN-13",
        ),
        (
            "custom.barcode.databar-expanded-decode",
            "DataBarExpanded",
            "DataBar Expanded",
            "(01)09501101530003(17)240101(10)ABC123",
            "(01)09501101530003(17)240101(10)ABC123",
            "DataBar Expanded",
        ),
        (
            "custom.barcode.code39-standard-decode",
            "Code39Std",
            "Code 39 Standard",
            "CODE39STD",
            "CODE39STD",
            "Code 39",
        ),
        (
            "custom.barcode.itf14-decode",
            "ITF14",
            "ITF-14",
            "10012345000017",
            "10012345000017",
            "ITF",
        ),
        (
            "custom.barcode.pdf417-decode",
            "PDF417",
            "PDF417",
            "PDF417-sample",
            "PDF417-sample",
            "PDF417",
        ),
        (
            "custom.barcode.micro-qr-code-decode",
            "MicroQRCode",
            "Micro QR Code",
            "MQR",
            "MQR",
            "Micro QR Code",
        ),
        (
            "custom.barcode.aztec-rune-decode",
            "AztecRune",
            "Aztec Rune",
            "123",
            "123",
            "Aztec",
        ),
    ),
)
def test_repository_barcode_protocol_nodes_decode_expected_symbol(
    tmp_path: Path,
    node_type_id: str,
    barcode_format_name: str,
    expected_format_text: str,
    payload_text: str,
    expected_text: str,
    expected_reported_format: str,
) -> None:
    """验证仓库内置 Barcode/QR 节点包可以解码代表性制式。"""

    node_pack_loader = LocalNodePackLoader(_get_repository_custom_nodes_root())
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes(
        f"inputs/{barcode_format_name}.png",
        _build_barcode_test_png_bytes(payload_text=payload_text, barcode_format_name=barcode_format_name),
    )

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id=f"{barcode_format_name}-decode-pipeline",
        template_version="1.0.0",
        display_name=f"{expected_format_text} Decode Pipeline",
        nodes=(
            WorkflowGraphNode(
                node_id="decode",
                node_type_id=node_type_id,
                parameters={"is_pure": True},
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="decode",
                target_port="image",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="barcode_results",
                display_name="Barcode Results",
                payload_type_id="barcode-results.v1",
                source_node_id="decode",
                source_port="results",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": f"inputs/{barcode_format_name}.png",
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": f"barcode-{barcode_format_name.lower()}",
        },
    )

    results = execution_result.outputs["barcode_results"]
    assert results["requested_format"] == expected_format_text
    assert results["count"] == 1
    assert results["matched_formats"] == [expected_reported_format]
    assert results["source_image"]["transport_kind"] == "storage"
    assert results["source_object_key"] == f"inputs/{barcode_format_name}.png"
    assert results["items"][0]["format"] == expected_reported_format
    assert results["items"][0]["text"] == expected_text
    assert results["items"][0]["valid"] is True
    assert "bbox_xyxy" not in results["items"][0]
    assert "polygon" not in results["items"][0]
    assert len(results["items"][0]["position"]["polygon_xy"]) == 4
    assert len(results["items"][0]["position"]["bounds_xyxy"]) == 4
    assert len(results["items"][0]["position"]["center_xy"]) == 2
    assert any(record.node_type_id == node_type_id for record in execution_result.node_records)


def test_repository_barcode_all_readable_node_returns_multiple_items_with_position_reference(tmp_path: Path) -> None:
    """验证混合条码图片会返回多个结果项，并输出独立位置参考结构。"""

    node_pack_loader = LocalNodePackLoader(_get_repository_custom_nodes_root())
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes(
        "inputs/mixed-readable.png",
        _build_mixed_barcode_test_png_bytes(),
    )

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="all-readable-decode-pipeline",
        template_version="1.0.0",
        display_name="All Readable Decode Pipeline",
        nodes=(
            WorkflowGraphNode(
                node_id="decode",
                node_type_id="custom.barcode.all-readable-decode",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="decode",
                target_port="image",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="barcode_results",
                display_name="Barcode Results",
                payload_type_id="barcode-results.v1",
                source_node_id="decode",
                source_port="results",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/mixed-readable.png",
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "barcode-all-readable",
        },
    )

    results = execution_result.outputs["barcode_results"]
    assert results["requested_format"] == "All Readable"
    assert results["count"] == 2
    assert set(results["matched_formats"]) == {"QR Code", "Code 128"}

    item_texts = {item["text"] for item in results["items"]}
    assert item_texts == {"qr-multi", "code128-multi"}
    for item in results["items"]:
        assert "bbox_xyxy" not in item
        assert "polygon" not in item
        assert len(item["position"]["polygon_xy"]) == 4
        assert len(item["position"]["bounds_xyxy"]) == 4

    bounds = [tuple(item["position"]["bounds_xyxy"]) for item in results["items"]]
    assert len(set(bounds)) == 2


def test_repository_barcode_protocol_node_pack_is_enabled_by_default() -> None:
    """验证仓库内置 barcode.protocol-nodes 会被默认加载。"""

    node_pack_loader = LocalNodePackLoader(_get_repository_custom_nodes_root())
    node_pack_loader.refresh()

    node_pack_ids = {manifest.node_pack_id for manifest in node_pack_loader.get_node_pack_manifests()}
    loaded_node_type_ids = {node.node_type_id for node in node_pack_loader.get_workflow_node_definitions()}

    assert "barcode.protocol-nodes" in node_pack_ids
    assert {
        "custom.barcode.all-readable-decode",
        "custom.barcode.ean13-decode",
        "custom.barcode.databar-expanded-decode",
        "custom.barcode.aztec-rune-decode",
        "custom.barcode.micro-qr-code-decode",
        "custom.barcode.qr-code-decode",
        "custom.barcode.datamatrix-decode",
        "custom.barcode.code128-decode",
        "custom.barcode.filter-results",
        "custom.barcode.match-exists",
        "custom.barcode.results-summary",
        DRAW_BARCODE_RESULTS_NODE_TYPE_ID,
    }.issubset(loaded_node_type_ids)


def test_barcode_node_modules_are_aggregated_bottom_up() -> None:
    """验证 barcode node definitions 会从显式节点模块向上汇总。"""

    nodes_dir = Path(__file__).resolve().parents[1] / "custom_nodes" / "barcode_protocol_nodes" / "backend" / "nodes"
    node_definition_module_names = {
        file_path.stem
        for file_path in nodes_dir.glob("*.py")
        if file_path.is_file() and file_path.stem != "__init__" and not file_path.stem.startswith("_")
    }
    aggregated_node_type_ids = {
        payload["node_type_id"]
        for payload in NODE_DEFINITION_PAYLOADS
        if isinstance(payload.get("node_type_id"), str)
    }

    assert len(NODE_DEFINITION_PAYLOADS) == len(node_definition_module_names)
    assert {
        "custom.barcode.qr-code-decode",
        "custom.barcode.filter-results",
        "custom.barcode.match-exists",
        "custom.barcode.results-summary",
        DRAW_BARCODE_RESULTS_NODE_TYPE_ID,
    }.issubset(aggregated_node_type_ids)


def test_repository_barcode_filter_results_node_filters_by_format_text_index_and_region(tmp_path: Path) -> None:
    """验证 filter-results 节点可以按 format、text、index 和区域范围筛选结果。"""

    executor = _create_barcode_executor()
    template = WorkflowGraphTemplate(
        template_id="barcode-filter-results-pipeline",
        template_version="1.0.0",
        display_name="Barcode Filter Results Pipeline",
        nodes=(
            WorkflowGraphNode(
                node_id="filter",
                node_type_id="custom.barcode.filter-results",
                parameters={
                    "formats": ["Code 128"],
                    "text_contains": "box",
                    "indices": [2],
                    "region_bounds_xyxy": [100, 0, 280, 120],
                    "region_match_mode": "center-in",
                },
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="barcode_results",
                display_name="Barcode Results",
                payload_type_id="barcode-results.v1",
                target_node_id="filter",
                target_port="results",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="filtered_results",
                display_name="Filtered Results",
                payload_type_id="barcode-results.v1",
                source_node_id="filter",
                source_port="results",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={"barcode_results": _build_barcode_results_fixture()},
        execution_metadata={
            "dataset_storage": _create_dataset_storage(tmp_path),
            "workflow_run_id": "barcode-filter-results",
        },
    )

    filtered_results = execution_result.outputs["filtered_results"]
    assert filtered_results["count"] == 1
    assert filtered_results["matched_formats"] == ["Code 128"]
    assert filtered_results["items"][0]["index"] == 2
    assert filtered_results["items"][0]["text"] == "box-42"


def test_repository_barcode_match_exists_node_returns_boolean_and_count(tmp_path: Path) -> None:
    """验证 match-exists 节点会输出匹配布尔值和数量。"""

    executor = _create_barcode_executor()
    template = WorkflowGraphTemplate(
        template_id="barcode-match-exists-pipeline",
        template_version="1.0.0",
        display_name="Barcode Match Exists Pipeline",
        nodes=(
            WorkflowGraphNode(
                node_id="judge",
                node_type_id="custom.barcode.match-exists",
                parameters={
                    "formats": ["EAN-13"],
                    "text_contains": "5901234",
                },
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="barcode_results",
                display_name="Barcode Results",
                payload_type_id="barcode-results.v1",
                target_node_id="judge",
                target_port="results",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="judge_result",
                display_name="Judge Result",
                payload_type_id="boolean.v1",
                source_node_id="judge",
                source_port="result",
            ),
            WorkflowGraphOutput(
                output_id="judge_count",
                display_name="Judge Count",
                payload_type_id="value.v1",
                source_node_id="judge",
                source_port="count",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={"barcode_results": _build_barcode_results_fixture()},
        execution_metadata={
            "dataset_storage": _create_dataset_storage(tmp_path),
            "workflow_run_id": "barcode-match-exists",
        },
    )

    assert execution_result.outputs["judge_result"] == {"value": True}
    assert execution_result.outputs["judge_count"] == {"value": 1}


def test_repository_barcode_results_summary_node_outputs_lightweight_summary(tmp_path: Path) -> None:
    """验证 results-summary 节点会输出便于条件分支使用的轻量摘要。"""

    executor = _create_barcode_executor()
    template = WorkflowGraphTemplate(
        template_id="barcode-results-summary-pipeline",
        template_version="1.0.0",
        display_name="Barcode Results Summary Pipeline",
        nodes=(
            WorkflowGraphNode(
                node_id="summary",
                node_type_id="custom.barcode.results-summary",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="barcode_results",
                display_name="Barcode Results",
                payload_type_id="barcode-results.v1",
                target_node_id="summary",
                target_port="results",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="summary_body",
                display_name="Summary Body",
                payload_type_id="response-body.v1",
                source_node_id="summary",
                source_port="body",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={"barcode_results": _build_barcode_results_fixture()},
        execution_metadata={
            "dataset_storage": _create_dataset_storage(tmp_path),
            "workflow_run_id": "barcode-results-summary",
        },
    )

    summary_body = execution_result.outputs["summary_body"]
    assert summary_body["type"] == "barcode-results-summary.v1"
    assert summary_body["count"] == 3
    assert summary_body["has_items"] is True
    assert summary_body["first_text"] == "station-A"
    assert summary_body["first_format"] == "QR Code"
    assert summary_body["format_counts"]["Code 128"] == 1


def test_repository_barcode_draw_results_node_renders_position_overlay(tmp_path: Path) -> None:
    """验证 barcode draw 节点会消费 position 信息并输出新的图片引用。"""

    node_pack_loader = LocalNodePackLoader(_get_repository_custom_nodes_root())
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    source_image_bytes = _build_mixed_barcode_test_png_bytes()
    dataset_storage.write_bytes("inputs/mixed-readable.png", source_image_bytes)

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="barcode-draw-results-pipeline",
        template_version="1.0.0",
        display_name="Barcode Draw Results Pipeline",
        nodes=(
            WorkflowGraphNode(node_id="decode", node_type_id="custom.barcode.all-readable-decode"),
            WorkflowGraphNode(
                node_id="draw",
                node_type_id=DRAW_BARCODE_RESULTS_NODE_TYPE_ID,
                parameters={"draw_format": True, "draw_text": True, "draw_index": True},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-decode-draw-results",
                source_node_id="decode",
                source_port="results",
                target_node_id="draw",
                target_port="results",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="draw",
                target_port="image",
            ),
            WorkflowGraphInput(
                input_id="decode_image",
                display_name="Decode Image",
                payload_type_id="image-ref.v1",
                target_node_id="decode",
                target_port="image",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="drawn_image",
                display_name="Drawn Image",
                payload_type_id="image-ref.v1",
                source_node_id="draw",
                source_port="image",
            ),
        ),
    )

    execution_metadata = {
        "dataset_storage": dataset_storage,
        "workflow_run_id": "barcode-draw-results",
        "execution_image_registry": ExecutionImageRegistry(),
    }
    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/mixed-readable.png",
                "media_type": "image/png",
            },
            "decode_image": {
                "object_key": "inputs/mixed-readable.png",
                "media_type": "image/png",
            },
        },
        execution_metadata=execution_metadata,
    )

    output_payload = execution_result.outputs["drawn_image"]
    assert output_payload["transport_kind"] == "memory"
    assert output_payload["media_type"] == "image/png"
    output_image_bytes = execution_metadata["execution_image_registry"].read_bytes(str(output_payload["image_handle"]))
    assert output_image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert output_image_bytes != source_image_bytes
    assert any(record.node_type_id == DRAW_BARCODE_RESULTS_NODE_TYPE_ID for record in execution_result.node_records)


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建 workflow 运行时测试使用的本地文件存储。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files")))


def _create_barcode_executor() -> WorkflowGraphExecutor:
    """创建加载仓库 barcode node pack 的 workflow 执行器。"""

    node_pack_loader = LocalNodePackLoader(_get_repository_custom_nodes_root())
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()
    return WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())


def _get_repository_custom_nodes_root() -> Path:
    """返回仓库内置 custom_nodes 根目录。"""

    return Path(__file__).resolve().parents[1] / "custom_nodes"


def _build_barcode_results_fixture() -> dict[str, object]:
    """构造多条码结果过滤与摘要测试用的 barcode-results payload。"""

    return {
        "requested_format": "All Readable",
        "source_image": {
            "object_key": "inputs/barcode-results-fixture.png",
            "media_type": "image/png",
            "transport_kind": "storage",
        },
        "source_object_key": "inputs/barcode-results-fixture.png",
        "count": 3,
        "matched_formats": ["QR Code", "Code 128", "EAN-13"],
        "items": [
            _build_barcode_result_item(
                index=1,
                item_format="QR Code",
                text="station-A",
                bounds_xyxy=[12, 16, 72, 76],
            ),
            _build_barcode_result_item(
                index=2,
                item_format="Code 128",
                text="box-42",
                bounds_xyxy=[120, 24, 260, 88],
            ),
            _build_barcode_result_item(
                index=3,
                item_format="EAN-13",
                text="5901234123457",
                bounds_xyxy=[300, 30, 430, 92],
            ),
        ],
    }


def _build_barcode_result_item(
    *,
    index: int,
    item_format: str,
    text: str,
    bounds_xyxy: list[int],
) -> dict[str, object]:
    """构造单个条码结果项测试数据。"""

    x1, y1, x2, y2 = bounds_xyxy
    polygon_xy = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    return {
        "index": index,
        "format": item_format,
        "symbology": item_format,
        "text": text,
        "raw_bytes_base64": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "content_type": "Text",
        "orientation": 0,
        "valid": True,
        "position": {
            "top_left_xy": polygon_xy[0],
            "top_right_xy": polygon_xy[1],
            "bottom_right_xy": polygon_xy[2],
            "bottom_left_xy": polygon_xy[3],
            "polygon_xy": polygon_xy,
            "bounds_xyxy": bounds_xyxy,
            "center_xy": [(x1 + x2) / 2.0, (y1 + y2) / 2.0],
            "size_wh": [x2 - x1, y2 - y1],
        },
    }


def _build_barcode_test_png_bytes(*, payload_text: str, barcode_format_name: str) -> bytes:
    """生成条码测试 PNG 图片字节。

    参数：
    - payload_text：条码中写入的文本。
    - barcode_format_name：zxingcpp.BarcodeFormat 的成员名称。

    返回：
    - bytes：编码后的 PNG 图片字节。
    """

    import cv2
    import numpy as np
    import zxingcpp

    barcode_format = getattr(zxingcpp.BarcodeFormat, barcode_format_name)
    barcode = zxingcpp.create_barcode(payload_text, barcode_format)
    image = np.asarray(barcode.to_image(scale=8))
    success, encoded_image = cv2.imencode(".png", image)
    assert success is True
    return encoded_image.tobytes()


def _build_mixed_barcode_test_png_bytes() -> bytes:
    """生成包含两个不同条码的混合 PNG 图片字节。"""

    import cv2
    import numpy as np
    import zxingcpp

    qr_image = np.asarray(zxingcpp.create_barcode("qr-multi", zxingcpp.BarcodeFormat.QRCode).to_image(scale=6))
    code128_image = np.asarray(
        zxingcpp.create_barcode("code128-multi", zxingcpp.BarcodeFormat.Code128).to_image(scale=3)
    )

    padding = 24
    canvas_height = max(qr_image.shape[0], code128_image.shape[0]) + padding * 2
    canvas_width = qr_image.shape[1] + code128_image.shape[1] + padding * 3
    canvas = np.full((canvas_height, canvas_width), 255, dtype=np.uint8)
    canvas[padding : padding + qr_image.shape[0], padding : padding + qr_image.shape[1]] = qr_image
    right_start_x = padding * 2 + qr_image.shape[1]
    canvas[
        padding : padding + code128_image.shape[0],
        right_start_x : right_start_x + code128_image.shape[1],
    ] = code128_image

    success, encoded_image = cv2.imencode(".png", canvas)
    assert success is True
    return encoded_image.tobytes()