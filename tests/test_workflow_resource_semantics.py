"""正式 Runtime 存储路径与内存 Preview 状态合约。"""
import pytest
from pydantic import TypeAdapter, ValidationError
from backend.contracts.workflows.resource_semantics import build_workflow_app_runtime_snapshot_object_key
from backend.contracts.workflows.preview_session import PreviewRunState


def test_workflow_app_runtime_snapshot_path():
    """正式运行快照的持久化位置保持不变。"""
    assert build_workflow_app_runtime_snapshot_object_key('runtime-1', 'template.snapshot.json') == 'workflows/runtime/app-runtimes/runtime-1/template.snapshot.json'


def test_preview_session_rejects_unknown_state():
    """预览状态只能来自当前 v1 协议。"""
    with pytest.raises(ValidationError):
        TypeAdapter(PreviewRunState).validate_python('queued')
