"""Workflow Trigger 公开输入能力边界测试。"""

from __future__ import annotations

import pytest

from backend.contracts.workflows import (
    HIGH_PERFORMANCE_TRIGGER_INPUT_PAYLOAD_TYPE_IDS,
    workflow_trigger_supports_input_payload_type,
)
from backend.service.application.workflows.trigger_sources.trigger_source_service import (
    _find_trigger_contract_mapping_issues,
)


@pytest.mark.parametrize("trigger_kind", ["zeromq-topic", "local-shared-memory"])
def test_high_performance_trigger_accepts_only_reference_json_and_text(
    trigger_kind: str,
) -> None:
    """验证高性能 Trigger 的三类稳定输入均可映射。"""

    contract = _build_contract(
        request_image_ref="image-ref.v1",
        request_json="value.v1",
        request_text="text.v1",
    )
    mapping = {
        binding_id: {"source": f"payload.{binding_id}"}
        for binding_id in (
            "request_image_ref",
            "request_json",
            "request_text",
        )
    }

    assert _find_trigger_contract_mapping_issues(
        contract=contract,
        trigger_kind=trigger_kind,
        input_binding_mapping=mapping,
        result_mapping={},
        result_mode="event-only",
    ) == []


@pytest.mark.parametrize("trigger_kind", ["zeromq-topic", "local-shared-memory"])
@pytest.mark.parametrize(
    ("binding_id", "payload_type_id"),
    [
        ("request_image_base64", "image-base64.v1"),
        ("request_file", "file-ref.v1"),
        ("request_files", "file-refs.v1"),
    ],
)
def test_high_performance_trigger_rejects_http_only_inputs_from_contract(
    trigger_kind: str,
    binding_id: str,
    payload_type_id: str,
) -> None:
    """验证省略映射类型提示也不能绕过 App Contract 能力边界。"""

    assert _find_trigger_contract_mapping_issues(
        contract=_build_contract(**{binding_id: payload_type_id}),
        trigger_kind=trigger_kind,
        input_binding_mapping={binding_id: {"source": f"payload.{binding_id}"}},
        result_mapping={},
        result_mode="event-only",
    ) == [
        {
            "kind": "unsupported_trigger_input_payload_type",
            "binding_id": binding_id,
            "trigger_kind": trigger_kind,
            "payload_type_id": payload_type_id,
            "supported_payload_type_ids": sorted(
                HIGH_PERFORMANCE_TRIGGER_INPUT_PAYLOAD_TYPE_IDS
            ),
        }
    ]


def test_http_trigger_keeps_protocol_adapter_input_capability() -> None:
    """验证普通协议 Trigger 不被高性能链路边界误伤。"""

    contract = _build_contract(
        request_image_base64="image-base64.v1",
        request_file="file-ref.v1",
        request_files="file-refs.v1",
    )
    mapping = {
        binding_id: {"source": f"payload.{binding_id}"}
        for binding_id in (
            "request_image_base64",
            "request_file",
            "request_files",
        )
    }

    assert _find_trigger_contract_mapping_issues(
        contract=contract,
        trigger_kind="http-api",
        input_binding_mapping=mapping,
        result_mapping={},
        result_mode="event-only",
    ) == []
    assert workflow_trigger_supports_input_payload_type(
        "http-api",
        "file-ref.v1",
    )


def _build_contract(**payload_types: str) -> dict[str, object]:
    """构造只包含本测试所需字段的公开契约。"""

    return {
        "inputs": [
            {
                "binding_id": binding_id,
                "payload_type_id": payload_type_id,
                "required": False,
            }
            for binding_id, payload_type_id in payload_types.items()
        ],
        "outputs": [],
    }
