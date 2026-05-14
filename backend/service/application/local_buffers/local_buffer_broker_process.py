"""LocalBufferBroker 独立进程入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.contracts.buffers import BufferLease, BufferRef, FrameRef
from backend.service.application.errors import InvalidRequestError, ServiceError, ServiceConfigurationError
from backend.service.application.local_buffers.broker_settings import LocalBufferBrokerSettings
from backend.service.infrastructure.local_buffers import MmapBufferPool, MmapBufferPoolConfig


@dataclass
class LocalBufferBrokerRegistry:
    """把多个 MmapBufferPool 收敛为 broker 管理的 registry。

    字段：
    - settings：broker 进程启动配置。
    - broker_epoch：当前 broker 进程代次。
    """

    settings: LocalBufferBrokerSettings
    broker_epoch: str = field(default_factory=lambda: f"epoch-{uuid4().hex}")

    def __post_init__(self) -> None:
        """按配置创建全部 mmap pool。"""

        self._pools: dict[str, MmapBufferPool] = {}
        root_dir = Path(self.settings.root_dir).resolve()
        for pool_settings in self.settings.pools:
            pool_name = pool_settings.pool_name.strip()
            if not pool_name:
                raise InvalidRequestError("LocalBufferBroker pool_name 不能为空")
            if pool_name in self._pools:
                raise InvalidRequestError("LocalBufferBroker pool_name 重复", details={"pool_name": pool_name})
            self._pools[pool_name] = MmapBufferPool(
                MmapBufferPoolConfig(
                    pool_name=pool_name,
                    root_dir=root_dir / pool_name,
                    file_name=pool_settings.file_name,
                    file_size_bytes=pool_settings.file_size_bytes,
                    slot_size_bytes=pool_settings.slot_size_bytes,
                    broker_epoch=self.broker_epoch,
                )
            )
        if self.settings.default_pool_name not in self._pools:
            raise InvalidRequestError(
                "LocalBufferBroker default_pool_name 未出现在 pools 中",
                details={"default_pool_name": self.settings.default_pool_name},
            )

    def handle(self, message: object) -> dict[str, object]:
        """处理一条 broker 控制消息。"""

        if not isinstance(message, dict):
            raise InvalidRequestError("LocalBufferBroker 请求必须是对象")
        action = str(message.get("action") or "").strip()
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        if action == "status":
            return self._build_status()
        if action == "allocate-buffer":
            return self._handle_allocate_buffer(dict(payload))
        if action == "commit-buffer":
            return self._handle_commit_buffer(dict(payload))
        if action == "validate-buffer-ref":
            return self._handle_validate_buffer_ref(dict(payload))
        if action == "create-frame-channel":
            return self._handle_create_frame_channel(dict(payload))
        if action == "allocate-frame":
            return self._handle_allocate_frame(dict(payload))
        if action == "commit-frame":
            return self._handle_commit_frame(dict(payload))
        if action == "validate-frame-ref":
            return self._handle_validate_frame_ref(dict(payload))
        if action == "read-frame-ref":
            return self._handle_read_frame_ref(dict(payload))
        if action == "release":
            return self._handle_release(dict(payload))
        if action in {"release-owner", "release-by-owner"}:
            return self._handle_release_owner(dict(payload))
        if action == "expire-leases":
            return self._handle_expire_leases(dict(payload))
        if action == "shutdown":
            return {"state": "stopping", "process_id": os.getpid()}
        raise InvalidRequestError("LocalBufferBroker 收到未知控制动作", details={"action": action})

    def close(self) -> None:
        """关闭全部 mmap pool。"""

        for pool in self._pools.values():
            pool.close()

    def _handle_allocate_buffer(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 allocate-buffer 控制动作。"""

        pool = self._require_pool(_read_optional_str(payload, "pool_name") or self.settings.default_pool_name)
        lease = pool.allocate(
            size=_require_positive_int(payload, "size"),
            owner_kind=_require_str(payload, "owner_kind"),
            owner_id=_require_str(payload, "owner_id"),
            ttl_seconds=_read_optional_float(payload, "ttl_seconds"),
            trace_id=_read_optional_str(payload, "trace_id"),
        )
        return {"lease": lease.model_dump(mode="json")}

    def _handle_commit_buffer(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 commit-buffer 控制动作。"""

        lease_payload = payload.get("lease")
        if not isinstance(lease_payload, dict):
            raise InvalidRequestError("LocalBufferBroker commit-buffer 缺少 lease")
        lease = BufferLease.model_validate(lease_payload)
        pool = self._require_pool(lease.pool_name)
        result = pool.commit_lease(
            lease=lease,
            media_type=_require_str(payload, "media_type"),
            shape=_read_int_tuple(payload.get("shape")),
            dtype=_read_optional_str(payload, "dtype"),
            layout=_read_optional_str(payload, "layout"),
            pixel_format=_read_optional_str(payload, "pixel_format"),
        )
        return {
            "lease": result.lease.model_dump(mode="json"),
            "buffer_ref": result.buffer_ref.model_dump(mode="json"),
        }

    def _handle_validate_buffer_ref(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 validate-buffer-ref 控制动作。"""

        buffer_ref_payload = payload.get("buffer_ref")
        if not isinstance(buffer_ref_payload, dict):
            raise InvalidRequestError("LocalBufferBroker validate-buffer-ref 缺少 buffer_ref")
        buffer_ref = BufferRef.model_validate(buffer_ref_payload)
        pool = self._select_pool_for_buffer_ref(buffer_ref)
        pool.validate_buffer_ref(buffer_ref)
        return {"valid": True}

    def _handle_create_frame_channel(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 create-frame-channel 控制动作。"""

        pool = self._require_pool(_read_optional_str(payload, "pool_name") or self.settings.default_pool_name)
        channel = pool.create_frame_channel(
            stream_id=_require_str(payload, "stream_id"),
            frame_capacity=_require_positive_int(payload, "frame_capacity"),
        )
        return {"channel": channel}

    def _handle_allocate_frame(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 allocate-frame 控制动作。"""

        pool = self._require_pool(_read_optional_str(payload, "pool_name") or self.settings.default_pool_name)
        reservation = pool.allocate_frame(
            stream_id=_require_str(payload, "stream_id"),
            size=_require_positive_int(payload, "size"),
        )
        return {"reservation": reservation}

    def _handle_commit_frame(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 commit-frame 控制动作。"""

        reservation = payload.get("reservation")
        if not isinstance(reservation, dict):
            raise InvalidRequestError("LocalBufferBroker commit-frame 缺少 reservation")
        pool = self._require_pool(str(reservation.get("pool_name") or self.settings.default_pool_name))
        frame_ref = pool.commit_frame(
            reservation=dict(reservation),
            media_type=_require_str(payload, "media_type"),
            shape=_read_int_tuple(payload.get("shape")),
            dtype=_read_optional_str(payload, "dtype"),
            layout=_read_optional_str(payload, "layout"),
            pixel_format=_read_optional_str(payload, "pixel_format"),
            metadata=dict(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
        )
        return {"frame_ref": frame_ref.model_dump(mode="json")}

    def _handle_validate_frame_ref(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 validate-frame-ref 控制动作。"""

        frame_ref_payload = payload.get("frame_ref")
        if not isinstance(frame_ref_payload, dict):
            raise InvalidRequestError("LocalBufferBroker validate-frame-ref 缺少 frame_ref")
        frame_ref = FrameRef.model_validate(frame_ref_payload)
        pool = self._select_pool_for_buffer_id(frame_ref.buffer_id)
        pool.validate_frame_ref(frame_ref)
        return {"valid": True}

    def _handle_read_frame_ref(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 read-frame-ref 控制动作。"""

        frame_ref_payload = payload.get("frame_ref")
        if not isinstance(frame_ref_payload, dict):
            raise InvalidRequestError("LocalBufferBroker read-frame-ref 缺少 frame_ref")
        frame_ref = FrameRef.model_validate(frame_ref_payload)
        pool = self._select_pool_for_buffer_id(frame_ref.buffer_id)
        return {"content": pool.read_frame_ref(frame_ref)}

    def _handle_release(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 release 控制动作。"""

        lease_id = _require_str(payload, "lease_id")
        pool_name = _read_optional_str(payload, "pool_name")
        if pool_name is not None:
            self._require_pool(pool_name).release(lease_id)
            return {"released": True, "lease_id": lease_id}
        last_error: InvalidRequestError | None = None
        for pool in self._pools.values():
            try:
                pool.release(lease_id)
                return {"released": True, "lease_id": lease_id}
            except InvalidRequestError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise InvalidRequestError("mmap buffer lease 不存在", details={"lease_id": lease_id})

    def _handle_release_owner(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 release-owner 控制动作。"""

        owner_kind = _read_optional_str(payload, "owner_kind")
        owner_id = _read_optional_str(payload, "owner_id")
        owner_id_prefix = _read_optional_str(payload, "owner_id_prefix")
        if owner_id is None and owner_id_prefix is None:
            raise InvalidRequestError("LocalBufferBroker release-owner 缺少 owner_id 或 owner_id_prefix")
        pool_name = _read_optional_str(payload, "pool_name")
        if pool_name is not None:
            released_count = self._require_pool(pool_name).release_owner(
                owner_kind=owner_kind,
                owner_id=owner_id,
                owner_id_prefix=owner_id_prefix,
            )
        else:
            released_count = sum(
                pool.release_owner(
                    owner_kind=owner_kind,
                    owner_id=owner_id,
                    owner_id_prefix=owner_id_prefix,
                )
                for pool in self._pools.values()
            )
        return {
            "released_count": released_count,
            "owner_kind": owner_kind,
            "owner_id": owner_id,
            "owner_id_prefix": owner_id_prefix,
            "pool_name": pool_name,
        }

    def _handle_expire_leases(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 expire-leases 控制动作。"""

        pool_name = _read_optional_str(payload, "pool_name")
        if pool_name is not None:
            expired_count = self._require_pool(pool_name).expire_leases()
        else:
            expired_count = sum(pool.expire_leases() for pool in self._pools.values())
        return {"expired_count": expired_count}

    def _build_status(self) -> dict[str, object]:
        """构造 broker 状态 payload。"""

        return {
            "state": "running",
            "process_id": os.getpid(),
            "broker_epoch": self.broker_epoch,
            "default_pool_name": self.settings.default_pool_name,
            "pools": [
                pool.build_status() for pool in self._pools.values()
            ],
        }

    def _require_pool(self, pool_name: str) -> MmapBufferPool:
        """按名称读取 pool。"""

        normalized_pool_name = pool_name.strip()
        pool = self._pools.get(normalized_pool_name)
        if pool is None:
            raise InvalidRequestError("LocalBufferBroker pool 不存在", details={"pool_name": normalized_pool_name})
        return pool

    def _select_pool_for_buffer_ref(self, buffer_ref: BufferRef) -> MmapBufferPool:
        """按 BufferRef 定位所属 pool。"""

        for pool in self._pools.values():
            if Path(buffer_ref.path) == pool.file_path:
                return pool
        return self._select_pool_for_buffer_id(buffer_ref.buffer_id)

    def _select_pool_for_buffer_id(self, buffer_id: str) -> MmapBufferPool:
        """按 buffer_id 前缀定位所属 pool。"""

        for pool_name, pool in self._pools.items():
            if buffer_id.startswith(f"{pool_name}:"):
                return pool
        raise InvalidRequestError("LocalBufferBroker 找不到 buffer 所属 pool", details={"buffer_id": buffer_id})


def run_local_buffer_broker_process(
    *,
    settings_payload: dict[str, object],
    startup_queue: Any,
    request_queue: Any,
    response_queue: Any,
) -> None:
    """LocalBufferBroker companion process 入口。

    参数：
    - settings_payload：LocalBufferBrokerSettings 的可序列化配置。
    - startup_queue：向 supervisor 回报启动状态的队列。
    - request_queue：接收控制事件的队列。
    - response_queue：返回控制事件处理结果的队列。
    """

    registry: LocalBufferBrokerRegistry | None = None
    try:
        settings = LocalBufferBrokerSettings.model_validate(settings_payload)
        registry = LocalBufferBrokerRegistry(settings=settings)
        startup_queue.put(
            {
                "ok": True,
                "broker_epoch": registry.broker_epoch,
                "process_id": os.getpid(),
            }
        )
        stop_requested = False
        while not stop_requested:
            message = request_queue.get()
            request_id = str(message.get("request_id") or "") if isinstance(message, dict) else ""
            try:
                action = str(message.get("action") or "") if isinstance(message, dict) else ""
                payload = registry.handle(message)
                response_queue.put({"request_id": request_id, "ok": True, "payload": payload})
                if action == "shutdown":
                    stop_requested = True
            except ServiceError as exc:
                response_queue.put({"request_id": request_id, **_serialize_error(exc)})
            except Exception as exc:  # pragma: no cover - broker 进程兜底错误封装
                response_queue.put(
                    {
                        "request_id": request_id,
                        **_serialize_error(
                            ServiceConfigurationError(
                                "LocalBufferBroker 控制请求执行失败",
                                details={"error_type": type(exc).__name__, "error_message": str(exc)},
                            )
                        ),
                    }
                )
    except Exception as exc:  # pragma: no cover - 启动失败需要跨进程回传
        startup_queue.put(
            {
                "ok": False,
                "error": {
                    "code": getattr(exc, "code", "service_configuration_error"),
                    "message": getattr(exc, "message", str(exc) or type(exc).__name__),
                    "details": getattr(exc, "details", {"error_type": type(exc).__name__}),
                },
            }
        )
    finally:
        if registry is not None:
            registry.close()


def _serialize_error(error: ServiceError) -> dict[str, object]:
    """把 ServiceError 转换为 broker 控制响应。"""

    return {
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": dict(error.details),
        },
    }


def _require_str(payload: dict[str, object], field_name: str) -> str:
    """读取非空字符串字段。"""

    value = payload.get(field_name)
    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise InvalidRequestError("LocalBufferBroker payload 缺少必需字符串字段", details={"field_name": field_name})
    return normalized_value


def _read_optional_str(payload: dict[str, object], field_name: str) -> str | None:
    """读取可选字符串字段。"""

    value = payload.get(field_name)
    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _read_optional_float(payload: dict[str, object], field_name: str) -> float | None:
    """读取可选浮点数字段。"""

    value = payload.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool):
        raise InvalidRequestError("LocalBufferBroker payload 字段必须是数字", details={"field_name": field_name})
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError("LocalBufferBroker payload 字段必须是数字", details={"field_name": field_name}) from exc


def _require_positive_int(payload: dict[str, object], field_name: str) -> int:
    """读取正整数字段。"""

    value = payload.get(field_name)
    if isinstance(value, bool):
        raise InvalidRequestError("LocalBufferBroker payload 字段必须是正整数", details={"field_name": field_name})
    try:
        normalized_value = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError("LocalBufferBroker payload 字段必须是正整数", details={"field_name": field_name}) from exc
    if normalized_value <= 0:
        raise InvalidRequestError("LocalBufferBroker payload 字段必须是正整数", details={"field_name": field_name})
    return normalized_value


def _read_int_tuple(value: object) -> tuple[int, ...]:
    """读取整数 tuple 字段。"""

    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise InvalidRequestError("LocalBufferBroker shape 必须是整数列表")
    try:
        return tuple(int(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError("LocalBufferBroker shape 必须是整数列表") from exc