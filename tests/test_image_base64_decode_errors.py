"""图片 Base64 解码失败保留可定位原因，不返回图片正文。"""

from types import SimpleNamespace

import pytest

from backend.nodes.core_nodes.io.image.image_base64_decode import (
    _image_base64_decode_handler,
)
from backend.service.application.errors import InvalidRequestError


@pytest.mark.parametrize("encoded", ["%%%", "x", "非 ASCII 图片"])
def test_decode_error_reports_reason_without_image(encoded: str) -> None:
    """字符、长度和编码错误都应报告原因，而不是只有模糊的外层错误。"""
    request = SimpleNamespace(
        node_id="decode", input_values={"payload": {"image_base64": encoded}}
    )
    with pytest.raises(InvalidRequestError) as failure:
        _image_base64_decode_handler(request)
    assert failure.value.details["node_id"] == "decode"
    assert failure.value.details["reason"] == str(failure.value.__cause__)
    assert "image_base64" not in failure.value.details
