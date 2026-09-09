"""Preview 长执行期间 HTTP loop 可响应，取消不得提前回收输入。"""

import asyncio
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.datastructures import FormData, UploadFile

from backend.service.api.rest.v1.routes.workflow_runtime import preview_runs as routes


@pytest.mark.parametrize("cancel", [False, True])
def test_multipart_keeps_loop_responsive_and_owns_upload_until_finished(monkeypatch, cancel):
    """由测试释放长执行；期间 loop 可处理事件，反复取消也不能关闭被使用的文件。"""

    started, release = Event(), Event()
    upload = UploadFile(filename="sample.txt", file=BytesIO(b"sample"))
    form = FormData([("request", '{"project_id":"project-1"}'), ("input", upload)])
    storage = SimpleNamespace(delete_tree=Mock(), resolve_filesystem_path=Mock(
        return_value=SimpleNamespace(stat=Mock(side_effect=FileNotFoundError))))
    contract = {"inputs": [{"binding_id": "input", "payload_type_id": "file-ref.v1"}]}
    monkeypatch.setattr(routes, "_require_dataset_storage", Mock(return_value=storage))
    monkeypatch.setattr(routes, "_build_workflow_runtime_service", Mock(return_value=SimpleNamespace(
        resolve_preview_input_contract=Mock(return_value=(None, contract)))))
    monkeypatch.setattr(routes, "publish_workflow_upload", AsyncMock(return_value={"object_key": "sample"}))
    monkeypatch.setattr(routes, "WorkflowInputValidator", Mock())
    monkeypatch.setattr(routes, "_build_preview_run_contract", lambda result: result)

    def execute(**kwargs):
        """模拟持有上传内容的阻塞节点，不依赖实际模型速度。"""
        started.set()
        if not release.wait(5):
            raise TimeoutError("HTTP loop 未能在执行期间响应")
        assert not upload.file.closed
        return {"state": "succeeded"}

    monkeypatch.setattr(routes, "_create_preview_run", execute)

    async def verify():
        """以独立事件验证响应性，不对节点执行时长设置性能假设。"""
        task = asyncio.create_task(routes.create_workflow_preview_run_multipart(
            SimpleNamespace(form=AsyncMock(return_value=form)), SimpleNamespace()))
        try:
            assert await asyncio.to_thread(started.wait, 3)
            if cancel:
                task.cancel()
                await asyncio.sleep(.02)
                task.cancel()
            await asyncio.sleep(.02)
            assert not task.done()
            assert not upload.file.closed
            storage.delete_tree.assert_not_called()
        finally:
            release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task == {"state": "succeeded"}
        assert upload.file.closed
        storage.delete_tree.assert_called_once()

    asyncio.run(verify())
