"""系统诊断服务状态测试。"""

from types import SimpleNamespace

import pytest

from backend.service.api.rest.v1.routes.system import diagnostics


@pytest.mark.parametrize(
    ("dependency_installed", "adapter_configured", "expected_status"),
    (
        (False, False, "missing"),
        (False, True, "missing"),
        (True, False, "not_configured"),
        (True, True, "available"),
    ),
)
def test_zeromq_service_status_requires_dependency_and_adapter(
    monkeypatch: pytest.MonkeyPatch,
    dependency_installed: bool,
    adapter_configured: bool,
    expected_status: str,
) -> None:
    """验证 ZeroMQ 只有在依赖和协议 adapter 同时就绪时才标记为可用。"""

    monkeypatch.setattr(
        diagnostics,
        "_build_dependency_status",
        lambda _distribution, _import_name: {"installed": dependency_installed},
    )
    adapters = {"zeromq-topic": object()} if adapter_configured else {}

    summary = diagnostics._build_zeromq_service_summary(
        SimpleNamespace(adapters=adapters)
    )

    assert summary["status"] == expected_status
    assert summary["available"] is (
        dependency_installed and adapter_configured
    )
    assert summary["adapter_configured"] is adapter_configured
