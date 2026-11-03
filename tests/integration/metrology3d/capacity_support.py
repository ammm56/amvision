"""容量验收使用真实逐块写入的数据，不以稀疏文件或虚假长度替代。"""

from contextlib import contextmanager
import json
from pathlib import Path
import platform
from threading import Event, Thread
from time import perf_counter

import numpy as np
import psutil

from backend.service.settings import BackendServiceSettings
from tests.point_cloud_support import options


ROWS = 65536
DTYPE = np.dtype([(name, "<f4") for name in ("x", "y", "z")] + [("serial", "<u4")])


def settings():
    """加载随节点包提供的显式容量配置，不修改当前生产配置。"""
    path = (
        Path(__file__).resolve().parents[3]
        / "custom_nodes/metrology3d_nodes/workstation-1gb.example.json"
    )
    return BackendServiceSettings.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def read_options():
    """位置和原始序号均为必读字段，禁止只验证 XYZ。"""
    return options(
        "ply-binary-le",
        extra=(
            {
                "source_names": ["serial"],
                "target_name": "serial",
                "semantic": "scalar",
                "dtype": "uint32",
                "components": 1,
                "unit": None,
            },
        ),
    )


def records(start, stop):
    """独立整数公式产生可逐行核对的非空数据。"""
    index = np.arange(start, stop, dtype="<u4")
    result = np.empty(stop - start, dtype=DTYPE)
    result["x"] = index % 1024
    result["y"] = (index // 1024) % 4096
    result["z"] = 0.25
    result["serial"] = index
    return result


def write_ply(path, size):
    """有效 header 对齐后写满每个记录，最终文件恰为指定字节数。"""
    assert 1024 <= size <= 1000000000 and size % 16 == 0
    header_size = 256
    count = (size - header_size) // DTYPE.itemsize
    head = (
        f"ply\nformat binary_little_endian 1.0\nelement vertex {count}\n"
        "property float x\nproperty float y\nproperty float z\nproperty uint serial\ncomment "
    ).encode()
    header = (
        head
        + b"x" * (header_size - len(head) - len(b"\nend_header\n"))
        + b"\nend_header\n"
    )
    assert len(header) == header_size
    with path.open("wb") as stream:
        stream.write(header)
        for start in range(0, count, ROWS):
            block = records(start, min(start + ROWS, count))
            assert stream.write(memoryview(block).cast("B")) == block.nbytes
    assert path.stat().st_size == size
    return count


def assert_cloud(runtime, cloud, count):
    """核对所有行、所有字段和源点数，不抽样替代完整容量验证。"""
    assert cloud.point_count == runtime.source_point_count(cloud) == count
    with runtime.borrow(cloud) as view:
        for start in range(0, count, ROWS):
            stop = min(start + ROWS, count)
            actual = view.chunk(start, stop)
            expected = records(start, stop)
            for column, name in enumerate(("x", "y", "z")):
                np.testing.assert_array_equal(
                    actual["positions"][:, column], expected[name]
                )
            np.testing.assert_array_equal(
                actual["serial"].reshape(-1), expected["serial"]
            )
            np.testing.assert_array_equal(
                view.source_indices(start, stop), expected["serial"]
            )
            assert not actual["positions"].flags.writeable


@contextmanager
def report(request, name):
    """记录当前验收进程的 RSS；不冒称包含独立 worker 的内存。"""
    process = psutil.Process()
    baseline = process.memory_info().rss
    result = {
        "platform": platform.platform(),
        "input_bytes": request.config.getoption("--cloud-capacity-bytes"),
        "rss_baseline_bytes": baseline,
        "rss_peak_bytes": baseline,
        "stages": {},
        "passed": False,
    }
    stop = Event()

    def sample():
        while not stop.wait(0.05):
            result["rss_peak_bytes"] = max(
                result["rss_peak_bytes"], process.memory_info().rss
            )

    thread = Thread(target=sample, name="capacity-rss", daemon=False)
    thread.start()
    started = perf_counter()
    try:
        yield result
        result["passed"] = True
    finally:
        stop.set()
        thread.join()
        result["seconds"] = perf_counter() - started
        result["rss_final_bytes"] = process.memory_info().rss
        destination = request.config.getoption("--cloud-report-dir")
        if destination:
            path = Path(destination)
            path.mkdir(parents=True, exist_ok=True)
            (path / f"capacity-{name}-{platform.system().lower()}.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )


@contextmanager
def stage(result, name):
    """分阶段计时只用于容量路径定位，不作为十秒测量门禁。"""
    started = perf_counter()
    try:
        yield
    finally:
        result["stages"][name] = perf_counter() - started
