"""PLC Modbus TCP client 生命周期和错误翻译。"""

from __future__ import annotations

from backend.service.application.errors import OperationTimeoutError, ServiceError
from backend.service.infrastructure.integrations.modbus import (
    ModbusBitsReadResponse,
    ModbusRegistersReadResponse,
    ModbusTcpConnectionError,
    ModbusTcpDeviceError,
    ModbusTcpError,
    ModbusTcpProtocolError,
    ModbusTcpTimeoutError,
    ModbusWriteResponse,
    ProjectModbusTcpClient,
)
from custom_nodes.plc_modbus_tcp_nodes.backend.runtime.types import (
    ModbusConnectionConfig,
)


def _open_modbus_client(
    connection: ModbusConnectionConfig,
    *,
    node_name: str,
) -> _ModbusClientContext:
    """创建并连接一个同步 Modbus TCP client。"""

    client = ProjectModbusTcpClient(
        connection.host,
        port=connection.port,
        timeout=connection.timeout_seconds,
        retries=connection.retries,
    )
    try:
        if not client.connect():
            raise ServiceError(
                "Modbus TCP 连接失败",
                code="modbus_connection_failed",
                status_code=502,
                details={
                    "node_name": node_name,
                    "host": connection.host,
                    "port": connection.port,
                    "unit_id": connection.unit_id,
                },
            )
    except Exception as exc:  # pragma: no cover - 由统一错误翻译兜底
        try:
            _raise_as_service_error(exc=exc, node_name=node_name, connection=connection)
        finally:
            client.close()
    return _ModbusClientContext(client)


def _build_response_meta(
    response: ModbusBitsReadResponse
    | ModbusRegistersReadResponse
    | ModbusWriteResponse,
) -> dict[str, object]:
    """提取统一响应元数据。"""

    return {
        "dev_id": response.dev_id,
        "transaction_id": response.transaction_id,
        "function_code": response.function_code,
        "exception_code": response.exception_code,
        "retries": response.retries,
    }


def _raise_as_service_error(
    *,
    exc: Exception,
    node_name: str,
    connection: ModbusConnectionConfig,
) -> None:
    """把底层异常翻译为项目内错误。"""

    message = str(exc).strip() or exc.__class__.__name__
    if isinstance(exc, ModbusTcpTimeoutError):
        raise OperationTimeoutError(
            "Modbus TCP 设备响应超时",
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "error_message": message,
            },
        ) from exc
    if isinstance(exc, ModbusTcpConnectionError):
        raise ServiceError(
            "Modbus TCP 连接失败",
            code="modbus_connection_failed",
            status_code=502,
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "error_message": message,
            },
        ) from exc
    if isinstance(exc, ModbusTcpDeviceError):
        raise ServiceError(
            "Modbus TCP 设备返回异常响应",
            code="modbus_device_exception",
            status_code=502,
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "function_code": exc.function_code,
                "exception_code": exc.exception_code,
                "error_message": message,
            },
        ) from exc
    if isinstance(exc, ModbusTcpProtocolError):
        raise ServiceError(
            "Modbus TCP 响应报文非法",
            code="modbus_protocol_error",
            status_code=502,
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "error_message": message,
            },
        ) from exc
    if isinstance(exc, ModbusTcpError):
        raise ServiceError(
            "Modbus TCP 请求失败",
            code="modbus_request_failed",
            status_code=502,
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "error_message": message,
            },
        ) from exc
    if isinstance(exc, OSError):
        raise ServiceError(
            "Modbus TCP 套接字访问失败",
            code="modbus_socket_error",
            status_code=502,
            details={
                "node_name": node_name,
                "host": connection.host,
                "port": connection.port,
                "unit_id": connection.unit_id,
                "error_message": message,
            },
        ) from exc
    raise ServiceError(
        "Modbus TCP 节点执行失败",
        code="modbus_runtime_failed",
        status_code=500,
        details={
            "node_name": node_name,
            "host": connection.host,
            "port": connection.port,
            "unit_id": connection.unit_id,
            "error_type": exc.__class__.__name__,
            "error_message": message,
        },
    ) from exc


class _ModbusClientContext:
    """为 ProjectModbusTcpClient 提供统一 close 包装。"""

    def __init__(self, client: ProjectModbusTcpClient) -> None:
        self._client = client

    def __enter__(self) -> ProjectModbusTcpClient:
        return self._client

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._client.close()
