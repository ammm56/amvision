"""system 路由共用服务装配工具。"""

from __future__ import annotations

from fastapi import Request

from backend.service.application.local_buffers import LocalBufferBrokerProcessSupervisor
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.settings import BackendServiceSettings


def build_local_buffer_broker_health(request: Request) -> dict[str, object]:
    """读取 LocalBufferBroker 健康摘要。"""

    supervisor = getattr(request.app.state, "local_buffer_broker_supervisor", None)
    if supervisor is None:
        return {"enabled": False, "state": "not_configured", "running": False}
    if not isinstance(supervisor, LocalBufferBrokerProcessSupervisor):
        return {"enabled": False, "state": "misconfigured", "running": False}
    return supervisor.get_health_summary()


def require_backend_service_settings(request: Request) -> BackendServiceSettings:
    """从 application.state 中读取 BackendServiceSettings。"""

    settings = getattr(request.app.state, "backend_service_settings", None)
    if not isinstance(settings, BackendServiceSettings):
        raise RuntimeError("当前服务尚未完成 backend_service_settings 装配")
    return settings


def require_session_factory(request: Request) -> SessionFactory:
    """从 application.state 中读取 SessionFactory。"""

    session_factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(session_factory, SessionFactory):
        raise RuntimeError("当前服务尚未完成 session_factory 装配")
    return session_factory

