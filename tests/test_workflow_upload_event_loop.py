"""multipart 接入等待 Runtime 时，HTTP 事件循环必须仍能服务其他请求。"""

import asyncio
from threading import Event
from types import SimpleNamespace

import pytest

from backend.service.api.rest.v1.routes.workflow_runtime import runs


@pytest.mark.parametrize("phase", ["lookup", "execute"])
@pytest.mark.parametrize("synchronous", [True, False])
def test_multipart_runtime_wait_keeps_event_loop_available(monkeypatch, phase, synchronous):
    """由同一事件循环解除模拟 IPC 等待；阻塞循环的实现必定超时失败。"""
    entered, release = Event(), Event()
    result = object()

    def blocking_step(current_phase):
        """模拟目录查询或 IPC 等待，只允许事件循环继续后返回。"""
        if phase == current_phase:
            entered.set()
            assert release.wait(2), "multipart 路由阻塞了 HTTP 事件循环"
        return result

    service = SimpleNamespace(
        get_visible_workflow_app_runtime=lambda *args, **kwargs: blocking_step("lookup"),
        invoke_workflow_app_runtime_with_response=lambda *args, **kwargs: blocking_step("execute"),
        create_workflow_run=lambda *args, **kwargs: blocking_step("execute"),
    )

    async def build_upload(**kwargs):
        """上传解析已完成，后续仍须等待本次真实调用结果。"""
        return result

    monkeypatch.setattr(runs, "_build_workflow_runtime_service", lambda request: service)
    monkeypatch.setattr(runs, "_build_multipart_runtime_invoke_request", build_upload)
    monkeypatch.setattr(runs, "_build_sync_invoke_response", lambda value, **kwargs: value)
    monkeypatch.setattr(runs, "_build_workflow_run_contract", lambda value: value)

    async def check():
        """在同一循环上调度并发请求，验证没有提前返回调用结果。"""
        route = runs.invoke_workflow_app_runtime_upload if synchronous else runs.create_workflow_run_upload
        kwargs = {"response_mode": "app-result"} if synchronous else {}
        task = asyncio.create_task(route("runtime", object(), SimpleNamespace(project_ids=["project-1"], principal_id="user"), **kwargs))
        try:
            async with asyncio.timeout(4):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
                assert not task.done()
                release.set()
                assert await task is result
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(check())
