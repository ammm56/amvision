"""OpenCV 基础节点目录生成测试。"""

from __future__ import annotations

import json
from pathlib import Path

from custom_nodes.opencv_basic_nodes.workflow.catalog_builder import build_custom_node_catalog_payload


def test_opencv_basic_node_catalog_builder_matches_checked_in_catalog() -> None:
    """验证 catalog 碎片生成结果与仓库内 catalog.json 保持一致。"""

    repository_root = Path(__file__).resolve().parents[1]
    workflow_dir = repository_root / "custom_nodes" / "opencv_basic_nodes" / "workflow"
    expected_catalog_payload = json.loads((workflow_dir / "catalog.json").read_text(encoding="utf-8"))
    actual_catalog_payload = build_custom_node_catalog_payload(workflow_dir=workflow_dir)

    assert actual_catalog_payload == expected_catalog_payload
    _assert_source_image_schema_supports_local_buffer_refs(
        catalog_payload=actual_catalog_payload,
        payload_type_ids={"contours.v1", "measurements.v1"},
    )


def _assert_source_image_schema_supports_local_buffer_refs(
    *,
    catalog_payload: dict[str, object],
    payload_type_ids: set[str],
) -> None:
    """验证指定 payload 的 source_image schema 支持 LocalBufferBroker 引用。

    参数：
    - catalog_payload：custom node catalog JSON。
    - payload_type_ids：需要检查的 payload_type_id 集合。
    """

    payload_contracts = catalog_payload["payload_contracts"]
    assert isinstance(payload_contracts, list)
    contracts_by_type = {contract["payload_type_id"]: contract for contract in payload_contracts}
    for payload_type_id in payload_type_ids:
        contract_payload = contracts_by_type[payload_type_id]
        source_image_schema = contract_payload["json_schema"]["properties"]["source_image"]
        transport_enum = set(source_image_schema["properties"]["transport_kind"]["enum"])
        requirements_by_kind = {
            branch["properties"]["transport_kind"]["const"]: set(branch["required"])
            for branch in source_image_schema["oneOf"]
        }

        assert {"memory", "storage", "buffer", "frame"} <= transport_enum
        assert "buffer_ref" in source_image_schema["properties"]
        assert "frame_ref" in source_image_schema["properties"]
        assert requirements_by_kind["buffer"] == {"buffer_ref"}
        assert requirements_by_kind["frame"] == {"frame_ref"}