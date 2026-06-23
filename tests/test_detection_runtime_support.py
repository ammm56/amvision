"""detection runtime support 测试。"""

from __future__ import annotations

from backend.service.application.runtime.support.detection import (
    resolve_openvino_compiled_runtime_precision,
)


class _FakeOpenVINOSession:
    """模拟 OpenVINO compiled model 的 precision hint 读取。"""

    def __init__(self, value: object) -> None:
        self.value = value

    def get_property(self, name: str) -> object:
        """返回测试指定的 OpenVINO property。"""

        assert name == "INFERENCE_PRECISION_HINT"
        return self.value


def test_resolve_openvino_compiled_runtime_precision_reads_session_hint() -> None:
    """验证已有 compiled session 会优先返回真实 precision hint。"""

    precision = resolve_openvino_compiled_runtime_precision(
        session=_FakeOpenVINOSession("f16"),
        fallback_precision="fp32",
    )

    assert precision == "fp16"


def test_resolve_openvino_compiled_runtime_precision_supports_requested_metadata() -> None:
    """验证没有 session 时可按请求和 compile properties 记录 metadata。"""

    precision = resolve_openvino_compiled_runtime_precision(
        requested_runtime_precision="fp16",
        compile_properties={object(): object()},
        fallback="fp32",
    )

    assert precision == "fp16"
