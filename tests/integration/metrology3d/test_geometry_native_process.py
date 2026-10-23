"""原生算法沿现有跨平台进程归属退出；测试值不作为生产 timeout。"""

import json
from pathlib import Path
import sys

import pytest

from backend.runtime.processes import ProcessTreeSupervisor
from backend.runtime.processes.ownership import OwnershipScope, SCOPE_ENV, PARENT_ENV
from backend.service.application.errors import (
    OperationCancelledError,
    OperationTimeoutError,
)


@pytest.fixture
def ownership(tmp_path, monkeypatch):
    """全部控制文件在本用例原生临时目录，不接触正在运行的开发服务。"""
    scope = OwnershipScope.create(tmp_path / "ownership")
    monkeypatch.setenv(SCOPE_ENV, str(scope.root))
    monkeypatch.delenv(PARENT_ENV, raising=False)
    try:
        yield scope
    finally:
        scope.stop()
        scope.require_empty()


@pytest.mark.parametrize("mode", ["cancel", "timeout"])
def test_native_call_stops_with_existing_process_group(tmp_path, ownership, mode):
    """原生进入后取消或 deadline 都须确认整组清空，而非只看根退出码。"""
    marker = tmp_path / "native-state.txt"
    error = OperationCancelledError if mode == "cancel" else OperationTimeoutError
    with pytest.raises(error):
        ProcessTreeSupervisor(timeout_seconds=10, termination_grace_seconds=0.1).run(
            [
                sys.executable,
                "-m",
                "tests.integration.metrology3d.native_geometry_worker",
                "hold",
                "--marker",
                str(marker),
            ],
            cwd=Path(__file__).resolve().parents[3],
            cancel_requested=marker.exists if mode == "cancel" else None,
        )
    assert marker.read_text("utf-8") == "native-entering"
    ownership.require_empty()


def test_native_resources_in_reused_process(tmp_path, ownership):
    """记录短重复调用的真实 RSS/线程，不自拟尚未批准的资源门禁。"""
    result = ProcessTreeSupervisor(timeout_seconds=60).run(
        [
            sys.executable,
            "-m",
            "tests.integration.metrology3d.native_geometry_worker",
            "resources",
        ],
        cwd=Path(__file__).resolve().parents[3],
    )
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout.strip().splitlines()[-1])
    assert record["cycles"] == len(record["samples"]) == 20
    assert all(
        sample["rss"] > 0 and sample["threads"] > 0 for sample in record["samples"]
    )
    ownership.require_empty()
    rss = [sample["rss"] for sample in record["samples"]]
    threads = [sample["threads"] for sample in record["samples"]]
    print(
        dict(
            native_cycles=20,
            rss_first=rss[0],
            rss_last=rss[-1],
            rss_max=max(rss),
            threads_first=threads[0],
            threads_last=threads[-1],
            threads_max=max(threads),
        )
    )
