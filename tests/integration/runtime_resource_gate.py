"""持续负载的进程资源采样与有界趋势统计，不进入服务运行时。"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from statistics import median
from typing import Any

import psutil
from tests.integration.acceptance_contract import positive_seconds, read_measurement


class BoundedHistory(deque):
    """保留最近样本和完整计数；完整样本另存 JSONL。"""

    def __init__(self, maximum: int = 720) -> None:
        """maximum 限制内存内保留的条数。"""
        super().__init__(maxlen=maximum)
        self.total_count = 0

    def append(self, value: Any) -> None:
        """登记完整计数并添加最近记录。"""
        self.total_count += 1
        super().append(value)


class ResourceGate:
    """固定根进程身份，观测其进程树的内存、句柄和线程增长。"""

    def __init__(self, *, root_pids: tuple[int, ...], warmup_seconds: float,
                 limits: dict[str, float], sample_interval_seconds: float | None = None) -> None:
        """root_pids 只用于采样；warmup_seconds 后才形成基线；limits 是允许增长上限。"""
        self.roots = [psutil.Process(pid) for pid in set(root_pids)]
        self.identities = {process.pid: process.create_time() for process in self.roots}
        self.warmup_seconds = positive_seconds(warmup_seconds, "warmup_seconds", allow_zero=True)
        if set(limits) - {"rss_bytes", "private_bytes", "handles", "threads"}:
            raise ValueError("存在未采样的进程资源门禁字段")
        self.limits = {key: positive_seconds(value, key, allow_zero=True) for key, value in limits.items()}
        self.first: list[dict[str, float]] = []
        self.last: deque[dict[str, float]] = deque(maxlen=5)
        self.peak: dict[str, float] = {}
        self.maximum_window_growth: dict[str, float] = {}
        self.sample_count = 0
        self.errors: list[str] = []
        self.error_count = 0
        self.discarded_count = 0
        self.sample_interval_seconds = (positive_seconds(sample_interval_seconds, "sample_interval_seconds")
                                        if sample_interval_seconds is not None else None)
        self.first_sample_seconds: float | None = None
        self.last_sample_seconds: float | None = None
        self.maximum_gap_seconds = 0.0
        self.measurement_duration: float | None = None
        self.minimum_measure_seconds: float | None = None
        self.previous_cpu: dict[tuple[int, float], float] = {}
        self.previous_cpu_elapsed: float | None = None
        self.sampled_cpu_seconds = 0.0
        self.cpu_observation_seconds = 0.0
        self.peak_cpu_percent_one_core = 0.0

    def complete_measurement(self, *, duration: float, minimum_seconds: float) -> None:
        """固定真实负载区间，不能用排空或清理补足持续时长。"""
        self.measurement_duration = positive_seconds(duration, "duration", allow_zero=True)
        self.minimum_measure_seconds = positive_seconds(minimum_seconds, "minimum_seconds")

    def complete_from_phases(self, path: Path) -> None:
        """退出失败也读取已闭合的测量区间；未闭合时不能用当前时间补足。"""
        measurement = read_measurement(path)
        if measurement["started"] is not None and measurement["ended"] is not None:
            self.complete_measurement(duration=measurement["ended"] - measurement["started"],
                                      minimum_seconds=measurement["minimum_seconds"])

    def sample(self, elapsed_seconds: float) -> dict[str, Any]:
        """读取一次资源总量，根 PID 被回收或替换时明确失败。"""
        try:
            processes: dict[int, Any] = {}
            for root in self.roots:
                if not root.is_running() or root.create_time() != self.identities[root.pid]:
                    raise RuntimeError(f"采样根进程已退出或 PID 被复用：{root.pid}")
                processes[root.pid] = root
                processes.update({child.pid: child for child in root.children(recursive=True)})
            totals: dict[str, float] = {"rss_bytes": 0, "private_bytes": 0, "handles": 0, "threads": 0}
            cpu_totals: dict[tuple[int, float], float] = {}
            for process in processes.values():
                try:
                    with process.oneshot():
                        memory = process.memory_info()
                        totals["rss_bytes"] += memory.rss
                        totals["private_bytes"] += getattr(memory, "private", memory.rss)
                        totals["threads"] += process.num_threads()
                        totals["handles"] += process.num_handles() if hasattr(process, "num_handles") else process.num_fds()
                        if hasattr(process, "cpu_times"):
                            cpu = process.cpu_times()
                            cpu_totals[(process.pid, process.create_time())] = cpu.user + cpu.system
                except psutil.NoSuchProcess:
                    if process.pid in self.identities:
                        raise
                    # 正常短任务与受控故障都可能让子进程在枚举后退出。
                    # 丢弃整次不完整样本，不能把缺失进程计为零后加入趋势。
                    self.discarded_count += 1
                    return {"elapsed_seconds": elapsed_seconds,
                            "discarded": "child-exited-during-sampling", "pid": process.pid}
            self.observe(elapsed_seconds, totals)
            cpu_percent = self._observe_cpu(elapsed_seconds, cpu_totals)
            return {"elapsed_seconds": elapsed_seconds, "process_count": len(processes),
                    "cpu_percent_one_core": cpu_percent, **totals}
        except (psutil.Error, RuntimeError) as error:
            self.error_count += 1
            if len(self.errors) < 20:
                self.errors.append(str(error))
            return {"elapsed_seconds": elapsed_seconds, "error": str(error)}

    def _observe_cpu(self, elapsed: float, values: dict[tuple[int, float], float]) -> float | None:
        """采样间隔内的 CPU 时间，100% 表示占满一个逻辑核；PID 复用不能产生负差值。"""
        if elapsed < self.warmup_seconds or not values:
            return None
        percent = None
        if self.previous_cpu_elapsed is not None and elapsed > self.previous_cpu_elapsed:
            duration = elapsed - self.previous_cpu_elapsed
            used = sum(max(0., value - self.previous_cpu.get(identity, value)) for identity, value in values.items())
            percent = used / duration * 100
            self.sampled_cpu_seconds += used
            self.cpu_observation_seconds += duration
            self.peak_cpu_percent_one_core = max(self.peak_cpu_percent_one_core, percent)
        self.previous_cpu = values
        self.previous_cpu_elapsed = elapsed
        return percent

    def observe(self, elapsed_seconds: float, totals: dict[str, float]) -> None:
        """累计预热后的样本；窗口中位数抑制单个资源尖峰。"""
        if elapsed_seconds < self.warmup_seconds:
            return
        if set(self.limits) - totals.keys():
            self.error_count += 1
            if len(self.errors) < 20:
                self.errors.append("样本缺少必须测量的资源字段")
            return
        self.sample_count += 1
        if self.first_sample_seconds is None:
            self.first_sample_seconds = elapsed_seconds
            self.maximum_gap_seconds = elapsed_seconds - self.warmup_seconds
        if self.last_sample_seconds is not None:
            self.maximum_gap_seconds = max(self.maximum_gap_seconds, elapsed_seconds - self.last_sample_seconds)
        self.last_sample_seconds = elapsed_seconds
        value = dict(totals)
        if len(self.first) < 5:
            self.first.append(value)
        self.last.append(value)
        for key, number in value.items():
            self.peak[key] = max(number, self.peak.get(key, number))
        if self.sample_count >= 10:
            # 保存每个完整尾窗口的最大增长，防止退出负载后的资源释放掩盖早期泄漏。
            for key in value:
                growth = median(item[key] for item in self.last) - median(item[key] for item in self.first)
                self.maximum_window_growth[key] = max(growth, self.maximum_window_growth.get(key, growth))

    def summary(self) -> dict[str, Any]:
        """返回趋势与门禁；样本不足或采样失败时不得冒充通过。"""
        failures = []
        growth = {}
        if self.first:
            growth = {key: median(item[key] for item in self.last) - median(item[key] for item in self.first)
                      for key in self.first[0]}
        if self.limits and self.sample_count < 10:
            failures.append("资源门禁需要预热后至少 10 个样本，首尾窗口不能重叠")
        for key, limit in self.limits.items():
            maximum_growth = self.maximum_window_growth.get(key, growth.get(key, 0))
            if maximum_growth > limit:
                failures.append(f"{key} 窗口增长超限：{maximum_growth} > {limit}")
        if self.error_count:
            failures.append(f"资源采样失败 {self.error_count} 次")
        coverage = None
        maximum_gap = self.maximum_gap_seconds
        if self.sample_interval_seconds is not None:
            if self.measurement_duration is None or self.minimum_measure_seconds is None:
                failures.append("尚未收到完整的稳定负载区间")
            else:
                if self.measurement_duration < self.minimum_measure_seconds:
                    failures.append("实际稳定负载时长不足")
                expected = max(1, (self.measurement_duration - self.warmup_seconds) / self.sample_interval_seconds)
                coverage = min(1.0, self.sample_count / expected)
                maximum_gap = max(maximum_gap, self.measurement_duration - (self.last_sample_seconds or 0))
                if coverage < .9:
                    failures.append(f"稳定负载有效采样覆盖不足：{coverage:.3f} < 0.9")
                if maximum_gap > self.sample_interval_seconds * 3:
                    failures.append(f"稳定负载连续采样缺口超限：{maximum_gap:.3f}s")
        return {"sample_count": self.sample_count, "warmup_seconds": self.warmup_seconds,
                "growth": growth, "maximum_window_growth": self.maximum_window_growth,
                "peak": self.peak, "limits": self.limits,
                "discarded_count": self.discarded_count,
                "measurement_duration": self.measurement_duration, "minimum_measure_seconds": self.minimum_measure_seconds,
                "coverage": coverage, "maximum_gap_seconds": maximum_gap,
                "cpu": {"scope": "sampled-owned-processes; 100% = one logical core",
                        "observed_seconds": self.cpu_observation_seconds,
                        "sampled_cpu_seconds": self.sampled_cpu_seconds,
                        "mean_percent_one_core": self.sampled_cpu_seconds / self.cpu_observation_seconds * 100 if self.cpu_observation_seconds else None,
                        "peak_percent_one_core": self.peak_cpu_percent_one_core if self.cpu_observation_seconds else None},
                "errors": self.errors, "error_count": self.error_count, "failures": failures,
                "status": "failed" if failures else "passed" if self.limits else "observed"}
