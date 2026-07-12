"""节点参数读取公共工具测试。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter


def test_is_empty_parameter_only_treats_none_and_empty_string_as_empty() -> None:
    """数组和对象参数不能被空值判断误伤。"""

    assert is_empty_parameter(None) is True
    assert is_empty_parameter("") is True
    assert is_empty_parameter([]) is False
    assert is_empty_parameter({}) is False
    assert is_empty_parameter(0) is False
    assert is_empty_parameter(False) is False
