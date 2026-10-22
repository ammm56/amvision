"""取消及叶进程终止后释放文件，不建立新的平台进程管理入口。"""

from io import BytesIO
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pytest
from pypcd4 import Encoding, PointCloud
from trimesh.exchange import ply

from test_pcd import LIMITS, source as pcd_source
from test_ply import source as ply_source


@pytest.mark.parametrize("kind", ["ply", "pcd"])
def test_cancel_mid_read_closes_owned_file(tmp_path, kind):
    path = tmp_path / f"cancel.{kind}"
    make = ply_source if kind == "ply" else pcd_source
    path.write_bytes(make(b"1 2 3\n" * 10, count=10))
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise InterruptedError("cancel after a decoded chunk")

    with pytest.raises(InterruptedError):
        with path.open("rb") as stream:
            if kind == "ply":
                header = ply.read_ply_header(stream, max_header_bytes=4096)
                ply.read_ply_data(
                    stream,
                    header,
                    max_decoded_bytes=4096,
                    chunk_rows=2,
                    chunk_bytes=128,
                    cancel=cancel,
                )
            else:
                PointCloud.from_fileobj(stream, **LIMITS, cancel=cancel)
    assert calls == 3
    path.unlink()
    assert not path.exists()


@pytest.mark.parametrize("kind", ["ply", "pcd"])
def test_cancel_write_does_not_report_success(tmp_path, kind):
    path = tmp_path / f"cancel-write.{kind}"
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise InterruptedError("cancel write")

    with pytest.raises(InterruptedError):
        with path.open("wb") as stream:
            if kind == "ply":
                data = np.ones(10, dtype=[("x", "f4"), ("y", "f4"), ("z", "f4")])
                ply.write_ply_points(
                    stream, data, encoding="ascii", chunk_rows=2, cancel=cancel
                )
            else:
                pc = PointCloud.from_fileobj(
                    BytesIO(pcd_source(b"1 2 3\n" * 10, count=10)), **LIMITS
                )
                pc.save(
                    stream,
                    Encoding.BINARY,
                    chunk_rows=2,
                    max_working_bytes=4096,
                    cancel=cancel,
                )
    path.unlink()


@pytest.mark.parametrize("kind", ["ply", "pcd"])
def test_terminated_leaf_releases_open_file(tmp_path, kind):
    path = tmp_path / f"terminate.{kind}"
    make = ply_source if kind == "ply" else pcd_source
    path.write_bytes(make())
    worker = Path(__file__).with_name("termination_worker.py")
    child = subprocess.Popen(
        [sys.executable, str(worker), str(path), kind],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # 测试固定期限仅防止夹具挂住，不是生产 timeout。
        ready = path.with_suffix(".ready")
        deadline = time.monotonic() + 20
        while not ready.exists():
            if child.poll() is not None:
                raise AssertionError(child.communicate()[1].decode())
            if time.monotonic() > deadline:
                raise AssertionError("fixture not ready")
            time.sleep(0.02)
        child.terminate()
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)
    path.unlink()
    assert not path.exists()
