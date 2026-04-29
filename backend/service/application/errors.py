"""service application 通用错误定义。"""

from __future__ import annotations

from collections.abc import Mapping


class ServiceError(Exception):
    """描述可被 API 层稳定映射的服务错误。

    属性：
    - code：稳定错误码。
    - message：对外可见的错误消息。
    - status_code：对应的 HTTP 状态码。
    - details：附加错误细节。
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化服务错误。

        参数：
        - message：错误消息。
        - code：稳定错误码。
        - status_code：HTTP 状态码。
        - details：附加错误细节。
        """

        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})


class AuthenticationRequiredError(ServiceError):
    """表示当前请求缺少有效身份。"""

    def __init__(self, message: str = "当前请求未通过鉴权") -> None:
        """初始化鉴权失败错误。

        参数：
        - message：错误消息。
        """

        super().__init__(message, code="authentication_required", status_code=401)


class PermissionDeniedError(ServiceError):
    """表示当前主体没有足够权限。"""

    def __init__(
        self,
        message: str = "当前主体没有执行该操作的权限",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化权限不足错误。

        参数：
        - message：错误消息。
        - details：附加错误细节。
        """

        super().__init__(message, code="permission_denied", status_code=403, details=details)


class ServiceConfigurationError(ServiceError):
    """表示服务运行时配置不完整或不合法。"""

    def __init__(
        self,
        message: str = "服务配置不完整",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化服务配置错误。

        参数：
        - message：错误消息。
        - details：附加错误细节。
        """

        super().__init__(message, code="service_configuration_error", status_code=500, details=details)


class PersistenceOperationError(ServiceError):
    """表示数据库或持久化操作失败。"""

    def __init__(
        self,
        message: str = "持久化操作失败",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化持久化错误。

        参数：
        - message：错误消息。
        - details：附加错误细节。
        """

        super().__init__(message, code="persistence_operation_error", status_code=503, details=details)


class InvalidRequestError(ServiceError):
    """表示当前请求内容不合法。"""

    def __init__(
        self,
        message: str = "请求内容不合法",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化请求内容错误。

        参数：
        - message：错误消息。
        - details：附加错误细节。
        """

        super().__init__(message, code="invalid_request", status_code=400, details=details)


class UnsupportedDatasetFormatError(ServiceError):
    """表示当前数据集格式暂不支持。"""

    def __init__(
        self,
        message: str = "当前数据集格式暂不支持",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化不支持的数据集格式错误。

        参数：
        - message：错误消息。
        - details：附加错误细节。
        """

        super().__init__(message, code="unsupported_dataset_format", status_code=422, details=details)