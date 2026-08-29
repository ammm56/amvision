"""core payload 规则 回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    WorkflowPayloadContract,
    validate_node_definition_catalog,
)
from backend.nodes.core_catalog import (
    get_core_workflow_node_definitions,
    get_core_workflow_payload_contracts,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_core_payload_contracts_include_image_base64_and_local_buffer_image_refs() -> (
    None
):
    """验证 core payload 规则s 已收敛到 base64 输入和 LocalBufferBroker 图片引用。"""

    payload_contracts = {
        item.payload_type_id: item for item in get_core_workflow_payload_contracts()
    }

    assert "image-base64.v1" in payload_contracts

    image_ref_contract = payload_contracts["image-ref.v1"]
    image_ref_schema = image_ref_contract.json_schema
    assert image_ref_contract.transport_kind == "hybrid"
    assert image_ref_schema["required"] == ["transport_kind", "media_type"]
    assert image_ref_schema["properties"]["transport_kind"]["enum"] == [
        "memory",
        "storage",
        "local-path",
        "buffer",
        "frame",
    ]
    assert "buffer_ref" in image_ref_schema["properties"]
    assert "frame_ref" in image_ref_schema["properties"]
    assert "local_path" in image_ref_schema["properties"]
    assert any(
        item.get("properties", {}).get("transport_kind", {}).get("const")
        == "local-path"
        and item.get("required") == ["local_path"]
        for item in image_ref_schema["oneOf"]
    )

    image_base64_contract = payload_contracts["image-base64.v1"]
    assert image_base64_contract.transport_kind == "inline-json"
    assert image_base64_contract.json_schema["required"] == ["image_base64"]

    image_refs_contract = payload_contracts["image-refs.v1"]
    item_schema = image_refs_contract.json_schema["properties"]["items"]["items"]
    assert item_schema["required"] == ["transport_kind", "media_type"]
    assert item_schema["properties"]["transport_kind"]["enum"] == [
        "memory",
        "storage",
        "local-path",
        "buffer",
        "frame",
    ]
    assert "source_image" in image_refs_contract.json_schema["properties"]

    roi_contract = payload_contracts["roi.v1"]
    assert roi_contract.transport_kind == "inline-json"
    assert roi_contract.json_schema["required"] == [
        "roi_id",
        "roi_kind",
        "bbox_xyxy",
        "polygon_xy",
        "area",
    ]

    result_record_contract = payload_contracts["result-record.v1"]
    assert result_record_contract.transport_kind == "inline-json"
    assert result_record_contract.json_schema["required"] == ["ok_ng", "ok"]

    alarm_record_contract = payload_contracts["alarm-record.v1"]
    assert alarm_record_contract.transport_kind == "inline-json"
    assert alarm_record_contract.json_schema["required"] == [
        "active",
        "level",
        "message",
    ]

    workflow_result_contract = payload_contracts["workflow-result.v1"]
    assert workflow_result_contract.transport_kind == "inline-json"
    assert workflow_result_contract.json_schema["required"] == [
        "status",
        "code",
        "message",
    ]

    segments_contract = payload_contracts["segments.v1"]
    assert segments_contract.transport_kind == "inline-json"
    assert segments_contract.json_schema["required"] == ["items"]


def test_core_catalog_cold_start_includes_circles_contract() -> None:
    """验证不依赖 OpenCV 自定义包的核心目录可在冷启动时独立通过引用校验。"""

    payload_contracts = get_core_workflow_payload_contracts()
    payload_contract_index = {
        item.payload_type_id: item for item in payload_contracts
    }

    assert "circles.v1" in payload_contract_index
    validate_node_definition_catalog(
        node_definitions=get_core_workflow_node_definitions(),
        payload_contracts=payload_contracts,
    )


def test_core_circles_contract_matches_opencv_shared_contract() -> None:
    """验证核心与 OpenCV 包共用唯一 circles.v1 格式，合并时不会产生冲突。"""

    shared_contract_path = (
        REPOSITORY_ROOT
        / "custom_nodes"
        / "opencv_nodes"
        / "shared"
        / "workflow"
        / "payload_contracts.json"
    )
    shared_contract_payloads = json.loads(
        shared_contract_path.read_text(encoding="utf-8")
    )
    shared_contract = WorkflowPayloadContract.model_validate(
        next(
            item
            for item in shared_contract_payloads
            if item["payload_type_id"] == "circles.v1"
        )
    )
    core_contract = next(
        item
        for item in get_core_workflow_payload_contracts()
        if item.payload_type_id == "circles.v1"
    )

    assert core_contract == shared_contract
