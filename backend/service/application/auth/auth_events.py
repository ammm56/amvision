"""鉴权与 token 审计事件构造器。"""

from __future__ import annotations

from backend.service.application.events import ServiceEvent


AUTH_EVENTS_STREAM = "auth.events"
AUTH_EVENTS_RESOURCE_KIND = "auth_audit"
AUTH_EVENTS_RESOURCE_ID = "audit"


def build_auth_service_event(
    *,
    event_type: str,
    occurred_at: str,
    provider_id: str,
    provider_kind: str,
    user_id: str | None,
    actor_user_id: str | None,
    principal_type: str | None,
    credential_kind: str | None,
    credential_id: str | None,
    payload: dict[str, object] | None = None,
) -> ServiceEvent:
    """构造一条统一的 auth 审计事件。

    参数：
    - event_type：事件类型。
    - occurred_at：事件发生时间。
    - provider_id：provider 稳定标识。
    - provider_kind：provider 类型。
    - user_id：被影响的用户 id。
    - actor_user_id：触发动作的用户 id；为空表示系统动作。
    - principal_type：被影响主体类型。
    - credential_kind：凭据类型，例如 session、user-token。
    - credential_id：凭据 id。
    - payload：附加结构化正文。

    返回：
    - ServiceEvent：可发布到统一 service_event_bus 的审计事件。
    """

    merged_payload = {
        "provider_id": provider_id,
        "provider_kind": provider_kind,
        "user_id": user_id,
        "actor_user_id": actor_user_id,
        "principal_type": principal_type,
        "credential_kind": credential_kind,
        "credential_id": credential_id,
    }
    if payload is not None:
        merged_payload.update(payload)

    cursor_resource_id = credential_id or user_id or AUTH_EVENTS_RESOURCE_ID
    return ServiceEvent(
        stream=AUTH_EVENTS_STREAM,
        resource_kind=AUTH_EVENTS_RESOURCE_KIND,
        resource_id=AUTH_EVENTS_RESOURCE_ID,
        event_type=event_type,
        event_version="v1",
        occurred_at=occurred_at,
        cursor=f"{occurred_at}|{event_type}|{cursor_resource_id}",
        payload=merged_payload,
    )