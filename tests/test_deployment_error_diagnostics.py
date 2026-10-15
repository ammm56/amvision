"""子进程异常诊断保留内部堆栈，同时维持公开错误边界。"""
from queue import SimpleQueue

from backend.service.application.runtime.deployment.deployment_process_worker import _put_error_response


def test_empty_exception_has_type_message_and_internal_trace(caplog):
    """无文本异常仍能定位，公开响应不包含 traceback。"""
    queue = SimpleQueue()
    try:
        raise AssertionError()
    except AssertionError as error:
        _put_error_response(response_queue=queue, request_id="request-test", error=error)
    response = queue.get_nowait()
    assert response["error"]["message"] == "AssertionError"
    assert response["error"]["details"] == {"error_type": "AssertionError"}
    assert "request-test" in caplog.text
    assert caplog.records[0].exc_info[2] is not None
