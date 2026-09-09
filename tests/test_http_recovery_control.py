"""HTTP 两阶段控制、恢复预算和停止优先级回归。"""

import json
import time
import asyncio
from threading import Thread

import pytest

from backend.service.infrastructure.http.liveness import ServiceLiveness
from backend.service.infrastructure.http.recovery_control import HttpRecoveryControl
from runtimes.launchers.http_stack_recovery import RecoveryBlocked, RecoveryBudget, wait_until


def test_recovery_budget_is_bounded_and_does_not_reset_on_success():
    """三次恢复用尽窗口，完整窗口过去才恢复预算。"""
    budget = RecoveryBudget()
    assert [budget.reserve(t) for t in (0, 10, 20)] == [2, 5, 15]
    with pytest.raises(RecoveryBlocked):
        budget.reserve(599)
    assert budget.reserve(600) == 15


@pytest.mark.parametrize("fails", [False, True])
def test_control_requires_identity_drain_ack_and_no_failed_shutdown(tmp_path, fails):
    """错误实例、乱序关闭、排空失败均不能启动关闭步骤。"""
    calls = []
    live = ServiceLiveness()

    def drain():
        """模拟已有消费者的正常或失败排空。"""
        calls.append("drain")
        if fails:
            raise RuntimeError("view still held")

    control = HttpRecoveryControl(tmp_path, live, drain, lambda: calls.append("shutdown"))

    def request(action, identity=live.instance_id):
        """写入本次测试的绑定请求。"""
        control.request.write_text(json.dumps({"format_id": "amvision.http-recovery.v1",
            "instance_id": identity, "pid": live.pid, "action": action}))

    control.start()
    try:
        request("drain", "b" * 32)
        time.sleep(.25)
        assert not calls
        request("shutdown")
        time.sleep(.25)
        assert not calls
        request("drain")
        wait_until(lambda: control.phase in {"failed", "drained"}, lambda: None,
                   timeout=2, description="test drain timeout")
        assert live.phase == "draining"
        assert calls == ["drain"]
        if fails:
            assert json.loads(control.status.read_text())["error"] == "view still held"
        request("shutdown")
        if fails:
            time.sleep(.25)
            assert calls == ["drain"]
        else:
            wait_until(lambda: calls == ["drain", "shutdown"], lambda: None,
                       timeout=2, description="test shutdown timeout")
    finally:
        control.close()


def test_manual_stop_preempts_ready_condition():
    """即使已满足重启条件，人工停止仍优先。"""
    def stop():
        """模拟已有 Supervisor 停止请求。"""
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        wait_until(lambda: True, stop, timeout=1, description="unused")


def test_drain_waits_for_complete_http_stream_and_rejects_new_requests():
    """发送 header 后仍占用计数，直到最后一个 body 完成；新请求返回 503。"""
    from backend.service.infrastructure.http.drain_middleware import HttpDrainMiddleware
    live = ServiceLiveness(phase="ready")
    drained = []

    async def exercise():
        """用两个可控 ASGI body 分段固定流式响应竞态。"""
        first_body = asyncio.Event()
        finish = asyncio.Event()
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            first_body.set()
            await finish.wait()
            await send({"type": "http.response.body", "body": b"done"})
        async def send(message):
            responses.append(message)
        async def receive():
            return {"type": "http.disconnect"}
        responses = []
        middleware = HttpDrainMiddleware(app, live)
        scope = {"type": "http", "path": "/image"}
        running = asyncio.create_task(middleware(scope, receive, send))
        await first_body.wait()
        def drain():
            live.begin_drain(timeout=2)
            drained.append(True)
        thread = Thread(target=drain)
        thread.start()
        try:
            while live.phase != "draining":
                await asyncio.sleep(.001)
            assert live.active_requests == 1 and not drained
            await middleware(scope, receive, send)
            assert any(r.get("status") == 503 for r in responses)
            finish.set()
            await running
        finally:
            finish.set()
            await running
            thread.join(2)
        assert drained == [True] and live.active_requests == 0
    asyncio.run(exercise())


def test_broker_strict_stop_preserves_unfinished_owner():
    """Broker 未确认退出时不能 terminate、停止 router 或清理 owner 引用。"""
    from threading import Lock
    from types import SimpleNamespace
    from backend.service.application.errors import OperationTimeoutError
    from backend.service.application.local_buffers.local_buffer_broker_supervisor import LocalBufferBrokerProcessSupervisor
    calls = []
    process = SimpleNamespace(is_alive=lambda: True, exitcode=None,
        join=lambda **_: None, terminate=lambda: calls.append("terminate"))
    router = SimpleNamespace(stop=lambda: calls.append("router.stop"))
    client = SimpleNamespace(shutdown=lambda: None, close=lambda: calls.append("client.close"))
    owner = SimpleNamespace(_stop_expire_loop=lambda: None, _close_direct_io_client=lambda: None,
        _lock=Lock(), _process=process, _router=router, create_client=lambda: client,
        settings=SimpleNamespace(shutdown_timeout_seconds=.1))
    with pytest.raises(OperationTimeoutError):
        LocalBufferBrokerProcessSupervisor.stop(owner, graceful_only=True)
    assert calls == ["client.close"]
    assert owner._process is process and owner._router is router


def test_workflow_strict_stop_preserves_live_handle_after_ack():
    """stop-runtime 回复不等于进程退出；仍存活时不得清理句柄或强杀。"""
    from threading import Lock
    from types import SimpleNamespace
    from backend.service.application.errors import OperationTimeoutError
    from backend.service.application.workflows.worker.manager import WorkflowRuntimeWorkerManager
    calls = []
    handle = SimpleNamespace(process=SimpleNamespace(is_alive=lambda: True,
        join=lambda **_: None, exitcode=None), state_lock=Lock(), request_lock=Lock())
    manager = SimpleNamespace(_lock=Lock(), _handles={"runtime": handle},
        _wait_for_runtime_state=lambda *a, **k: "stopped",
        _cleanup_handle=lambda *_: calls.append("cleanup"),
        _remove_handle_if_current=lambda *_: calls.append("remove"))
    with pytest.raises(OperationTimeoutError):
        WorkflowRuntimeWorkerManager._stop_runtime(manager, "runtime", graceful_only=True)
    assert not calls and manager._handles["runtime"] is handle
