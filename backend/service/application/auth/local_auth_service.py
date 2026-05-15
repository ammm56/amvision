"""本地用户、登录会话、refresh token 和长期调用 token 服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.auth.auth_events import build_auth_service_event
from backend.service.application.errors import (
    AuthenticationRequiredError,
    InvalidRequestError,
    PersistenceOperationError,
    ResourceNotFoundError,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.persistence.local_auth_orm import (
    LocalAuthRefreshTokenRecord,
    LocalAuthSessionRecord,
    LocalAuthUserRecord,
    LocalAuthUserTokenRecord,
)
from backend.service.settings import BackendServiceSettings


_PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
_PASSWORD_HASH_ITERATIONS = 600_000
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{2,63}$")
_TOKEN_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")
_LOCAL_PROVIDER_ID = "local"


@dataclass(frozen=True)
class LocalAuthUser:
    """描述一个本地鉴权用户。"""

    user_id: str
    provider_kind: str
    username: str
    display_name: str
    principal_type: str
    project_ids: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""
    last_login_at: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAuthResolvedCredential:
    """描述一次本地 Bearer token 解析结果。"""

    credential_kind: str
    credential_id: str
    credential_name: str | None
    expires_at: str | None
    user: LocalAuthUser


@dataclass(frozen=True)
class LocalAuthSessionResult:
    """描述一次登录、bootstrap 或 refresh 返回的会话凭据。"""

    session_id: str
    access_token: str
    access_expires_at: str | None
    refresh_token: str
    refresh_expires_at: str | None
    user: LocalAuthUser


@dataclass(frozen=True)
class LocalAuthUserToken:
    """描述一个长期调用 user token 的公开摘要。"""

    token_id: str
    user_id: str
    token_name: str
    created_at: str
    expires_at: str | None
    last_used_at: str | None
    revoked_at: str | None
    created_by_user_id: str | None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAuthIssuedUserToken:
    """描述一次新签发的长期调用 user token。"""

    token: str
    user_token: LocalAuthUserToken


@dataclass(frozen=True)
class LocalAuthBootstrapAdminRequest:
    """描述一次本地管理员 bootstrap 请求。"""

    username: str
    password: str
    display_name: str | None = None


@dataclass(frozen=True)
class LocalAuthUserTokenCreateRequest:
    """描述一次长期调用 user token 创建请求。"""

    token_name: str = "default"
    ttl_hours: int | None = None
    expires_at: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAuthInitializeDefaultUserRequest:
    """描述空库启动时默认本地用户初始化请求。"""

    username: str
    password: str
    display_name: str | None = None
    principal_type: str = "user"
    project_ids: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    user_token_name: str = "default"
    user_token: str = ""
    user_token_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAuthUserCreateRequest:
    """描述一次本地用户创建请求。"""

    username: str
    password: str
    display_name: str | None = None
    principal_type: str = "user"
    project_ids: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    initial_user_token: LocalAuthUserTokenCreateRequest | None = field(
        default_factory=LocalAuthUserTokenCreateRequest
    )


@dataclass(frozen=True)
class LocalAuthUserCreateResult:
    """描述一次本地用户创建结果。"""

    user: LocalAuthUser
    initial_user_token: LocalAuthIssuedUserToken | None = None


@dataclass(frozen=True)
class LocalAuthUserUpdateRequest:
    """描述一次本地用户更新请求。"""

    display_name: str | None = None
    password: str | None = None
    project_ids: tuple[str, ...] | None = None
    scopes: tuple[str, ...] | None = None
    is_active: bool | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class LocalAuthPasswordResetRequest:
    """描述一次本地用户密码重置请求。"""

    new_password: str
    revoke_sessions: bool = True
    revoke_user_tokens: bool = False


class LocalAuthService:
    """封装本地用户、登录会话、refresh token 和长期调用 token 的持久化逻辑。"""

    def __init__(self, *, settings: BackendServiceSettings, session_factory: SessionFactory) -> None:
        """初始化本地鉴权服务。"""

        self.settings = settings
        self.session_factory = session_factory
        self.service_event_bus = getattr(session_factory, "service_event_bus", None)

    def has_any_users(self) -> bool:
        """判断当前是否已经初始化过本地用户。"""

        with self.session_factory.create_session() as session:
            try:
                user_count = session.execute(select(func.count()).select_from(LocalAuthUserRecord)).scalar_one()
            except SQLAlchemyError as error:
                raise PersistenceOperationError(
                    "统计本地用户失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return bool(user_count)

    def bootstrap_admin(self, request: LocalAuthBootstrapAdminRequest) -> LocalAuthSessionResult:
        """在用户表为空时初始化一个本地管理员并签发登录会话。"""

        self._require_local_auth_enabled()
        username = self._normalize_username(request.username)
        display_name = self._normalize_display_name(request.display_name, username)
        self._validate_password(request.password)
        now = _now_isoformat()

        with self.session_factory.create_session() as session:
            try:
                user_count = session.execute(select(func.count()).select_from(LocalAuthUserRecord)).scalar_one()
                if user_count:
                    raise InvalidRequestError("本地管理员已初始化，不能重复 bootstrap")

                user_record = LocalAuthUserRecord(
                    user_id=_build_user_id(),
                    provider_kind="local",
                    provider_subject=username.casefold(),
                    username=username,
                    display_name=display_name,
                    principal_type="user",
                    password_hash=_hash_password(request.password),
                    is_active=True,
                    project_ids_json=[],
                    scopes_json=["*"],
                    created_at=now,
                    updated_at=now,
                    last_login_at=now,
                    metadata_json={"bootstrap_admin": True},
                )
                session.add(user_record)
                session_result = self._issue_session(
                    session=session,
                    user_record=user_record,
                    auth_source="local-bootstrap",
                )
                session.commit()
                self._flush_pending_auth_events(session)
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "初始化本地管理员失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return session_result

    def login(self, *, username: str, password: str) -> LocalAuthSessionResult:
        """按用户名和密码登录本地用户，并签发新的登录会话。"""

        self._require_local_auth_enabled()
        normalized_subject = self._normalize_username(username).casefold()
        now = _now_isoformat()
        with self.session_factory.create_session() as session:
            try:
                user_record = session.execute(
                    select(LocalAuthUserRecord).where(
                        LocalAuthUserRecord.provider_kind == "local",
                        LocalAuthUserRecord.provider_subject == normalized_subject,
                    )
                ).scalar_one_or_none()
                if user_record is None or not user_record.is_active:
                    raise AuthenticationRequiredError("用户名或密码错误")
                if not _verify_password(password, user_record.password_hash):
                    raise AuthenticationRequiredError("用户名或密码错误")

                user_record.last_login_at = now
                user_record.updated_at = now
                session_result = self._issue_session(
                    session=session,
                    user_record=user_record,
                    auth_source="local-login",
                )
                session.commit()
                self._flush_pending_auth_events(session)
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "本地用户登录失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return session_result

    def refresh_session(self, refresh_token: str) -> LocalAuthSessionResult:
        """使用 refresh token 刷新一组新的登录会话凭据。"""

        self._require_local_auth_enabled()
        refresh_token_hash = _hash_token(refresh_token)
        now = _now_isoformat()
        with self.session_factory.create_session() as session:
            try:
                refresh_record = session.execute(
                    select(LocalAuthRefreshTokenRecord).where(
                        LocalAuthRefreshTokenRecord.token_hash == refresh_token_hash,
                    )
                ).scalar_one_or_none()
                if refresh_record is None or refresh_record.revoked_at is not None:
                    raise AuthenticationRequiredError("refresh token 无效")
                if _is_expired(refresh_record.expires_at):
                    refresh_record.revoked_at = now
                    session.commit()
                    self._flush_pending_auth_events(session)
                    raise AuthenticationRequiredError("refresh token 已过期")

                user_record = session.get(LocalAuthUserRecord, refresh_record.user_id)
                if user_record is None or not user_record.is_active:
                    refresh_record.revoked_at = now
                    self._revoke_session_record(
                        session,
                        refresh_record.session_id,
                        revoked_at=now,
                        reason="user-inactive",
                        actor_user_id=None,
                    )
                    session.commit()
                    self._flush_pending_auth_events(session)
                    raise AuthenticationRequiredError("refresh token 无效")

                refresh_record.last_used_at = now
                refresh_record.revoked_at = now
                self._revoke_session_record(
                    session,
                    refresh_record.session_id,
                    revoked_at=now,
                    reason="refresh-rotated",
                    actor_user_id=user_record.user_id,
                )
                user_record.updated_at = now
                session_result = self._issue_session(
                    session=session,
                    user_record=user_record,
                    auth_source="local-refresh",
                )
                session.commit()
                self._flush_pending_auth_events(session)
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "刷新本地登录会话失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return session_result

    def resolve_bearer_token(self, bearer_token: str) -> LocalAuthResolvedCredential | None:
        """按 Bearer token 解析本地登录会话或长期调用 token。"""

        if not self._local_bearer_auth_enabled():
            return None
        token_hash = _hash_token(bearer_token)
        now = _now_isoformat()
        with self.session_factory.create_session() as session:
            try:
                should_commit = False
                session_record = session.execute(
                    select(LocalAuthSessionRecord).where(LocalAuthSessionRecord.token_hash == token_hash)
                ).scalar_one_or_none()
                if session_record is not None:
                    resolved_session = self._resolve_session_record(
                        session=session,
                        session_record=session_record,
                        revoked_at=now,
                    )
                    if resolved_session is not None:
                        session.commit()
                        self._flush_pending_auth_events(session)
                        return resolved_session
                    should_commit = True

                user_token_record = session.execute(
                    select(LocalAuthUserTokenRecord).where(LocalAuthUserTokenRecord.token_hash == token_hash)
                ).scalar_one_or_none()
                if user_token_record is not None:
                    resolved_user_token = self._resolve_user_token_record(
                        session=session,
                        user_token_record=user_token_record,
                        revoked_at=now,
                    )
                    if resolved_user_token is not None:
                        session.commit()
                        self._flush_pending_auth_events(session)
                        return resolved_user_token
                    should_commit = True

                if should_commit:
                    session.commit()
                    self._flush_pending_auth_events(session)
                else:
                    session.rollback()
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "解析本地 Bearer token 失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return None

    def revoke_session_access_token(
        self,
        access_token: str,
        *,
        expected_user_id: str | None = None,
        actor_user_id: str | None = None,
    ) -> bool:
        """撤销一个登录会话 access token，并级联撤销对应 refresh token。"""

        if not self._local_bearer_auth_enabled():
            return False
        token_hash = _hash_token(access_token)
        now = _now_isoformat()
        with self.session_factory.create_session() as session:
            try:
                session_record = session.execute(
                    select(LocalAuthSessionRecord).where(LocalAuthSessionRecord.token_hash == token_hash)
                ).scalar_one_or_none()
                if session_record is None or session_record.revoked_at is not None:
                    return False
                if expected_user_id is not None and session_record.user_id != expected_user_id:
                    return False
                self._revoke_session_record(
                    session,
                    session_record.session_id,
                    revoked_at=now,
                    reason="logout",
                    actor_user_id=actor_user_id,
                )
                self._revoke_refresh_tokens_for_session(session, session_record.session_id, revoked_at=now)
                session.commit()
                self._flush_pending_auth_events(session)
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "撤销本地登录会话失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return True

    def list_users(self) -> tuple[LocalAuthUser, ...]:
        """列出全部本地用户。"""

        self._require_local_auth_enabled()
        with self.session_factory.create_session() as session:
            try:
                records = session.execute(
                    select(LocalAuthUserRecord).order_by(
                        LocalAuthUserRecord.created_at.desc(),
                        LocalAuthUserRecord.user_id.desc(),
                    )
                ).scalars().all()
            except SQLAlchemyError as error:
                raise PersistenceOperationError(
                    "列出本地用户失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return tuple(_user_from_record(record) for record in records)

    def get_user(self, user_id: str) -> LocalAuthUser:
        """按 id 读取一个本地用户。"""

        self._require_local_auth_enabled()
        with self.session_factory.create_session() as session:
            try:
                record = session.get(LocalAuthUserRecord, user_id)
            except SQLAlchemyError as error:
                raise PersistenceOperationError(
                    "读取本地用户失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        if record is None:
            raise ResourceNotFoundError("请求的本地用户不存在", details={"user_id": user_id})
        return _user_from_record(record)

    def create_user(
        self,
        request: LocalAuthUserCreateRequest,
        *,
        created_by_user_id: str | None = None,
    ) -> LocalAuthUserCreateResult:
        """创建一个本地用户，并按需签发默认长期调用 token。"""

        self._require_local_auth_enabled()
        username = self._normalize_username(request.username)
        display_name = self._normalize_display_name(request.display_name, username)
        principal_type = self._normalize_principal_type(request.principal_type)
        self._validate_password(request.password)
        project_ids = _normalize_string_collection(request.project_ids, field_name="project_ids")
        scopes = _normalize_string_collection(request.scopes, field_name="scopes")
        now = _now_isoformat()

        with self.session_factory.create_session() as session:
            try:
                existing_record = session.execute(
                    select(LocalAuthUserRecord).where(
                        LocalAuthUserRecord.provider_kind == "local",
                        LocalAuthUserRecord.provider_subject == username.casefold(),
                    )
                ).scalar_one_or_none()
                if existing_record is not None:
                    raise InvalidRequestError(
                        "username 已存在",
                        details={"username": username},
                    )

                user_record = LocalAuthUserRecord(
                    user_id=_build_user_id(),
                    provider_kind="local",
                    provider_subject=username.casefold(),
                    username=username,
                    display_name=display_name,
                    principal_type=principal_type,
                    password_hash=_hash_password(request.password),
                    is_active=True,
                    project_ids_json=list(project_ids),
                    scopes_json=list(scopes),
                    created_at=now,
                    updated_at=now,
                    last_login_at=None,
                    metadata_json=_build_local_provider_metadata(request.metadata),
                )
                session.add(user_record)
                issued_user_token = None
                if request.initial_user_token is not None:
                    issued_user_token = self._issue_user_token(
                        session=session,
                        user_record=user_record,
                        request=request.initial_user_token,
                        created_by_user_id=created_by_user_id,
                    )
                session.commit()
                self._flush_pending_auth_events(session)
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "创建本地用户失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return LocalAuthUserCreateResult(
            user=_user_from_record(user_record),
            initial_user_token=issued_user_token,
        )

    def update_user(self, user_id: str, request: LocalAuthUserUpdateRequest) -> LocalAuthUser:
        """更新一个本地用户。"""

        self._require_local_auth_enabled()
        with self.session_factory.create_session() as session:
            try:
                record = session.get(LocalAuthUserRecord, user_id)
                if record is None:
                    raise ResourceNotFoundError("请求的本地用户不存在", details={"user_id": user_id})

                if request.display_name is not None:
                    record.display_name = self._normalize_display_name(request.display_name, record.username)
                if request.password is not None:
                    self._validate_password(request.password)
                    record.password_hash = _hash_password(request.password)
                if request.project_ids is not None:
                    record.project_ids_json = list(
                        _normalize_string_collection(request.project_ids, field_name="project_ids")
                    )
                if request.scopes is not None:
                    record.scopes_json = list(_normalize_string_collection(request.scopes, field_name="scopes"))
                if request.is_active is not None:
                    record.is_active = request.is_active
                if request.metadata is not None:
                    record.metadata_json = dict(request.metadata)
                record.updated_at = _now_isoformat()
                session.commit()
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "更新本地用户失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return _user_from_record(record)

    def delete_user(self, user_id: str, *, actor_user_id: str | None = None) -> None:
        """删除一个本地用户，并清理关联会话、refresh token 和长期调用 token。"""

        self._require_local_auth_enabled()
        with self.session_factory.create_session() as session:
            try:
                user_record = session.get(LocalAuthUserRecord, user_id)
                if user_record is None:
                    raise ResourceNotFoundError("请求的本地用户不存在", details={"user_id": user_id})

                self._revoke_user_sessions(
                    session,
                    user_id=user_id,
                    revoked_at=_now_isoformat(),
                    reason="user-deleted",
                    actor_user_id=actor_user_id,
                )
                self._delete_user_sessions(session, user_id=user_id)
                self._delete_user_refresh_tokens(session, user_id=user_id)
                self._revoke_user_tokens(
                    session,
                    user_id=user_id,
                    revoked_at=_now_isoformat(),
                    reason="user-deleted",
                    actor_user_id=actor_user_id,
                )
                self._delete_user_tokens(session, user_id=user_id)
                session.delete(user_record)
                session.commit()
                self._flush_pending_auth_events(session)
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "删除本地用户失败",
                    details={"error_type": error.__class__.__name__},
                ) from error

    def reset_user_password(
        self,
        user_id: str,
        request: LocalAuthPasswordResetRequest,
        *,
        actor_user_id: str | None = None,
    ) -> LocalAuthUser:
        """重置一个本地用户的密码，并按请求撤销现有凭据。"""

        self._require_local_auth_enabled()
        self._validate_password(request.new_password)
        now = _now_isoformat()
        with self.session_factory.create_session() as session:
            try:
                user_record = session.get(LocalAuthUserRecord, user_id)
                if user_record is None:
                    raise ResourceNotFoundError("请求的本地用户不存在", details={"user_id": user_id})
                user_record.password_hash = _hash_password(request.new_password)
                user_record.updated_at = now
                if request.revoke_sessions:
                    self._revoke_user_sessions(
                        session,
                        user_id=user_id,
                        revoked_at=now,
                        reason="password-reset",
                        actor_user_id=actor_user_id,
                    )
                    self._revoke_user_refresh_tokens(session, user_id=user_id, revoked_at=now)
                if request.revoke_user_tokens:
                    self._revoke_user_tokens(
                        session,
                        user_id=user_id,
                        revoked_at=now,
                        reason="password-reset",
                        actor_user_id=actor_user_id,
                    )
                session.commit()
                self._flush_pending_auth_events(session)
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "重置本地用户密码失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return _user_from_record(user_record)

    def list_user_tokens(self, user_id: str) -> tuple[LocalAuthUserToken, ...]:
        """列出一个本地用户的长期调用 token。"""

        self._require_local_auth_enabled()
        self.get_user(user_id)
        with self.session_factory.create_session() as session:
            try:
                token_records = session.execute(
                    select(LocalAuthUserTokenRecord)
                    .where(LocalAuthUserTokenRecord.user_id == user_id)
                    .order_by(
                        LocalAuthUserTokenRecord.created_at.desc(),
                        LocalAuthUserTokenRecord.token_id.desc(),
                    )
                ).scalars().all()
            except SQLAlchemyError as error:
                raise PersistenceOperationError(
                    "列出本地 user token 失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return tuple(_user_token_from_record(record) for record in token_records)

    def create_user_token(
        self,
        user_id: str,
        request: LocalAuthUserTokenCreateRequest,
        *,
        created_by_user_id: str | None = None,
    ) -> LocalAuthIssuedUserToken:
        """为一个本地用户创建长期调用 token。"""

        self._require_local_auth_enabled()
        with self.session_factory.create_session() as session:
            try:
                user_record = session.get(LocalAuthUserRecord, user_id)
                if user_record is None:
                    raise ResourceNotFoundError("请求的本地用户不存在", details={"user_id": user_id})
                issued_token = self._issue_user_token(
                    session=session,
                    user_record=user_record,
                    request=request,
                    created_by_user_id=created_by_user_id,
                )
                session.commit()
                self._flush_pending_auth_events(session)
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "创建本地 user token 失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return issued_token

    def initialize_default_user_if_empty(
        self,
        request: LocalAuthInitializeDefaultUserRequest,
    ) -> LocalAuthUser | None:
        """仅在本地用户表为空时初始化默认本地用户与长期调用 token。"""

        self._require_local_auth_enabled()
        username = self._normalize_username(request.username)
        display_name = self._normalize_display_name(request.display_name, username)
        principal_type = self._normalize_principal_type(request.principal_type)
        token_name = self._normalize_token_name(request.user_token_name)
        self._validate_password(request.password)
        project_ids = _normalize_string_collection(request.project_ids, field_name="project_ids")
        scopes = _normalize_string_collection(request.scopes, field_name="scopes")
        user_metadata = _build_local_provider_metadata(request.metadata)
        token_metadata = dict(request.user_token_metadata)
        token_hash = _hash_token(request.user_token)
        now = _now_isoformat()

        with self.session_factory.create_session() as session:
            try:
                user_count = session.execute(select(func.count()).select_from(LocalAuthUserRecord)).scalar_one()
                if user_count:
                    session.rollback()
                    return None

                duplicate_token_record = session.execute(
                    select(LocalAuthUserTokenRecord).where(LocalAuthUserTokenRecord.token_hash == token_hash)
                ).scalar_one_or_none()
                if duplicate_token_record is not None:
                    raise InvalidRequestError(
                        "默认长期调用 token 与现有 token 冲突",
                        details={"token_name": token_name},
                    )

                user_record = LocalAuthUserRecord(
                    user_id=_build_user_id(),
                    provider_kind="local",
                    provider_subject=username.casefold(),
                    username=username,
                    display_name=display_name,
                    principal_type=principal_type,
                    password_hash=_hash_password(request.password),
                    is_active=True,
                    project_ids_json=list(project_ids),
                    scopes_json=list(scopes),
                    created_at=now,
                    updated_at=now,
                    last_login_at=None,
                    metadata_json=user_metadata,
                )
                session.add(user_record)

                token_record = LocalAuthUserTokenRecord(
                    token_id=_build_user_token_id(),
                    user_id=user_record.user_id,
                    token_name=token_name,
                    token_hash=token_hash,
                    created_at=now,
                    expires_at=None,
                    last_used_at=None,
                    revoked_at=None,
                    created_by_user_id=None,
                    metadata_json=token_metadata,
                )
                session.add(token_record)

                session.commit()
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "初始化默认本地用户失败",
                    details={"error_type": error.__class__.__name__},
                ) from error

        return _user_from_record(user_record)

    def revoke_user_token(
        self,
        user_id: str,
        token_id: str,
        *,
        actor_user_id: str | None = None,
    ) -> bool:
        """撤销一个长期调用 user token。"""

        self._require_local_auth_enabled()
        now = _now_isoformat()
        with self.session_factory.create_session() as session:
            try:
                token_record = session.get(LocalAuthUserTokenRecord, token_id)
                if token_record is None or token_record.user_id != user_id:
                    return False
                if token_record.revoked_at is not None:
                    return False
                token_record.revoked_at = now
                token_record.last_used_at = now
                user_record = session.get(LocalAuthUserRecord, token_record.user_id)
                self._publish_auth_event(
                    session=session,
                    event_type="auth.user-tokens.revoked",
                    occurred_at=now,
                    user_record=user_record,
                    user_id=token_record.user_id,
                    actor_user_id=actor_user_id,
                    principal_type=None if user_record is None else user_record.principal_type,
                    credential_kind="user-token",
                    credential_id=token_record.token_id,
                    payload={
                        "token_name": token_record.token_name,
                        "revocation_reason": "manual-revoke",
                    },
                )
                session.commit()
                self._flush_pending_auth_events(session)
            except SQLAlchemyError as error:
                session.rollback()
                raise PersistenceOperationError(
                    "撤销本地 user token 失败",
                    details={"error_type": error.__class__.__name__},
                ) from error
        return True

    def _issue_session(
        self,
        *,
        session: Session,
        user_record: LocalAuthUserRecord,
        auth_source: str,
    ) -> LocalAuthSessionResult:
        """为指定用户签发一个新的登录会话和 refresh token。"""

        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        now = _now_isoformat()
        session_id = _build_session_id()
        refresh_token_id = _build_refresh_token_id()
        access_expires_at = _future_isoformat(
            hours=self.settings.auth.local_auth.resolve_session_access_token_ttl_hours()
        )
        refresh_expires_at = _future_isoformat(hours=self.settings.auth.local_auth.refresh_token_ttl_hours)
        session.add(
            LocalAuthSessionRecord(
                session_id=session_id,
                user_id=user_record.user_id,
                token_hash=_hash_token(access_token),
                created_at=now,
                expires_at=access_expires_at,
                last_used_at=now,
                revoked_at=None,
                metadata_json={"auth_source": auth_source},
            )
        )
        session.add(
            LocalAuthRefreshTokenRecord(
                refresh_token_id=refresh_token_id,
                session_id=session_id,
                user_id=user_record.user_id,
                token_hash=_hash_token(refresh_token),
                created_at=now,
                expires_at=refresh_expires_at,
                last_used_at=now,
                revoked_at=None,
                metadata_json={"auth_source": auth_source},
            )
        )
        self._publish_auth_event(
            session=session,
            event_type="auth.sessions.issued",
            occurred_at=now,
            user_record=user_record,
            user_id=user_record.user_id,
            actor_user_id=user_record.user_id,
            principal_type=user_record.principal_type,
            credential_kind="session",
            credential_id=session_id,
            payload={
                "session_id": session_id,
                "auth_source": auth_source,
                "access_expires_at": access_expires_at,
                "refresh_token_id": refresh_token_id,
                "refresh_expires_at": refresh_expires_at,
            },
        )
        return LocalAuthSessionResult(
            session_id=session_id,
            access_token=access_token,
            access_expires_at=access_expires_at,
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expires_at,
            user=_user_from_record(user_record),
        )

    def _issue_user_token(
        self,
        *,
        session: Session,
        user_record: LocalAuthUserRecord,
        request: LocalAuthUserTokenCreateRequest,
        created_by_user_id: str | None,
    ) -> LocalAuthIssuedUserToken:
        """为指定用户签发一个长期调用 token。"""

        token_name = self._normalize_token_name(request.token_name)
        existing_token = session.execute(
            select(LocalAuthUserTokenRecord).where(
                LocalAuthUserTokenRecord.user_id == user_record.user_id,
                LocalAuthUserTokenRecord.token_name == token_name,
            )
        ).scalar_one_or_none()
        if existing_token is not None:
            raise InvalidRequestError(
                "token_name 已存在",
                details={"user_id": user_record.user_id, "token_name": token_name},
            )
        token = secrets.token_urlsafe(32)
        now = _now_isoformat()
        expires_at = self._resolve_token_expiry(
            ttl_hours=request.ttl_hours,
            expires_at=request.expires_at,
            default_ttl_hours=self.settings.auth.local_auth.user_token_default_ttl_hours,
            field_prefix="user_token",
        )
        token_record = LocalAuthUserTokenRecord(
            token_id=_build_user_token_id(),
            user_id=user_record.user_id,
            token_name=token_name,
            token_hash=_hash_token(token),
            created_at=now,
            expires_at=expires_at,
            last_used_at=None,
            revoked_at=None,
            created_by_user_id=created_by_user_id,
            metadata_json=dict(request.metadata),
        )
        session.add(token_record)
        self._publish_auth_event(
            session=session,
            event_type="auth.user-tokens.issued",
            occurred_at=now,
            user_record=user_record,
            user_id=user_record.user_id,
            actor_user_id=created_by_user_id,
            principal_type=user_record.principal_type,
            credential_kind="user-token",
            credential_id=token_record.token_id,
            payload={
                "token_name": token_name,
                "expires_at": expires_at,
            },
        )
        return LocalAuthIssuedUserToken(
            token=token,
            user_token=_user_token_from_record(token_record),
        )

    def _resolve_session_record(
        self,
        *,
        session: Session,
        session_record: LocalAuthSessionRecord,
        revoked_at: str,
    ) -> LocalAuthResolvedCredential | None:
        """把 session access token 记录解析为主体。"""

        if session_record.revoked_at is not None:
            return None
        if _is_expired(session_record.expires_at):
            self._revoke_session_record(
                session,
                session_record.session_id,
                revoked_at=revoked_at,
                reason="expired",
                actor_user_id=None,
            )
            self._revoke_refresh_tokens_for_session(session, session_record.session_id, revoked_at=revoked_at)
            return None
        user_record = session.get(LocalAuthUserRecord, session_record.user_id)
        if user_record is None or not user_record.is_active:
            self._revoke_session_record(
                session,
                session_record.session_id,
                revoked_at=revoked_at,
                reason="user-inactive",
                actor_user_id=None,
            )
            self._revoke_refresh_tokens_for_session(session, session_record.session_id, revoked_at=revoked_at)
            return None
        session_record.last_used_at = revoked_at
        return LocalAuthResolvedCredential(
            credential_kind="session",
            credential_id=session_record.session_id,
            credential_name=None,
            expires_at=session_record.expires_at,
            user=_user_from_record(user_record),
        )

    def _resolve_user_token_record(
        self,
        *,
        session: Session,
        user_token_record: LocalAuthUserTokenRecord,
        revoked_at: str,
    ) -> LocalAuthResolvedCredential | None:
        """把长期调用 token 记录解析为主体。"""

        if user_token_record.revoked_at is not None:
            return None
        if _is_expired(user_token_record.expires_at):
            user_token_record.revoked_at = revoked_at
            self._publish_auth_event(
                session=session,
                event_type="auth.user-tokens.revoked",
                occurred_at=revoked_at,
                user_record=None,
                user_id=user_token_record.user_id,
                actor_user_id=None,
                principal_type=None,
                credential_kind="user-token",
                credential_id=user_token_record.token_id,
                payload={
                    "token_name": user_token_record.token_name,
                    "revocation_reason": "expired",
                },
            )
            return None
        user_record = session.get(LocalAuthUserRecord, user_token_record.user_id)
        if user_record is None or not user_record.is_active:
            user_token_record.revoked_at = revoked_at
            self._publish_auth_event(
                session=session,
                event_type="auth.user-tokens.revoked",
                occurred_at=revoked_at,
                user_record=user_record,
                user_id=user_token_record.user_id,
                actor_user_id=None,
                principal_type=None if user_record is None else user_record.principal_type,
                credential_kind="user-token",
                credential_id=user_token_record.token_id,
                payload={
                    "token_name": user_token_record.token_name,
                    "revocation_reason": "user-inactive",
                },
            )
            return None
        user_token_record.last_used_at = revoked_at
        return LocalAuthResolvedCredential(
            credential_kind="user-token",
            credential_id=user_token_record.token_id,
            credential_name=user_token_record.token_name,
            expires_at=user_token_record.expires_at,
            user=_user_from_record(user_record),
        )

    def _revoke_session_record(
        self,
        session: Session,
        session_id: str,
        *,
        revoked_at: str,
        reason: str,
        actor_user_id: str | None,
    ) -> None:
        """撤销一条登录会话 access token 记录。"""

        session_record = session.get(LocalAuthSessionRecord, session_id)
        if session_record is None or session_record.revoked_at is not None:
            return
        session_record.revoked_at = revoked_at
        session_record.last_used_at = revoked_at
        user_record = session.get(LocalAuthUserRecord, session_record.user_id)
        self._publish_auth_event(
            session=session,
            event_type="auth.sessions.revoked",
            occurred_at=revoked_at,
            user_record=user_record,
            user_id=session_record.user_id,
            actor_user_id=actor_user_id,
            principal_type=None if user_record is None else user_record.principal_type,
            credential_kind="session",
            credential_id=session_id,
            payload={
                "session_id": session_id,
                "revocation_reason": reason,
                "expires_at": session_record.expires_at,
            },
        )

    def _revoke_refresh_tokens_for_session(self, session: Session, session_id: str, *, revoked_at: str) -> None:
        """撤销一条登录会话关联的全部 refresh token。"""

        refresh_records = session.execute(
            select(LocalAuthRefreshTokenRecord).where(LocalAuthRefreshTokenRecord.session_id == session_id)
        ).scalars().all()
        for refresh_record in refresh_records:
            if refresh_record.revoked_at is not None:
                continue
            refresh_record.revoked_at = revoked_at
            refresh_record.last_used_at = revoked_at

    def _revoke_user_sessions(
        self,
        session: Session,
        *,
        user_id: str,
        revoked_at: str,
        reason: str,
        actor_user_id: str | None,
    ) -> None:
        """撤销一个用户的全部登录会话。"""

        session_records = session.execute(
            select(LocalAuthSessionRecord).where(LocalAuthSessionRecord.user_id == user_id)
        ).scalars().all()
        for session_record in session_records:
            if session_record.revoked_at is not None:
                continue
            self._revoke_session_record(
                session,
                session_record.session_id,
                revoked_at=revoked_at,
                reason=reason,
                actor_user_id=actor_user_id,
            )

    def _revoke_user_refresh_tokens(self, session: Session, *, user_id: str, revoked_at: str) -> None:
        """撤销一个用户的全部 refresh token。"""

        refresh_records = session.execute(
            select(LocalAuthRefreshTokenRecord).where(LocalAuthRefreshTokenRecord.user_id == user_id)
        ).scalars().all()
        for refresh_record in refresh_records:
            if refresh_record.revoked_at is not None:
                continue
            refresh_record.revoked_at = revoked_at
            refresh_record.last_used_at = revoked_at

    def _revoke_user_tokens(
        self,
        session: Session,
        *,
        user_id: str,
        revoked_at: str,
        reason: str,
        actor_user_id: str | None,
    ) -> None:
        """撤销一个用户的全部长期调用 token。"""

        user_token_records = session.execute(
            select(LocalAuthUserTokenRecord).where(LocalAuthUserTokenRecord.user_id == user_id)
        ).scalars().all()
        for user_token_record in user_token_records:
            if user_token_record.revoked_at is not None:
                continue
            user_token_record.revoked_at = revoked_at
            user_token_record.last_used_at = revoked_at
            user_record = session.get(LocalAuthUserRecord, user_token_record.user_id)
            self._publish_auth_event(
                session=session,
                event_type="auth.user-tokens.revoked",
                occurred_at=revoked_at,
                user_record=user_record,
                user_id=user_token_record.user_id,
                actor_user_id=actor_user_id,
                principal_type=None if user_record is None else user_record.principal_type,
                credential_kind="user-token",
                credential_id=user_token_record.token_id,
                payload={
                    "token_name": user_token_record.token_name,
                    "revocation_reason": reason,
                },
            )

    def _delete_user_sessions(self, session: Session, *, user_id: str) -> None:
        """删除一个用户的全部登录会话记录。"""

        session_records = session.execute(
            select(LocalAuthSessionRecord).where(LocalAuthSessionRecord.user_id == user_id)
        ).scalars().all()
        for session_record in session_records:
            session.delete(session_record)

    def _delete_user_refresh_tokens(self, session: Session, *, user_id: str) -> None:
        """删除一个用户的全部 refresh token 记录。"""

        refresh_records = session.execute(
            select(LocalAuthRefreshTokenRecord).where(LocalAuthRefreshTokenRecord.user_id == user_id)
        ).scalars().all()
        for refresh_record in refresh_records:
            session.delete(refresh_record)

    def _delete_user_tokens(self, session: Session, *, user_id: str) -> None:
        """删除一个用户的全部长期调用 token 记录。"""

        user_token_records = session.execute(
            select(LocalAuthUserTokenRecord).where(LocalAuthUserTokenRecord.user_id == user_id)
        ).scalars().all()
        for user_token_record in user_token_records:
            session.delete(user_token_record)

    def _require_local_auth_enabled(self) -> None:
        """要求当前服务已启用本地用户鉴权。"""

        if not self.settings.auth.local_auth.enabled:
            raise InvalidRequestError("当前服务未启用本地用户与登录功能")

    def _local_bearer_auth_enabled(self) -> bool:
        """判断当前是否允许本地 Bearer token 解析。"""

        return self.settings.auth.local_session_auth_enabled()

    def _normalize_username(self, username: str) -> str:
        """校验并规范化用户名。"""

        normalized_username = username.strip()
        if not _USERNAME_PATTERN.fullmatch(normalized_username):
            raise InvalidRequestError(
                "username 格式不合法，只允许字母、数字、点、下划线、减号和 @，长度 3-64",
                details={"username": username},
            )
        return normalized_username

    def _normalize_display_name(self, display_name: str | None, fallback_username: str) -> str:
        """规范化展示名称。"""

        if display_name is None or not display_name.strip():
            return fallback_username
        return display_name.strip()

    def _normalize_principal_type(self, principal_type: str) -> str:
        """规范化 principal_type。"""

        normalized_principal_type = principal_type.strip()
        if not normalized_principal_type:
            raise InvalidRequestError("principal_type 不能为空")
        return normalized_principal_type

    def _normalize_token_name(self, token_name: str) -> str:
        """校验并规范化长期调用 token 的名称。"""

        normalized_token_name = token_name.strip()
        if not _TOKEN_NAME_PATTERN.fullmatch(normalized_token_name):
            raise InvalidRequestError(
                "token_name 格式不合法，只允许字母、数字、点、下划线、减号和 @，长度 1-128",
                details={"token_name": token_name},
            )
        return normalized_token_name

    def _validate_password(self, password: str) -> None:
        """校验本地密码复杂度下界。"""

        if len(password) < self.settings.auth.local_auth.password_min_length:
            raise InvalidRequestError(
                "password 长度不足",
                details={"password_min_length": self.settings.auth.local_auth.password_min_length},
            )

    def _resolve_token_expiry(
        self,
        *,
        ttl_hours: int | None,
        expires_at: str | None,
        default_ttl_hours: int,
        field_prefix: str,
    ) -> str | None:
        """根据 ttl 或显式 expires_at 解析 token 过期时间。"""

        if ttl_hours is not None and expires_at is not None:
            raise InvalidRequestError(
                f"{field_prefix} 不能同时提供 ttl_hours 和 expires_at",
                details={"field_prefix": field_prefix},
            )
        if expires_at is not None:
            expires_at_datetime = _parse_iso_datetime(expires_at, field_name=f"{field_prefix}.expires_at")
            if expires_at_datetime <= datetime.now(timezone.utc):
                raise InvalidRequestError(
                    f"{field_prefix}.expires_at 必须晚于当前时间",
                    details={"expires_at": expires_at},
                )
            return expires_at_datetime.isoformat()
        effective_ttl_hours = default_ttl_hours if ttl_hours is None else ttl_hours
        return _future_isoformat(hours=effective_ttl_hours)

    def _publish_auth_event(
        self,
        *,
        session: Session,
        event_type: str,
        occurred_at: str,
        user_record: LocalAuthUserRecord | None,
        user_id: str | None,
        actor_user_id: str | None,
        principal_type: str | None,
        credential_kind: str | None,
        credential_id: str | None,
        payload: dict[str, object] | None = None,
    ) -> None:
        """把一条 auth 审计事件挂到当前 Session，等待 commit 成功后统一发布。"""

        if self.service_event_bus is None:
            return

        provider_kind = _LOCAL_PROVIDER_ID if user_record is None else user_record.provider_kind
        provider_id = _LOCAL_PROVIDER_ID
        if user_record is not None:
            provider_metadata = dict(user_record.metadata_json or {})
            provider_id = str(provider_metadata.get("provider_id") or provider_kind or _LOCAL_PROVIDER_ID)

        pending_auth_events = session.info.setdefault("pending_auth_events", [])
        pending_auth_events.append(
            build_auth_service_event(
                event_type=event_type,
                occurred_at=occurred_at,
                provider_id=provider_id,
                provider_kind=provider_kind,
                user_id=user_id,
                actor_user_id=actor_user_id,
                principal_type=principal_type,
                credential_kind=credential_kind,
                credential_id=credential_id,
                payload=payload,
            )
        )

    def _flush_pending_auth_events(self, session: Session) -> None:
        """在数据库事务成功提交后统一发布挂起的 auth 审计事件。"""

        if self.service_event_bus is None:
            return
        pending_auth_events = session.info.pop("pending_auth_events", [])
        for event in pending_auth_events:
            self.service_event_bus.publish(event)


def _user_from_record(record: LocalAuthUserRecord) -> LocalAuthUser:
    """把 ORM 用户记录转换为应用层用户对象。"""

    metadata = dict(record.metadata_json or {})
    metadata.setdefault("provider_id", record.provider_kind or _LOCAL_PROVIDER_ID)
    return LocalAuthUser(
        user_id=record.user_id,
        provider_kind=record.provider_kind,
        username=record.username,
        display_name=record.display_name,
        principal_type=record.principal_type,
        project_ids=tuple(record.project_ids_json or []),
        scopes=tuple(record.scopes_json or []),
        is_active=record.is_active,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_login_at=record.last_login_at,
        metadata=metadata,
    )


def _build_local_provider_metadata(metadata: dict[str, object]) -> dict[str, object]:
    """补齐 local provider 约定元数据。"""

    normalized_metadata = dict(metadata)
    normalized_metadata.setdefault("provider_id", _LOCAL_PROVIDER_ID)
    return normalized_metadata


def _user_token_from_record(record: LocalAuthUserTokenRecord) -> LocalAuthUserToken:
    """把 ORM user token 记录转换为应用层摘要对象。"""

    return LocalAuthUserToken(
        token_id=record.token_id,
        user_id=record.user_id,
        token_name=record.token_name,
        created_at=record.created_at,
        expires_at=record.expires_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
        created_by_user_id=record.created_by_user_id,
        metadata=dict(record.metadata_json or {}),
    )


def _normalize_string_collection(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    """规范化字符串集合，保留顺序并去重。"""

    normalized_items: list[str] = []
    seen_items: set[str] = set()
    for item in values:
        normalized_item = item.strip()
        if not normalized_item:
            raise InvalidRequestError(f"{field_name} 中不能包含空字符串")
        if normalized_item in seen_items:
            continue
        normalized_items.append(normalized_item)
        seen_items.add(normalized_item)
    return tuple(normalized_items)


def _hash_password(password: str) -> str:
    """按 PBKDF2 生成密码摘要。"""

    salt_hex = secrets.token_hex(16)
    digest_hex = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        _PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"{_PASSWORD_HASH_ALGORITHM}${_PASSWORD_HASH_ITERATIONS}${salt_hex}${digest_hex}"


def _verify_password(password: str, password_hash: str) -> bool:
    """校验密码是否匹配 PBKDF2 摘要。"""

    try:
        algorithm, iterations_text, salt_hex, digest_hex = password_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != _PASSWORD_HASH_ALGORITHM:
        return False
    try:
        iterations = int(iterations_text)
    except ValueError:
        return False
    candidate_digest_hex = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        iterations,
    ).hex()
    return hmac.compare_digest(candidate_digest_hex, digest_hex)


def _hash_token(token: str) -> str:
    """生成 Bearer token 的持久化摘要。"""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _build_user_id() -> str:
    """生成稳定的本地用户 id。"""

    return f"user-{secrets.token_hex(16)}"


def _build_session_id() -> str:
    """生成稳定的登录会话 id。"""

    return f"session-{secrets.token_hex(16)}"


def _build_refresh_token_id() -> str:
    """生成稳定的 refresh token 记录 id。"""

    return f"refresh-token-{secrets.token_hex(16)}"


def _build_user_token_id() -> str:
    """生成稳定的长期调用 token id。"""

    return f"user-token-{secrets.token_hex(16)}"


def _now_isoformat() -> str:
    """返回当前 UTC 时间的 ISO8601 文本。"""

    return datetime.now(timezone.utc).isoformat()


def _future_isoformat(*, hours: int) -> str | None:
    """按小时数计算未来过期时间。"""

    if hours <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _is_expired(expires_at: str | None) -> bool:
    """判断 token 是否已过期。"""

    if expires_at is None:
        return False
    return _parse_iso_datetime(expires_at, field_name="expires_at") <= datetime.now(timezone.utc)


def _parse_iso_datetime(value: str, *, field_name: str) -> datetime:
    """解析 ISO8601 时间文本。"""

    try:
        parsed_datetime = datetime.fromisoformat(value)
    except ValueError as error:
        raise InvalidRequestError(
            f"{field_name} 不是合法的 ISO8601 时间",
            details={field_name: value},
        ) from error
    if parsed_datetime.tzinfo is None:
        parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
    return parsed_datetime.astimezone(timezone.utc)