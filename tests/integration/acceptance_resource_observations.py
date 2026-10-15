"""低频发行存储和 GPU 观测；缺失的设备能力明确标记 unavailable。"""

from pathlib import Path
import time
from tests.integration.acceptance_contract import positive_seconds


class ResourceObservations:
    """观测明确目录和设备，不改变模型进程或主机配置。"""

    def __init__(self, root: Path, gpu_index: int | None, *, limits: dict[str, int] | None = None) -> None:
        """root 是独立发行目录；GPU 数据是整卡观测，不冒充进程专属显存。"""
        self.root = root
        self.gpu_index = gpu_index
        self.nvml = None
        self.gpu_error = None
        self.previous_storage_at = -60.0
        self.storage = {}
        self.first = {}
        self.peak = {}
        self.last = {}
        self.limits = limits or {}
        allowed = {"gpu.used_bytes", "gpu.total_bytes", "storage.database_bytes", "storage.wal_bytes",
                   "storage.log_bytes", "storage.data_file_bytes", "storage.data_file_count"}
        if set(self.limits) - allowed or (gpu_index is None and any(key.startswith("gpu.") for key in self.limits)):
            raise ValueError("观测门禁包含未配置或不存在的资源字段")
        self.limits = {key: positive_seconds(value, key, allow_zero=True) for key, value in self.limits.items()}
        self.failures: set[str] = set()
        self.sample_count = 0
        if gpu_index is not None:
            try:
                import pynvml
                pynvml.nvmlInit()
                self.nvml = pynvml
                self.handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
            except Exception as error:
                self.gpu_error = str(error)

    def sample(self, *, measure: bool = False) -> dict:
        """存储最多每分钟扫描一次；GPU 采用设备级 used bytes 并声明范围。"""
        now = time.monotonic()
        if now - self.previous_storage_at >= 60 or (measure and self.sample_count == 0):
            totals = {"database_bytes": 0, "wal_bytes": 0, "log_bytes": 0, "data_file_bytes": 0, "data_file_count": 0}
            try:
                for folder in ("data", "logs"):
                    for path in (self.root / folder).rglob("*"):
                        try:
                            if not path.is_file():
                                continue
                            size = path.stat().st_size
                        except FileNotFoundError:
                            continue
                        if folder == "logs":
                            totals["log_bytes"] += size
                        elif path.suffix == ".db":
                            totals["database_bytes"] += size
                        elif path.name.endswith("-wal"):
                            totals["wal_bytes"] += size
                        else:
                            totals["data_file_bytes"] += size
                            totals["data_file_count"] += 1
                self.storage = {"status": "observed", **totals}
            except OSError as error:
                self.storage = {"status": "unavailable", "error": str(error)}
            self.previous_storage_at = now
        gpu = {"status": "not_requested"}
        if self.gpu_index is not None:
            try:
                if self.nvml is None:
                    raise RuntimeError(self.gpu_error)
                info = self.nvml.nvmlDeviceGetMemoryInfo(self.handle)
                gpu = {"status": "observed", "scope": "whole-device", "device_index": self.gpu_index,
                       "used_bytes": info.used, "total_bytes": info.total,
                       "uuid": self.nvml.nvmlDeviceGetUUID(self.handle)}
            except Exception as error:
                gpu = {"status": "unavailable", "error": str(error), "scope": "whole-device"}
        result = {"gpu": gpu, "storage": self.storage}
        if not measure:
            return result
        self.sample_count += 1
        for name, values in result.items():
            if values["status"] == "observed":
                numeric = {key: value for key, value in values.items() if key.endswith("bytes") or key.endswith("count")}
                self.first.setdefault(name, numeric)
                self.last[name] = numeric
                peak = self.peak.setdefault(name, {})
                for key, value in numeric.items():
                    peak[key] = max(value, peak.get(key, value))
                    field = f"{name}.{key}"
                    if field in self.limits and peak[key] - self.first[name][key] > self.limits[field]:
                        self.failures.add(f"{field} 最大增长超过 {self.limits[field]}")
            elif name == "storage" or self.gpu_index is not None:
                self.failures.add(f"{name} 测量不可用: {values.get('error', values['status'])}")
        return result

    def summary(self) -> dict:
        """稳定负载以首样本为基线；保留峰值增长，停止后的释放不能抵消超限。"""
        return {"status": "failed" if self.failures else "passed" if self.sample_count else "incomplete",
                "scope": {"gpu": "whole-device", "storage": "logical-file-bytes"},
                "samples": self.sample_count, "limits": self.limits, "first": self.first,
                "last": self.last, "peak": self.peak, "failures": sorted(self.failures)}

    def close(self) -> None:
        """释放 NVML 客户端，允许采样不可用时安全退出。"""
        if self.nvml is not None:
            self.nvml.nvmlShutdown()
            self.nvml = None
