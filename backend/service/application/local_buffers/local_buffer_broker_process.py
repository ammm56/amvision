"""LocalBufferBroker 单 arena 独立进程入口。"""

from __future__ import annotations

from dataclasses import dataclass
from multiprocessing import parent_process
import os
from pathlib import Path
from typing import Any

from backend.contracts.buffers import BufferLease, BufferRef, FrameRef
from backend.contracts.buffers.lease_ownership import LeaseOwnershipReceipt
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.local_buffers.broker_instance_lock import (
    LocalBufferBrokerInstanceLock,
)
from backend.service.application.local_buffers.broker_settings import (
    LocalBufferBrokerSettings,
)
from backend.service.infrastructure.local_buffers.local_buffer_arena_pool import (
    LocalBufferArenaPool,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    MmapBufferArenaConfig,
)


@dataclass
class LocalBufferBrokerRegistry:
    """把单一固定容量 arena 收敛为 Broker 控制动作。"""

    settings: LocalBufferBrokerSettings
    root_dir: Path

    def __post_init__(self) -> None:
        """按冻结几何创建唯一主 arena。"""

        self._arena = LocalBufferArenaPool(
            MmapBufferArenaConfig(
                root_dir=self.root_dir,
                arena_id=self.settings.arena_id,
                arena_size_bytes=self.settings.arena_size_bytes,
                min_block_size_bytes=self.settings.min_block_size_bytes,
                max_allocation_bytes=self.settings.max_allocation_bytes,
                huge_reserve_bytes=self.settings.huge_reserve_bytes,
                reader_guard_slots=self.settings.reader_guard_slots,
                flush_on_write=self.settings.flush_on_write,
                revocation_grace_seconds=self.settings.revocation_grace_seconds,
            )
        )

    @property
    def broker_epoch(self) -> str:
        """返回当前 arena owner epoch。"""

        return self._arena.broker_epoch

    def handle(self, message: object) -> dict[str, object]:
        """处理一条 Broker 控制消息。"""

        if not isinstance(message, dict):
            raise InvalidRequestError("LocalBufferBroker 请求必须是对象")
        action = str(message.get("action") or "").strip()
        payload = message.get("payload")
        normalized_payload = dict(payload) if isinstance(payload, dict) else {}
        handlers = {
            "status": self._handle_status,
            "allocate-buffer": self._handle_allocate_buffer,
            "allocate-buffers": self._handle_allocate_buffers,
            "allocate-external-buffer": self._handle_allocate_external_buffer,
            "commit-buffer": self._handle_commit_buffer,
            "commit-buffers": self._handle_commit_buffers,
            "commit-external-buffer": self._handle_commit_external_buffer,
            "publish-and-transfer-external-buffer": (
                self._handle_publish_and_transfer_external_buffer
            ),
            "transfer-lease-ownership": self._handle_transfer_lease_ownership,
            "conditional-release": self._handle_conditional_release,
            "sweep-reclaiming-leases": self._handle_sweep,
            "validate-buffer-ref": self._handle_validate_buffer_ref,
            "prepare-buffer-reader": self._handle_prepare_buffer_reader,
            "create-frame-channel": self._handle_create_frame_channel,
            "allocate-frame": self._handle_allocate_frame,
            "commit-frame": self._handle_commit_frame,
            "abort-frame": self._handle_abort_frame,
            "destroy-frame-channel": self._handle_destroy_frame_channel,
            "validate-frame-ref": self._handle_validate_frame_ref,
            "prepare-frame-reader": self._handle_prepare_frame_reader,
            "read-frame-ref": self._handle_read_frame_ref,
            "release": self._handle_release,
            "release-many": self._handle_release_many,
            "release-owner": self._handle_release_owner,
            "release-by-owner": self._handle_release_owner,
            "expire-leases": self._handle_expire_leases,
            "shutdown": self._handle_shutdown,
        }
        handler = handlers.get(action)
        if handler is None:
            raise InvalidRequestError(
                "LocalBufferBroker 收到未知控制动作",
                details={"action": action},
            )
        return handler(normalized_payload)

    def close(self) -> None:
        """关闭唯一 arena。"""

        self._arena.close()

    def sweep_reclaiming_leases(self) -> dict[str, int]:
        """非阻塞推进 deadline 与撤销状态机。"""

        return self._arena.sweep_reclaiming_leases()

    def _handle_status(self, _payload: dict[str, object]) -> dict[str, object]:
        status = self._arena.build_status()
        return {"process_id": os.getpid(), **status}

    def _handle_allocate_buffer(self, payload: dict[str, object]) -> dict[str, object]:
        lease = self._arena.allocate(
            content_length=_require_positive_int(payload, "content_length"),
            owner_kind=_require_str(payload, "owner_kind"),
            owner_id=_require_str(payload, "owner_id"),
            ttl_seconds=_read_optional_float(payload, "ttl_seconds"),
            trace_id=_read_optional_str(payload, "trace_id"),
        )
        return {
            "lease": lease.model_dump(mode="json"),
            "writer": self._build_writer_location(lease.descriptor_index),
        }

    def _handle_allocate_buffers(self, payload: dict[str, object]) -> dict[str, object]:
        """在一条控制消息中有序分配多块普通 WRITING extent。"""

        raw_items = _require_dict_items(payload, "items", max_count=256)
        owner_kind = _require_str(payload, "owner_kind")
        owner_id = _require_str(payload, "owner_id")
        ttl_seconds = _read_optional_float(payload, "ttl_seconds")
        trace_id = _read_optional_str(payload, "trace_id")
        leases: list[BufferLease] = []
        try:
            for item in raw_items:
                leases.append(
                    self._arena.allocate(
                        content_length=_require_positive_int(
                            item,
                            "content_length",
                        ),
                        owner_kind=owner_kind,
                        owner_id=owner_id,
                        ttl_seconds=ttl_seconds,
                        trace_id=trace_id,
                    )
                )
        except Exception:
            self._release_lease_ids_best_effort(
                tuple(lease.lease_id for lease in leases)
            )
            raise
        return {
            "allocations": [
                {
                    "lease": lease.model_dump(mode="json"),
                    "writer": self._build_writer_location(
                        lease.descriptor_index
                    ),
                }
                for lease in leases
            ]
        }

    def _handle_allocate_external_buffer(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        allocation = self._arena.allocate_external(
            content_length=_require_positive_int(payload, "content_length"),
            owner_kind=_require_str(payload, "owner_kind"),
            owner_id=_require_str(payload, "owner_id"),
            deadline_ns=_require_positive_int(payload, "deadline_ns"),
            ttl_seconds=_read_optional_float(payload, "ttl_seconds"),
            trace_id=_read_optional_str(payload, "trace_id"),
        )
        return {
            "allocation": allocation.model_dump(mode="json"),
            "writer": self._build_writer_location(
                allocation.lease.descriptor_index
            ),
        }

    def _build_writer_location(self, descriptor_index: int) -> dict[str, object]:
        """返回仅经 Broker 控制通道分发的受信 arena writer locator。"""

        return {
            **self._arena.arena.guard_location(descriptor_index),
            "arena_path": str(self._arena.arena.arena_path),
            "allocator_path": str(self._arena.arena.allocator_path),
            "layout_fingerprint": self._arena.arena.layout_fingerprint.hex(),
        }

    def _handle_commit_buffer(self, payload: dict[str, object]) -> dict[str, object]:
        lease = BufferLease.model_validate(_require_dict(payload, "lease"))
        result = self._arena.commit_lease(
            lease=lease,
            media_type=_require_str(payload, "media_type"),
            shape=_read_int_tuple(payload.get("shape")),
            dtype=_read_optional_str(payload, "dtype"),
            layout=_read_optional_str(payload, "layout"),
            pixel_format=_read_optional_str(payload, "pixel_format"),
            content_length=_read_optional_positive_int(payload, "content_length"),
        )
        return {
            "lease": result.lease.model_dump(mode="json"),
            "buffer_ref": result.buffer_ref.model_dump(mode="json"),
        }

    def _handle_commit_buffers(self, payload: dict[str, object]) -> dict[str, object]:
        """校验全部元数据后有序发布一批 WRITING lease。"""

        raw_items = _require_dict_items(payload, "items", max_count=256)
        prepared = [
            (
                BufferLease.model_validate(_require_dict(item, "lease")),
                _require_str(item, "media_type"),
                _read_int_tuple(item.get("shape")),
                _read_optional_str(item, "dtype"),
                _read_optional_str(item, "layout"),
                _read_optional_str(item, "pixel_format"),
            )
            for item in raw_items
        ]
        results = []
        try:
            for lease, media_type, shape, dtype, layout, pixel_format in prepared:
                results.append(
                    self._arena.commit_lease(
                        lease=lease,
                        media_type=media_type,
                        shape=shape,
                        dtype=dtype,
                        layout=layout,
                        pixel_format=pixel_format,
                    )
                )
        except Exception:
            self._release_lease_ids_best_effort(
                tuple(item[0].lease_id for item in prepared)
            )
            raise
        return {
            "results": [
                {
                    "lease": result.lease.model_dump(mode="json"),
                    "buffer_ref": result.buffer_ref.model_dump(mode="json"),
                }
                for result in results
            ]
        }

    def _handle_commit_external_buffer(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        result = self._arena.commit_external_lease(
            receipt=_require_receipt(payload),
            checksum=_require_nonnegative_int(payload, "checksum"),
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

    def _handle_publish_and_transfer_external_buffer(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        result = self._arena.publish_external_lease_and_transfer(
            receipt=_require_receipt(payload),
            media_type=_require_str(payload, "media_type"),
            new_owner_kind=_require_str(payload, "new_owner_kind"),
            new_owner_id=_require_str(payload, "new_owner_id"),
            deadline_ns=_require_positive_int(payload, "deadline_ns"),
            shape=_read_int_tuple(payload.get("shape")),
            dtype=_read_optional_str(payload, "dtype"),
            layout=_read_optional_str(payload, "layout"),
            pixel_format=_read_optional_str(payload, "pixel_format"),
        )
        return {
            "lease": result.lease.model_dump(mode="json"),
            "buffer_ref": result.buffer_ref.model_dump(mode="json"),
            "receipt": result.receipt.model_dump(mode="json"),
        }

    def _handle_transfer_lease_ownership(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        raw_receipts = payload.get("receipts")
        if not isinstance(raw_receipts, list):
            raise InvalidRequestError("transfer-lease-ownership 缺少 receipts")
        receipts = tuple(
            LeaseOwnershipReceipt.model_validate(item) for item in raw_receipts
        )
        transferred = self._arena.transfer_ownership_batch(
            receipts=receipts,
            new_owner_kind=_require_str(payload, "new_owner_kind"),
            new_owner_id=_require_str(payload, "new_owner_id"),
            deadline_ns=_require_positive_int(payload, "deadline_ns"),
        )
        return {
            "receipts": [item.model_dump(mode="json") for item in transferred]
        }

    def _handle_conditional_release(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return {
            "status": self._arena.conditional_release(
                receipt=_require_receipt(payload)
            )
        }

    def _handle_sweep(self, _payload: dict[str, object]) -> dict[str, object]:
        return self._arena.sweep_reclaiming_leases()

    def _handle_validate_buffer_ref(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        ref = BufferRef.model_validate(_require_dict(payload, "buffer_ref"))
        self._arena.validate_buffer_ref(ref)
        return {"valid": True}

    def _handle_prepare_buffer_reader(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        ref = BufferRef.model_validate(_require_dict(payload, "buffer_ref"))
        return {
            **self._arena.reader_guard_location(ref),
            "arena_path": str(self._arena.arena.arena_path),
            "allocator_path": str(self._arena.arena.allocator_path),
            "layout_fingerprint": self._arena.arena.layout_fingerprint.hex(),
        }

    def _handle_create_frame_channel(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return {
            "channel": self._arena.create_frame_channel(
                stream_id=_require_str(payload, "stream_id"),
                frame_count=_require_positive_int(payload, "frame_count"),
                max_frame_content_length=_require_positive_int(
                    payload,
                    "max_frame_content_length",
                ),
            )
        }

    def _handle_allocate_frame(self, payload: dict[str, object]) -> dict[str, object]:
        reservation = self._arena.allocate_frame(
                stream_id=_require_str(payload, "stream_id"),
                content_length=_require_positive_int(payload, "content_length"),
            )
        return {
            "reservation": {
                **reservation,
                "arena_path": str(self._arena.arena.arena_path),
                "allocator_path": str(self._arena.arena.allocator_path),
                "layout_fingerprint": self._arena.arena.layout_fingerprint.hex(),
            }
        }

    def _handle_commit_frame(self, payload: dict[str, object]) -> dict[str, object]:
        frame = self._arena.commit_frame(
            reservation=_require_dict(payload, "reservation"),
            media_type=_require_str(payload, "media_type"),
            shape=_read_int_tuple(payload.get("shape")),
            dtype=_read_optional_str(payload, "dtype"),
            layout=_read_optional_str(payload, "layout"),
            pixel_format=_read_optional_str(payload, "pixel_format"),
            metadata=(
                dict(payload["metadata"])
                if isinstance(payload.get("metadata"), dict)
                else {}
            ),
        )
        return {"frame_ref": frame.model_dump(mode="json")}

    def _handle_abort_frame(self, payload: dict[str, object]) -> dict[str, object]:
        self._arena.abort_frame(reservation=_require_dict(payload, "reservation"))
        return {"aborted": True}

    def _handle_destroy_frame_channel(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        stream_id = _require_str(payload, "stream_id")
        count = self._arena.destroy_frame_channel(stream_id=stream_id)
        return {
            "destroyed": True,
            "stream_id": stream_id,
            "released_extent_count": count,
        }

    def _handle_validate_frame_ref(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        ref = FrameRef.model_validate(_require_dict(payload, "frame_ref"))
        self._arena.validate_frame_ref(ref)
        return {"valid": True}

    def _handle_prepare_frame_reader(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        ref = FrameRef.model_validate(_require_dict(payload, "frame_ref"))
        return {
            **self._arena.frame_reader_guard_location(ref),
            "arena_path": str(self._arena.arena.arena_path),
            "allocator_path": str(self._arena.arena.allocator_path),
            "layout_fingerprint": self._arena.arena.layout_fingerprint.hex(),
        }

    def _handle_read_frame_ref(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        ref = FrameRef.model_validate(_require_dict(payload, "frame_ref"))
        return {"content": self._arena.read_frame_ref(ref)}

    def _handle_release(self, payload: dict[str, object]) -> dict[str, object]:
        self._arena.release(_require_str(payload, "lease_id"))
        return {"released": True}

    def _handle_release_many(self, payload: dict[str, object]) -> dict[str, object]:
        """按 lease_id 列表尽最大努力释放全部记录。"""

        raw_ids = payload.get("lease_ids")
        if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > 256:
            raise InvalidRequestError("release-many 要求 1 到 256 个 lease_id")
        lease_ids = tuple(
            _require_str({"lease_id": value}, "lease_id") for value in raw_ids
        )
        released_count = self._release_lease_ids_best_effort(lease_ids)
        return {"released_count": released_count}

    def _release_lease_ids_best_effort(self, lease_ids: tuple[str, ...]) -> int:
        """释放仍存在的精确 lease，单项失效不阻断其余项清理。"""

        released_count = 0
        for lease_id in lease_ids:
            try:
                self._arena.release(lease_id)
                released_count += 1
            except InvalidRequestError:
                continue
        return released_count

    def _handle_release_owner(self, payload: dict[str, object]) -> dict[str, object]:
        count = self._arena.release_owner(
            owner_kind=_read_optional_str(payload, "owner_kind"),
            owner_id=_read_optional_str(payload, "owner_id"),
            owner_id_prefix=_read_optional_str(payload, "owner_id_prefix"),
        )
        return {"released_count": count}

    def _handle_expire_leases(
        self,
        _payload: dict[str, object],
    ) -> dict[str, object]:
        return {"expired_count": self._arena.expire_leases()}

    @staticmethod
    def _handle_shutdown(_payload: dict[str, object]) -> dict[str, object]:
        return {"state": "stopping", "process_id": os.getpid()}


def run_local_buffer_broker_process(
    *,
    settings_payload: dict[str, object],
    root_dir: str,
    startup_queue: Any,
    request_connection: Any,
    response_connection: Any,
) -> None:
    """LocalBufferBroker companion process 入口。"""

    registry: LocalBufferBrokerRegistry | None = None
    instance_lock: LocalBufferBrokerInstanceLock | None = None
    try:
        settings = LocalBufferBrokerSettings.model_validate(settings_payload)
        resolved_root = Path(root_dir).resolve()
        instance_lock = LocalBufferBrokerInstanceLock(resolved_root)
        instance_lock.acquire()
        registry = LocalBufferBrokerRegistry(settings=settings, root_dir=resolved_root)
        supervisor_process = parent_process()
        _publish_startup_message(
            startup_queue,
            {
                "ok": True,
                "broker_epoch": registry.broker_epoch,
                "process_id": os.getpid(),
            },
        )
        stop_requested = False
        while not stop_requested:
            try:
                if not request_connection.poll(0.5):
                    registry.sweep_reclaiming_leases()
                    if supervisor_process is not None and not supervisor_process.is_alive():
                        break
                    continue
                message = request_connection.recv()
            except (EOFError, OSError):
                break
            request_id = str(message.get("request_id") or "") if isinstance(message, dict) else ""
            try:
                action = str(message.get("action") or "") if isinstance(message, dict) else ""
                response_connection.send(
                    {
                        "request_id": request_id,
                        "ok": True,
                        "payload": registry.handle(message),
                    }
                )
                stop_requested = action == "shutdown"
            except ServiceError as error:
                response_connection.send(
                    {"request_id": request_id, **_serialize_error(error)}
                )
            except Exception as error:  # pragma: no cover
                wrapped = ServiceConfigurationError(
                    "LocalBufferBroker 控制请求执行失败",
                    details={
                        "error_type": type(error).__name__,
                        "error_message": str(error),
                    },
                )
                response_connection.send(
                    {"request_id": request_id, **_serialize_error(wrapped)}
                )
    except KeyboardInterrupt:
        pass
    except Exception as error:  # pragma: no cover
        _publish_startup_message(
            startup_queue,
            {
                "ok": False,
                "error": {
                    "code": getattr(error, "code", "service_configuration_error"),
                    "message": getattr(
                        error,
                        "message",
                        str(error) or type(error).__name__,
                    ),
                    "details": getattr(
                        error,
                        "details",
                        {"error_type": type(error).__name__},
                    ),
                },
            },
        )
    finally:
        try:
            if registry is not None:
                registry.close()
        finally:
            try:
                if instance_lock is not None:
                    instance_lock.release()
            finally:
                for connection in (request_connection, response_connection):
                    close = getattr(connection, "close", None)
                    if callable(close):
                        close()


def _publish_startup_message(startup_queue: Any, message: dict[str, object]) -> None:
    startup_queue.put(message)
    close = getattr(startup_queue, "close", None)
    if callable(close):
        close()
    join_thread = getattr(startup_queue, "join_thread", None)
    if callable(join_thread):
        join_thread()


def _serialize_error(error: ServiceError) -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": dict(error.details),
        },
    }


def _require_str(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise InvalidRequestError(
            "LocalBufferBroker payload 缺少必需字符串字段",
            details={"field_name": field_name},
        )
    return normalized


def _require_dict_items(
    payload: dict[str, object],
    field_name: str,
    *,
    max_count: int,
) -> tuple[dict[str, object], ...]:
    """读取有界、非空、全为对象的 item 数组。"""

    value = payload.get(field_name)
    if not isinstance(value, list) or not value or len(value) > max_count:
        raise InvalidRequestError(
            f"{field_name} 必须包含 1 到 {max_count} 个对象"
        )
    if not all(isinstance(item, dict) for item in value):
        raise InvalidRequestError(f"{field_name} 的每一项都必须是对象")
    return tuple(dict(item) for item in value)


def _read_optional_str(payload: dict[str, object], field_name: str) -> str | None:
    value = payload.get(field_name)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _read_optional_float(payload: dict[str, object], field_name: str) -> float | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool):
        raise InvalidRequestError(f"{field_name} 必须是数字")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise InvalidRequestError(f"{field_name} 必须是数字") from error
    if result <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return result


def _read_optional_positive_int(
    payload: dict[str, object],
    field_name: str,
) -> int | None:
    """读取可选正整数。"""

    value = payload.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{field_name} 必须是正整数")
    return value


def _require_positive_int(payload: dict[str, object], field_name: str) -> int:
    value = payload.get(field_name)
    if isinstance(value, bool):
        raise InvalidRequestError(f"{field_name} 必须是正整数")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise InvalidRequestError(f"{field_name} 必须是正整数") from error
    if result <= 0:
        raise InvalidRequestError(f"{field_name} 必须是正整数")
    return result


def _require_nonnegative_int(payload: dict[str, object], field_name: str) -> int:
    value = payload.get(field_name)
    if isinstance(value, bool):
        raise InvalidRequestError(f"{field_name} 必须是非负整数")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise InvalidRequestError(f"{field_name} 必须是非负整数") from error
    if result < 0:
        raise InvalidRequestError(f"{field_name} 必须是非负整数")
    return result


def _require_dict(
    payload: dict[str, object],
    field_name: str,
) -> dict[str, object]:
    value = payload.get(field_name)
    if not isinstance(value, dict):
        raise InvalidRequestError(f"LocalBufferBroker payload 缺少 {field_name}")
    return dict(value)


def _require_receipt(payload: dict[str, object]) -> LeaseOwnershipReceipt:
    return LeaseOwnershipReceipt.model_validate(_require_dict(payload, "receipt"))


def _read_int_tuple(value: object) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise InvalidRequestError("LocalBufferBroker shape 必须是整数列表")
    try:
        return tuple(int(item) for item in value)
    except (TypeError, ValueError) as error:
        raise InvalidRequestError("LocalBufferBroker shape 必须是整数列表") from error
