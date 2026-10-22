"""路径写锁按打开句柄归属，避免 Linux lockf 的同进程别名问题。"""

from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from backend.service.application.runtime.io.path_write_coordinator import (
    PathWriteCoordinator,
)


def _available(path: Path) -> bool:
    """独立进程只尝试一次，测试超时用于防止测试进程残留。"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path\nimport sys\nfrom backend.service.application.runtime.io.path_write_coordinator import PathWriteCoordinator\nwith PathWriteCoordinator().try_acquire([Path(sys.argv[1])]) as acquired:\n print(acquired)",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip() == "True"


def test_nested_and_independent_coordinators_reject_same_path(tmp_path):
    """同线程重入和另一个服务协调器都不能重取已持有的路径。"""
    owner = PathWriteCoordinator()
    path = tmp_path / "asset"
    with owner.try_acquire([path]) as held:
        assert held
        with owner.try_acquire([path]) as duplicate:
            assert not duplicate
        with PathWriteCoordinator().try_acquire([path]) as other:
            assert not other
        assert not _available(path)
    assert _available(path)


def test_unrelated_descriptor_close_preserves_outer_lock(tmp_path):
    """关闭同一共享锁文件的不同路径句柄不能释放外层锁。"""
    first, second = tmp_path / "first", tmp_path / "second"
    owner = PathWriteCoordinator()
    with owner.try_acquire([first]) as held:
        assert held
        with PathWriteCoordinator().try_acquire([second]) as independent:
            assert independent
        assert not _available(first)
        assert _available(second)
    assert _available(first)


def test_other_thread_cannot_enter_and_lock_table_is_released(tmp_path):
    """进程内线程仍通过同一公共协调器，结束后引用表归零。"""
    owner = PathWriteCoordinator()
    path = tmp_path / "threaded"

    def attempt():
        with owner.try_acquire([path]) as acquired:
            return acquired

    with owner.try_acquire([path]) as held, ThreadPoolExecutor(max_workers=1) as pool:
        assert held and not pool.submit(attempt).result(timeout=5)
    assert owner._entries == {}
