"""workflow 资源共享语义测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.contracts.workflows.resource_semantics import (
    WORKFLOW_PREVIEW_RUN_STORAGE_ROOT,
    build_workflow_app_runtime_snapshot_object_key,
    build_workflow_preview_run_snapshot_object_key,
    build_workflow_preview_run_storage_dir,
)
from backend.contracts.workflows.runtime import WorkflowPreviewRunContract


def test_workflow_preview_run_storage_helpers_build_consistent_paths() -> None:
    """验证 preview/app runtime snapshot 路径 helper 使用统一目录规则。"""

    assert build_workflow_preview_run_storage_dir("preview-1") == f"{WORKFLOW_PREVIEW_RUN_STORAGE_ROOT}/preview-1"
    assert build_workflow_preview_run_snapshot_object_key(
        "preview-1",
        "application.snapshot.json",
    ) == "workflows/runtime/preview-runs/preview-1/application.snapshot.json"
    assert build_workflow_app_runtime_snapshot_object_key(
        "runtime-1",
        "template.snapshot.json",
    ) == "workflows/runtime/app-runtimes/runtime-1/template.snapshot.json"


def test_workflow_preview_run_contract_rejects_unknown_state() -> None:
    """验证 preview run 合同只接受共享语义中声明的状态值。"""

    with pytest.raises(ValidationError):
        WorkflowPreviewRunContract(
            preview_run_id="preview-1",
            project_id="project-1",
            application_id="app-1",
            source_kind="saved-application",
            application_snapshot_object_key="workflows/runtime/preview-runs/preview-1/application.snapshot.json",
            template_snapshot_object_key="workflows/runtime/preview-runs/preview-1/template.snapshot.json",
            state="queued",
            created_at="2026-05-14T10:00:00Z",
        )