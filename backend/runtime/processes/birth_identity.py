"""平台进程出生标识；Linux 不使用随墙钟调整而变化的 boot_time 换算。"""

from __future__ import annotations

from pathlib import Path
import sys
import math
from uuid import UUID

import psutil


def read_process_birth_identity(pid: int) -> str:
    """读取指定 PID 的内核出生标识，权限、格式或进程消失均不降级。"""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError("进程 PID 无效")
    if sys.platform.startswith("linux"):
        try:
            boot_id = str(UUID(Path("/proc/sys/kernel/random/boot_id").read_text().strip()))
            stat = Path(f"/proc/{pid}/stat").read_text()
        except FileNotFoundError as error:
            raise psutil.NoSuchProcess(pid) from error
        # comm 可以包含空格和右括号，最后一个右括号之后才是固定字段。
        fields = stat.rpartition(")")[2].split()
        if int(stat.partition(" ")[0]) != pid or len(fields) < 20:
            raise ValueError("内核进程身份格式无效")
        ticks = int(fields[19])
        if ticks < 0:
            raise ValueError("内核进程启动计数无效")
        return f"linux:{boot_id}:{ticks}"
    # Windows/macOS 的创建时间直接来自内核进程记录，不以当前 boot_time 换算。
    return f"{sys.platform}:{psutil.Process(pid).create_time().hex()}"


def birth_identity_is_newer(candidate: str, previous: str) -> bool:
    """在同一平台和启动代次内比较内核出生顺序，拒绝无法比较的记录。"""
    if not isinstance(candidate, str) or not isinstance(previous, str):
        raise ValueError("缺少内核进程出生标识")
    left, right = candidate.split(":"), previous.split(":")
    if left[0] != right[0] or left[0] != sys.platform:
        raise ValueError("进程出生标识的平台不一致")
    if sys.platform.startswith("linux"):
        if len(left) != 3 or len(right) != 3 or str(UUID(left[1])) != str(UUID(right[1])):
            raise ValueError("进程出生标识不属于同一启动代次")
        first, second = int(left[2]), int(right[2])
        if first < 0 or second < 0:
            raise ValueError("进程启动计数无效")
    else:
        if len(left) != 2 or len(right) != 2:
            raise ValueError("内核进程出生标识格式无效")
        first, second = float.fromhex(left[1]), float.fromhex(right[1])
        if not all(math.isfinite(value) and value > 0 for value in (first, second)):
            raise ValueError("内核进程出生时间无效")
    return first > second
