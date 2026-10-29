"""验证内存通道故障后的 Worker 退出及容量回收，不复用迟到回复。"""

from time import monotonic, sleep
from uuid import uuid4

from backend.service.application.workflows.preview.pool import PreviewSessionPool
from backend.service.application.workflows.preview.session import PreviewSessionManager
from backend.service.settings import BackendServiceSettings
from tests.preview_worker_faults import _broken_memory_worker


def test_failed_memory_channel_retires_worker_and_accepts_next_run(monkeypatch):
    """真实 spawn 连续运行两次，失败后进程、队列和预算都被回收。"""
    import backend.service.application.workflows.preview.pool as module

    monkeypatch.setattr(module, "run_preview_worker", _broken_memory_worker)
    manager = PreviewSessionManager()
    pool = PreviewSessionPool(settings=BackendServiceSettings(), manager=manager)
    manager.pool = pool
    try:
        for _ in range(2):
            sid = manager.create(
                principal_id="test",
                project_id="p",
                application_id="a",
                editor_session_id=str(uuid4()),
            )["session_id"]
            manager.subscribe(sid, "test")
            manager.submit(
                sid,
                "test",
                {
                    "request_id": str(uuid4()),
                    "document_revision": "r",
                    "timeout_seconds": 10,
                },
                pool.submit,
            )
            deadline = monotonic() + 20
            while pool._active and monotonic() < deadline:
                sleep(0.02)
            assert not pool._active
            assert manager.authorize(sid, "test").run["state"] == "failed"
            assert all(slot.process is None and not slot.busy for slot in pool._slots)
            manager.release(sid, "test")
            assert manager.buffers.stats() == {
                "blocks": 0,
                "bytes": 0,
                "pins": 0,
                "reserved_bytes": 0,
            }
    finally:
        manager.close()
