"""本地用户、会话与长期调用 token 的 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.service.infrastructure.persistence.base import Base


class LocalAuthUserRecord(Base):
    """映射本地鉴权用户。"""

    __tablename__ = "auth_users"
    __table_args__ = (
        UniqueConstraint("provider_kind", "provider_subject", name="uq_auth_users_provider_subject"),
    )

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider_kind: Mapped[str] = mapped_column(String(32), index=True)
    provider_subject: Mapped[str] = mapped_column(String(256), index=True)
    username: Mapped[str] = mapped_column(String(256), index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    principal_type: Mapped[str] = mapped_column(String(32), default="user")
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    project_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    scopes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64))
    last_login_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class LocalAuthSessionRecord(Base):
    """映射本地鉴权 access token 会话。"""

    __tablename__ = "auth_sessions"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    last_used_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class LocalAuthRefreshTokenRecord(Base):
    """映射本地登录会话的 refresh token。"""

    __tablename__ = "auth_refresh_tokens"

    refresh_token_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    last_used_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class LocalAuthUserTokenRecord(Base):
    """映射长期调用的本地 user token。"""

    __tablename__ = "auth_user_tokens"
    __table_args__ = (
        UniqueConstraint("user_id", "token_name", name="uq_auth_user_tokens_user_token_name"),
    )

    token_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    token_name: Mapped[str] = mapped_column(String(128), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    last_used_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)