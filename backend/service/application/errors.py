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


class WorkflowRecoveryRequiredError(ServiceError):
    """表示 Workflow 权威文件需要在启动恢复完成前保持写入 claim。"""

    def __init__(
        self,
        message: str = "Workflow 持久化恢复尚未完成",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化需要启动恢复的持久化错误。"""

        super().__init__(
            message,
            code="workflow_recovery_required",
            status_code=503,
            details=details,
        )


class ConversionPublicationRecoveryRequiredError(ServiceError):
    """表示 Conversion 已进入不可失败化的 publication 恢复边界。"""

    def __init__(
        self,
        message: str = "Conversion publication 需要由当前或后续 lease 恢复",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化 publication 恢复错误。"""

        super().__init__(
            message,
            code="conversion_publication_recovery_required",
            status_code=503,
            details=details,
        )


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


class EphemeralImageRefInJsonResultError(ServiceError):
    """表示普通 JSON binding 中夹带了执行期临时图片引用。"""

    def __init__(
        self,
        message: str = "普通 JSON 结果不能包含执行期临时图片引用",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化稳定的结果契约错误。"""

        super().__init__(
            message,
            code="ephemeral_image_ref_in_json_result",
            status_code=400,
            details=details,
        )


class OperationTimeoutError(ServiceError):
    """表示一次同步操作在给定时限内未完成。"""

    def __init__(
        self,
        message: str = "操作执行超时",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化操作超时错误。

        参数：
        - message：错误消息。
        - details：附加错误细节。
        """

        super().__init__(message, code="operation_timeout", status_code=504, details=details)


class OperationCancelledError(ServiceError):
    """表示一次可取消操作已被取消。"""

    def __init__(
        self,
        message: str = "操作已取消",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化操作取消错误。

        参数：
        - message：错误消息。
        - details：附加错误细节。
        """

        super().__init__(message, code="operation_cancelled", status_code=409, details=details)


class ResourceInUseError(ServiceError):
    """表示请求删除或修改的资源仍被其他业务资源引用。"""

    def __init__(
        self,
        message: str = "资源仍在使用中",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化资源占用错误。

        参数：
        - message：错误消息。
        - details：附加错误细节。
        """

        super().__init__(message, code="resource_in_use", status_code=409, details=details)


class ResourceConflictError(ServiceError):
    """表示资源状态或乐观并发条件与请求不一致。"""

    def __init__(
        self,
        message: str = "资源状态已发生变化",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化资源冲突错误。"""

        super().__init__(message, code="resource_conflict", status_code=409, details=details)


class WorkflowRuntimeBusyError(ServiceError):
    """表示目标 Workflow Runtime 当前没有可用执行槽位。"""

    def __init__(
        self,
        message: str = "Workflow Runtime 当前正在执行其他请求",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化可稳定映射到 Trigger busy 响应的错误。"""

        super().__init__(
            message,
            code="workflow_runtime_busy",
            status_code=409,
            details=details,
        )


class WorkflowTriggerSourceBusyError(ServiceError):
    """表示同一 TriggerSource 已有一条尚未完成协议交付的请求。"""

    def __init__(
        self,
        message: str = "TriggerSource 当前已有在途请求",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化 TriggerSource 单在途容量错误。"""

        super().__init__(
            message,
            code="trigger_source_busy",
            status_code=409,
            details=details,
        )


class WorkflowTriggerExecutorBusyError(ServiceError):
    """表示 Workflow Trigger 有界执行器当前没有可用执行 permit。"""

    def __init__(
        self,
        message: str = "Workflow Trigger 执行器当前已满载",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化不排队的执行器容量错误。"""

        super().__init__(
            message,
            code="trigger_executor_busy",
            status_code=409,
            details=details,
        )


class ZeroMqTransportCapacityError(ServiceError):
    """表示 ZeroMQ 输出传输生命周期表当前没有可用容量。"""

    def __init__(
        self,
        message: str = "ZeroMQ 图片结果传输容量已满",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化发送前可稳定返回的容量错误。"""

        super().__init__(
            message,
            code="zeromq_transport_capacity_exhausted",
            status_code=409,
            details=details,
        )


class LocalBufferCapacityError(ServiceError):
    """表示 LocalBuffer arena 没有满足当前请求的连续容量。"""

    def __init__(
        self,
        message: str = "LocalBuffer 图片内存容量不足",
        *,
        contiguous: bool = False,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """保留总容量与连续容量两种稳定错误码。"""

        super().__init__(
            message,
            code=(
                "local_buffer_contiguous_capacity_exhausted"
                if contiguous
                else "local_buffer_capacity_exhausted"
            ),
            status_code=409,
            details=details,
        )


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


class ResourceNotFoundError(ServiceError):
    """表示请求的资源不存在。"""

    def __init__(
        self,
        message: str = "请求的资源不存在",
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """初始化资源不存在错误。

        参数：
        - message：错误消息。
        - details：附加错误细节。
        """

        super().__init__(message, code="resource_not_found", status_code=404, details=details)
