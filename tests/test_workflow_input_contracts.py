"""Workflow App Contract v1 与统一输入校验测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphTemplate,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import WorkflowInputError
from backend.service.application.workflows.input_contracts import (
    WORKFLOW_APP_CONTRACT_FORMAT,
    WorkflowInputValidator,
    build_workflow_app_public_contract,
    find_workflow_app_public_contract_issues,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_contract_closes_payload_and_freezes_request_limits() -> None:
    """新发布契约必须冻结闭合 schema、transport、限制和 charset。"""

    application, template = _build_text_file_application()
    contract = build_workflow_app_public_contract(
        application=application,
        template=template,
        node_catalog_registry=NodeCatalogRegistry(),
    )
    inputs = {item["binding_id"]: item for item in contract["inputs"]}

    assert contract["format_id"] == WORKFLOW_APP_CONTRACT_FORMAT
    assert inputs["request_text"]["payload_schema"]["additionalProperties"] is False
    assert inputs["request_text"]["transports"] == ["json"]
    assert inputs["request_text"]["charset"] == "utf-8"
    assert inputs["request_file"]["transports"] == [
        "json-reference",
        "multipart-upload",
    ]
    assert inputs["request_file"]["max_files"] == 1


def test_current_v1_contract_definition_rejects_loose_or_unknown_contracts() -> None:
    """正式 Runtime 只接受结构完整的当前 v1 公开契约。"""

    application, template = _build_text_file_application()
    contract = build_workflow_app_public_contract(
        application=application,
        template=template,
        node_catalog_registry=NodeCatalogRegistry(),
    )
    assert find_workflow_app_public_contract_issues(contract) == ()

    loose_contract = {
        **contract,
        "inputs": [
            {
                key: value
                for key, value in item.items()
                if key not in {"payload_schema", "transports"}
            }
            for item in contract["inputs"]
        ],
    }
    loose_issues = find_workflow_app_public_contract_issues(loose_contract)
    assert {issue["kind"] for issue in loose_issues} == {
        "payload_schema_missing",
        "transports_invalid",
    }

    unknown_format_issues = find_workflow_app_public_contract_issues(
        {**contract, "format_id": "unknown"}
    )
    assert unknown_format_issues[0]["kind"] == "format_invalid"


def test_validator_rejects_extra_fields_for_v1_contract() -> None:
    """v1 公开契约始终启用闭合 payload schema。"""

    application, template = _build_text_file_application()
    validator = WorkflowInputValidator()
    payload = {
        "request_text": {
            "text": "hello",
            "media_type": "text/plain",
            "charset": "utf-8",
            "hidden": True,
        },
        "request_file": _file_ref(object_key="projects/project-1/files/example.txt"),
    }
    contract = build_workflow_app_public_contract(
        application=application,
        template=template,
        node_catalog_registry=NodeCatalogRegistry(),
    )

    with pytest.raises(WorkflowInputError) as error_info:
        validator.validate(
            application=application,
            input_bindings=payload,
            public_contract=contract,
            project_id="project-1",
        )

    assert error_info.value.code == "workflow_input_payload_schema_invalid"
    assert error_info.value.details["binding_id"] == "request_text"


def test_validator_checks_file_identity_and_project_scope(tmp_path: Path) -> None:
    """file-ref 必须匹配当前 Project 的不可变 ObjectStore identity。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )
    receipt = storage.write_immutable_object(
        object_prefix="projects/project-1/workflow-inputs/request-1",
        content=b"hello",
        media_type="text/plain",
        extension=".txt",
    )
    metadata = receipt.metadata
    application, template = _build_text_file_application()
    contract = build_workflow_app_public_contract(
        application=application,
        template=template,
        node_catalog_registry=NodeCatalogRegistry(),
    )
    payload = {
        "request_text": {
            "text": "hello",
            "media_type": "text/plain",
            "charset": "utf-8",
        },
        "request_file": {
            "transport_kind": "storage",
            "storage_ref": "object-store",
            "object_key": metadata.object_key,
            "file_name": "example.txt",
            "media_type": metadata.media_type,
            "content_length": metadata.content_length,
            "checksum_algorithm": metadata.checksum_algorithm,
            "checksum": metadata.checksum,
            "immutable_version": metadata.immutable_version,
        },
    }

    WorkflowInputValidator(object_store=storage).validate(
        application=application,
        input_bindings=payload,
        public_contract=contract,
        project_id="project-1",
    )
    payload["request_file"] = {
        **payload["request_file"],
        "checksum": "0" * 64,
    }
    with pytest.raises(WorkflowInputError) as error_info:
        WorkflowInputValidator(object_store=storage).validate(
            application=application,
            input_bindings=payload,
            public_contract=contract,
            project_id="project-1",
        )
    assert error_info.value.code == "workflow_input_object_reference_invalid"


def test_validator_uses_stable_missing_and_unknown_binding_codes() -> None:
    """所有入口共享稳定的缺失和未知 binding 错误码。"""

    application, _template = _build_text_file_application()
    validator = WorkflowInputValidator()
    with pytest.raises(WorkflowInputError) as missing_error:
        validator.validate(application=application, input_bindings={})
    assert missing_error.value.code == "workflow_input_required_binding_missing"

    with pytest.raises(WorkflowInputError) as unknown_error:
        validator.validate(
            application=application,
            input_bindings={"unknown": {"value": 1}},
        )
    assert unknown_error.value.code == "workflow_input_unknown_binding"


def _build_text_file_application() -> tuple[FlowApplication, WorkflowGraphTemplate]:
    """构造只覆盖公开文本和文件输入的最小应用。"""

    template = WorkflowGraphTemplate(
        template_id="text-file-template",
        template_version="1.0.0",
        display_name="Text File Template",
        nodes=(
            WorkflowGraphNode(
                node_id="text_input", node_type_id="core.io.template-input.text"
            ),
            WorkflowGraphNode(
                node_id="file_input", node_type_id="core.io.template-input.file"
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="text_payload",
                display_name="Text",
                payload_type_id="text.v1",
                target_node_id="text_input",
                target_port="payload",
            ),
            WorkflowGraphInput(
                input_id="file_payload",
                display_name="File",
                payload_type_id="file-ref.v1",
                target_node_id="file_input",
                target_port="payload",
            ),
        ),
    )
    application = FlowApplication(
        application_id="text-file-app",
        display_name="Text File App",
        template_ref=FlowTemplateReference(
            template_id=template.template_id,
            template_version=template.template_version,
            source_uri="templates/text-file-template/1.0.0.json",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_text",
                direction="input",
                template_port_id="text_payload",
                binding_kind="api-request",
            ),
            FlowApplicationBinding(
                binding_id="request_file",
                direction="input",
                template_port_id="file_payload",
                binding_kind="api-request",
            ),
        ),
    )
    return application, template


def _file_ref(*, object_key: str) -> dict[str, object]:
    """构造测试 file-ref。"""

    return {
        "transport_kind": "storage",
        "storage_ref": "object-store",
        "object_key": object_key,
        "file_name": "example.txt",
        "media_type": "text/plain",
        "content_length": 5,
        "checksum_algorithm": "sha256",
        "checksum": "0" * 64,
        "immutable_version": f"sha256:{'0' * 64}",
    }
