"""真实进程归属测试：中间进程退出后，末级进程继续持有文件。"""

from pathlib import Path
import subprocess
import sys
import time


def fake_birth_identity(order: float) -> str:
    """为假进程表构造可排序的当前平台内核身份，不读取真实 PID。"""
    if sys.platform.startswith("linux"):
        return f"linux:a1234567-1234-1234-1234-123456789012:{int(order * 100)}"
    return f"{sys.platform}:{float(order).hex()}"


def main() -> None:
    """通过文件握手固定派生时序，不依赖测试进程猜测执行速度。"""
    role, directory = sys.argv[1:3]
    root = Path(directory)
    if role == "leaf":
        with (root / "held-file").open("wb"):
            (root / "leaf-ready").write_text(str(__import__("os").getpid()))
            time.sleep(120)
        return
    child = subprocess.Popen(
        [sys.executable, __file__, "leaf" if role == "middle" else "middle", directory],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if role == "middle":
        deadline = time.perf_counter() + 15
        while not (root / "leaf-ready").exists():
            if time.perf_counter() >= deadline:
                raise TimeoutError("leaf 未就绪")
            time.sleep(.01)
        return
    child.wait(timeout=20)
    (root / "root-ready").write_text(str(child.pid))
    time.sleep(120)


if __name__ == "__main__":
    main()
