"""真实调用审计必须识别进程重启，不能只比较复用的 PID。"""

from types import SimpleNamespace

import pytest

from tests.integration import local_file_reading_live_audit as audit


def test_process_sample_preserves_identity_and_resource_counts(monkeypatch) -> None:
    """资源计数与创建时间属于同一进程身份。"""

    process = SimpleNamespace(
        create_time=lambda: 123.0,
        memory_info=lambda: SimpleNamespace(private=1024, rss=2048),
        num_handles=lambda: 12,
        num_threads=lambda: 3,
    )
    monkeypatch.setattr(audit.psutil, "Process", lambda pid: process)
    assert audit.process_sample(42, 123.0) == {
        "pid": 42, "created_at": 123.0, "private_bytes": 1024,
        "rss_bytes": 2048, "handles": 12, "threads": 3,
    }


def test_process_sample_rejects_reused_pid(monkeypatch) -> None:
    """相同 PID 的创建时间变化时，审计立即报错。"""

    monkeypatch.setattr(
        audit.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 456.0),
    )
    with pytest.raises(RuntimeError, match="进程已重启"):
        audit.process_sample(42, 123.0)
