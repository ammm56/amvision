"""未知节点异常必须可定位，公开错误契约仍由既有脱敏层控制。"""
import logging
from types import SimpleNamespace

from backend.service.application.workflows.execution.events import build_failed_node_details


def test_node_error_keeps_original_traceback_in_server_log(caplog):
    """空字符串异常也保留真实类型及堆栈，不仅返回通用失败消息。"""
    try:
        raise TimeoutError()
    except TimeoutError as error:
        with caplog.at_level(logging.ERROR):
            details = build_failed_node_details(node=SimpleNamespace(node_id="consume", metadata={}),
                node_definition=SimpleNamespace(node_type_id="custom.opencv.grayscale",
                    display_name="Grayscale", runtime_kind="python-callable"),
                execution_index=3, exc=error)
        assert caplog.records[-1].exc_info[1] is error
    assert details["error_type"] == "TimeoutError"
    assert "consume" in caplog.text
