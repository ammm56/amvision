"""backend-service lifespan 部分启动失败清理测试。"""

from __future__ import annotations

import asyncio

import pytest

from backend.service.api import app as app_module
from backend.service.settings import BackendServiceSettings


def test_lifespan_stops_partially_started_runtime_when_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start_runtime 尚未完成时抛错也必须进入统一 stop 路径。"""

    calls: list[str] = []
    runtime = object()
    settings = BackendServiceSettings(cors={"enabled": False})

    class _Bootstrap:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def load_settings(self) -> BackendServiceSettings:
            return settings

        def build_runtime(self, resolved: BackendServiceSettings) -> object:
            assert resolved is settings
            return runtime

        def initialize(self, target: object) -> None:
            assert target is runtime
            calls.append("initialize")

        def start_runtime(self, target: object) -> None:
            assert target is runtime
            calls.append("start")
            raise RuntimeError("injected partial startup failure")

        def stop_runtime(self, target: object) -> None:
            assert target is runtime
            calls.append("stop")

        def bind_application_state(self, _application: object, target: object) -> None:
            assert target is runtime

    monkeypatch.setattr(app_module, "BackendServiceBootstrap", _Bootstrap)
    monkeypatch.setattr(app_module, "_register_frontend_static_files", lambda _app: None)
    application = app_module.create_app()

    async def enter_lifespan() -> None:
        """进入待测 lifespan 并触发注入的启动失败。"""

        async with application.router.lifespan_context(application):
            pass

    with pytest.raises(RuntimeError, match="partial startup failure"):
        asyncio.run(enter_lifespan())

    assert calls == ["initialize", "start", "stop"]
