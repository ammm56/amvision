"""Trigger 调用结果的稳定错误分类。"""

from __future__ import annotations

from backend.contracts.workflows import TriggerResultContract


BUSY_ERROR_CODES = frozenset(
    {
        "deployment_inference_busy",
        "trigger_executor_busy",
        "trigger_source_busy",
        "workflow_runtime_busy",
    }
)
"""不应排队或重试的当前执行槽位占用错误。"""


CAPACITY_ERROR_CODES = frozenset(
    {
        "local_buffer_capacity_exhausted",
        "local_buffer_contiguous_capacity_exhausted",
        "local_buffer_output_capacity_exhausted",
        "trigger_response_capacity_exhausted",
        "zeromq_transport_capacity_exhausted",
    }
)
"""内存、响应页或传输生命周期表的硬容量错误。"""


def read_trigger_result_error_code(result: TriggerResultContract) -> str | None:
    """从统一 TriggerResult error 读取稳定错误码。"""

    return result.error.code if result.error is not None else None
