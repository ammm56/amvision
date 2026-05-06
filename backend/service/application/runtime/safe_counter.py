"""长时间运行计数器的安全边界工具。"""

from __future__ import annotations

from dataclasses import dataclass


JSON_SAFE_INTEGER_MAX = 9007199254740991


@dataclass
class SafeCounterState:
    """描述一个对外暴露的长期累计计数器。 

    字段：
    - value：当前对外暴露的计数值；始终限制在 JavaScript 安全整数范围内。
    - rollover_count：当前计数值已经发生的 rollover 次数；用于在 value 清零重计后继续保留可观测性。
    """

    value: int = 0
    rollover_count: int = 0

    def __post_init__(self) -> None:
        """在初始化时收敛字段到安全范围。"""

        self.value = normalize_safe_counter_value(self.value)
        self.rollover_count = normalize_safe_counter_value(self.rollover_count)


def normalize_safe_counter_value(value: int | None) -> int:
    """把任意整数收敛到非负且不超过安全整数上限的范围。

    参数：
    - value：待收敛的原始计数值。

    返回：
    - int：收敛后的计数值。
    """

    if value is None:
        return 0
    normalized = int(value)
    if normalized <= 0:
        return 0
    if normalized >= JSON_SAFE_INTEGER_MAX:
        return JSON_SAFE_INTEGER_MAX
    return normalized


def increment_safe_counter(counter: SafeCounterState) -> bool:
    """安全地对长期累计计数器执行一次自增。

    规则：
    - 当 value 尚未达到安全整数上限时，直接加一。
    - 当 value 已达到安全整数上限时，value 从 1 重新开始计数，同时 rollover_count 加一。
    - rollover_count 也会限制在安全整数上限内；达到上限后继续饱和，避免再向外暴露不安全整数。

    参数：
    - counter：待更新的计数器状态。

    返回：
    - bool：当本次自增触发了 value rollover 时返回 True，否则返回 False。
    """

    counter.value = normalize_safe_counter_value(counter.value)
    counter.rollover_count = normalize_safe_counter_value(counter.rollover_count)
    if counter.value < JSON_SAFE_INTEGER_MAX:
        counter.value += 1
        return False

    counter.value = 1
    if counter.rollover_count < JSON_SAFE_INTEGER_MAX:
        counter.rollover_count += 1
    return True


def snapshot_safe_counter(counter: SafeCounterState) -> dict[str, int]:
    """生成统一的安全计数器公开快照。

    参数：
    - counter：待导出的计数器状态。

    返回：
    - dict[str, int]：包含 value 和 rollover_count 的公开快照。
    """

    return {
        "value": normalize_safe_counter_value(counter.value),
        "rollover_count": normalize_safe_counter_value(counter.rollover_count),
    }