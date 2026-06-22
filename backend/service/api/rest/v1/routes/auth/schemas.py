"""auth 路由请求和响应 schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LocalAuthUserContract(BaseModel):
    """描述本地用户的公开返回结构。"""

    user_id: str
    provider_kind: str
    username: str
    display_name: str
    principal_type: str
    project_ids: list[str] = Field(default_factory=list, description="Project 可见范围列表；为空表示全部 Project")
    scopes: list[str] = Field(default_factory=list)
    is_active: bool
    created_at: str
    updated_at: str
    last_login_at: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class AuthProviderContract(BaseModel):
    """描述公开可发现的账号 provider 目录项。"""

    provider_id: str
    provider_kind: str
    display_name: str
    enabled: bool
    login_mode: str
    supports_password_login: bool
    supports_refresh: bool
    supports_bootstrap_admin: bool
    supports_user_management: bool
    supports_long_lived_tokens: bool
    issuer_url: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class LocalAuthSessionContract(BaseModel):
    """描述本地登录、bootstrap 与 refresh 的返回结构。"""

    session_id: str
    access_token: str
    token_type: str = "bearer"
    expires_at: str | None = None
    refresh_token: str
    refresh_expires_at: str | None = None
    user: LocalAuthUserContract


class LocalAuthUserTokenContract(BaseModel):
    """描述长期调用 user token 的公开摘要结构。"""

    token_id: str
    user_id: str
    token_name: str
    created_at: str
    expires_at: str | None = None
    last_used_at: str | None = None
    revoked_at: str | None = None
    created_by_user_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class LocalAuthIssuedUserTokenContract(LocalAuthUserTokenContract):
    """描述新签发 user token 的一次性返回结构。"""

    token: str
    token_type: str = "bearer"


class LocalAuthUserCreateContract(BaseModel):
    """描述本地用户创建返回结构。"""

    user: LocalAuthUserContract
    initial_user_token: LocalAuthIssuedUserTokenContract | None = None


class LocalAuthBootstrapAdminRequestBody(BaseModel):
    """描述 bootstrap 管理员请求体。"""

    username: str = Field(description="用户名")
    password: str = Field(description="密码")
    display_name: str | None = Field(default=None, description="可选展示名称")


class LocalAuthLoginRequestBody(BaseModel):
    """描述本地登录请求体。"""

    provider_id: str = Field(default="local", description="账号 provider 标识")
    username: str = Field(description="用户名")
    password: str = Field(description="密码")


class LocalAuthRefreshRequestBody(BaseModel):
    """描述 refresh token 刷新请求体。"""

    refresh_token: str = Field(description="登录返回的 refresh token")


class LocalAuthInitialUserTokenRequestBody(BaseModel):
    """描述创建用户时默认长期调用 token 的请求体。"""

    enabled: bool = Field(default=True, description="是否在创建用户时默认签发长期调用 token")
    token_name: str = Field(default="default", description="token 名称")
    ttl_hours: int | None = Field(default=None, description="相对有效期小时数")
    expires_at: str | None = Field(default=None, description="显式过期时间，ISO8601")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class LocalAuthUserTokenCreateRequestBody(BaseModel):
    """描述长期调用 user token 创建请求体。"""

    token_name: str = Field(default="default", description="token 名称")
    ttl_hours: int | None = Field(default=None, description="相对有效期小时数")
    expires_at: str | None = Field(default=None, description="显式过期时间，ISO8601")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class LocalAuthUserCreateRequestBody(BaseModel):
    """描述本地用户创建请求体。"""

    username: str = Field(description="用户名")
    password: str = Field(description="密码")
    display_name: str | None = Field(default=None, description="展示名称")
    principal_type: str = Field(default="user", description="主体类型")
    project_ids: list[str] = Field(default_factory=list, description="Project 可见范围列表；为空表示全部 Project")
    scopes: list[str] = Field(default_factory=list, description="当前用户持有的 scopes")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    initial_user_token: LocalAuthInitialUserTokenRequestBody | None = Field(
        default_factory=LocalAuthInitialUserTokenRequestBody,
        description="创建用户时的默认长期调用 token 配置；传 null 或 enabled=false 可关闭默认签发",
    )


class LocalAuthUserUpdateRequestBody(BaseModel):
    """描述本地用户更新请求体。"""

    display_name: str | None = Field(default=None, description="展示名称")
    password: str | None = Field(default=None, description="新密码")
    project_ids: list[str] | None = Field(default=None, description="Project 可见范围列表；为空表示全部 Project")
    scopes: list[str] | None = Field(default=None, description="当前用户持有的 scopes")
    is_active: bool | None = Field(default=None, description="是否启用")
    metadata: dict[str, object] | None = Field(default=None, description="附加元数据")


class LocalAuthPasswordResetRequestBody(BaseModel):
    """描述本地用户密码重置请求体。"""

    new_password: str = Field(description="新密码")
    revoke_sessions: bool = Field(default=True, description="是否同时撤销全部登录会话与 refresh token")
    revoke_user_tokens: bool = Field(default=False, description="是否同时撤销全部长期调用 token")

