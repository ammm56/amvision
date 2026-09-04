"""Preview 上传资源的所有权、失败释放和异常优先级测试。"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.datastructures import FormData, UploadFile

from backend.service.api.rest.v1.routes.workflow_runtime import preview_runs
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


@pytest.mark.parametrize("failure", [None, "delete", "release", "client", "form"])
@pytest.mark.parametrize("execution_failed", [False, True])
def test_cleanup_attempts_every_resource_and_preserves_execution_error(
    failure: str | None, execution_failed: bool,
) -> None:
    """任一清理失败也要尝试后续释放，已有执行错误优先保留。"""

    cleanup_error = OSError("cleanup failure")
    storage = SimpleNamespace(
        delete_tree=Mock(),
        resolve_filesystem_path=Mock(return_value=SimpleNamespace(stat=Mock(side_effect=FileNotFoundError))),
    )
    client = SimpleNamespace(release=Mock(), close=Mock())
    uploaded = UploadFile(filename="sample.txt", file=BytesIO(b"sample"))
    uploaded.close = AsyncMock()
    form = FormData([("request_file", uploaded)])
    actions = {
        "delete": storage.delete_tree, "release": client.release,
        "client": client.close, "form": uploaded.close,
    }
    if failure:
        actions[failure].side_effect = cleanup_error

    async def execute() -> None:
        """模拟路由 try/finally 中的真实异常传播。"""
        try:
            if execution_failed:
                raise ValueError("original execution failure")
        finally:
            await preview_runs._cleanup_preview_uploads(
                dataset_storage=storage, upload_root="test-owned-upload",
                lease_ids=["first", "second"], client=client, form=form,
                execution_failed=execution_failed,
            )

    if execution_failed:
        with pytest.raises(ValueError, match="original execution failure"):
            asyncio.run(execute())
    elif failure:
        with pytest.raises(OSError, match="cleanup failure"):
            asyncio.run(execute())
    else:
        asyncio.run(execute())
    storage.delete_tree.assert_called_once_with("test-owned-upload")
    assert client.release.call_args_list == [(('first',),), (('second',),)]
    client.close.assert_called_once_with()
    uploaded.close.assert_awaited_once_with()
    uploaded.file.close()


def test_multipart_closes_form_if_service_dependencies_are_missing(monkeypatch) -> None:
    """表单解析成功后装配失败，已打开上传文件仍由路由关闭。"""

    uploaded = UploadFile(filename="sample.txt", file=BytesIO(b"sample"))
    form = FormData([("request_file", uploaded)])
    request = SimpleNamespace(form=AsyncMock(return_value=form))
    monkeypatch.setattr(
        preview_runs, "_require_dataset_storage", Mock(side_effect=RuntimeError("missing storage")),
    )
    with pytest.raises(RuntimeError, match="missing storage"):
        asyncio.run(preview_runs.create_workflow_preview_run_multipart(request, SimpleNamespace()))
    assert uploaded.file.closed


def test_cleanup_does_not_need_broker_for_file_only_inputs() -> None:
    """普通文件上传只清理本地输入与表单，不要求 Broker。"""

    uploaded = UploadFile(filename="sample.txt", file=BytesIO(b"sample"))
    asyncio.run(preview_runs._cleanup_preview_uploads(
        dataset_storage=None, upload_root="", lease_ids=[], client=None,
        form=FormData([("request_file", uploaded)]), execution_failed=False,
    ))
    assert uploaded.file.closed


def test_one_upload_close_failure_does_not_skip_other_files() -> None:
    """第一个上传文件关闭失败时，后面的上传文件也必须尝试关闭。"""

    first = UploadFile(filename="first.txt", file=BytesIO(b"first"))
    second = UploadFile(filename="second.txt", file=BytesIO(b"second"))
    first.close = AsyncMock(side_effect=OSError("first file close failed"))
    try:
        with pytest.raises(OSError, match="first file close failed"):
            asyncio.run(preview_runs._cleanup_preview_uploads(
                dataset_storage=None, upload_root="", lease_ids=[], client=None,
                form=FormData([("request_files", first), ("request_files", second)]),
                execution_failed=False,
            ))
        assert second.file.closed
    finally:
        first.file.close()


def test_multipart_cleans_partial_first_upload_before_publication(tmp_path: Path, monkeypatch) -> None:
    """首个文件超限时 published_any 尚未置位，也必须清理已创建的目录。"""

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    uploaded = UploadFile(filename="sample.json", file=BytesIO(b"too large"))
    request = SimpleNamespace(form=AsyncMock(return_value=FormData([
        ("request", '{"project_id":"project-1"}'), ("request_file", uploaded),
    ])))
    contract = {"inputs": [{"binding_id": "request_file", "payload_type_id": "file-ref.v1", "max_file_bytes": 1}]}
    monkeypatch.setattr(preview_runs, "_require_dataset_storage", lambda request: storage)
    monkeypatch.setattr(preview_runs, "_build_preview_run_create_request", Mock())
    monkeypatch.setattr(preview_runs, "_build_workflow_runtime_service", lambda request: SimpleNamespace(
        resolve_preview_input_contract=Mock(return_value=(None, contract)),
    ))
    monkeypatch.setattr(preview_runs, "uuid4", lambda: SimpleNamespace(hex="test-owned-upload"))
    with pytest.raises(preview_runs.WorkflowInputError, match="超过"):
        asyncio.run(preview_runs.create_workflow_preview_run_multipart(request, SimpleNamespace()))
    assert not storage.resolve_filesystem_path("workflows/runtime-inputs/project-1/preview/test-owned-upload").exists()
    assert uploaded.file.closed


def test_remaining_upload_directory_reports_failure_and_closes_form(tmp_path: Path) -> None:
    """删除接口吞掉错误时，通过实际目录后置检查暴露失败，仍继续关闭文件。"""

    upload_root = tmp_path / "test-owned-upload"
    upload_root.mkdir()
    storage = SimpleNamespace(delete_tree=Mock(), resolve_filesystem_path=lambda path: upload_root)
    uploaded = UploadFile(filename="sample.txt", file=BytesIO(b"sample"))
    with pytest.raises(OSError, match="未完全删除"):
        asyncio.run(preview_runs._cleanup_preview_uploads(
            dataset_storage=storage, upload_root="test-owned-upload", lease_ids=[], client=None,
            form=FormData([("request_file", uploaded)]), execution_failed=False,
        ))
    assert uploaded.file.closed
