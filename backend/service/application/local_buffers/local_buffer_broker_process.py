"""LocalBufferBroker 独立进程入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from multiprocessing import parent_process
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.contracts.buffers import BufferLease, BufferRef, FrameRef
from backend.contracts.buffers.lease_ownership import LeaseOwnershipReceipt
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceError,
    ServiceConfigurationError,
)
from backend.service.application.local_buffers.broker_instance_lock import (
    LocalBufferBrokerInstanceLock,
)
from backend.service.application.local_buffers.broker_settings import (
    LocalBufferBrokerSettings,
)
from backend.service.infrastructure.local_buffers import (
    MmapBufferPool,
    MmapBufferPoolConfig,
)


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
                raise InvalidRequestError(
                    "LocalBufferBroker pool_name 重复", details={"pool_name": pool_name}
                )
            self._pools[pool_name] = MmapBufferPool(
                MmapBufferPoolConfig(
                    pool_name=pool_name,
                    root_dir=root_dir / pool_name,
                    file_name=pool_settings.file_name,
                    file_size_bytes=pool_settings.file_size_bytes,
                    slot_size_bytes=pool_settings.slot_size_bytes,
                    broker_epoch=self.broker_epoch,
                    flush_on_write=pool_settings.flush_on_write,
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
        payload = (
            message.get("payload") if isinstance(message.get("payload"), dict) else {}
        )
        if action == "status":
            return self._build_status()
        if action == "allocate-buffer":
            return self._handle_allocate_buffer(dict(payload))
        if action == "allocate-external-buffer":
            return self._handle_allocate_external_buffer(dict(payload))
        if action == "commit-buffer":
            return self._handle_commit_buffer(dict(payload))
        if action == "commit-external-buffer":
            return self._handle_commit_external_buffer(dict(payload))
        if action == "publish-and-transfer-external-buffer":
            return self._handle_publish_and_transfer_external_buffer(dict(payload))
        if action == "transfer-lease-ownership":
            return self._handle_transfer_lease_ownership(dict(payload))
        if action == "conditional-release":
            return self._handle_conditional_release(dict(payload))
        if action == "sweep-reclaiming-leases":
            return self._handle_sweep_reclaiming_leases(dict(payload))
        if action == "validate-buffer-ref":
            return self._handle_validate_buffer_ref(dict(payload))
        if action == "prepare-buffer-reader":
            return self._handle_prepare_buffer_reader(dict(payload))
        if action == "create-frame-channel":
            return self._handle_create_frame_channel(dict(payload))
        if action == "allocate-frame":
            return self._handle_allocate_frame(dict(payload))
        if action == "commit-frame":
            return self._handle_commit_frame(dict(payload))
        if action == "abort-frame":
            return self._handle_abort_frame(dict(payload))
        if action == "destroy-frame-channel":
            return self._handle_destroy_frame_channel(dict(payload))
        if action == "validate-frame-ref":
            return self._handle_validate_frame_ref(dict(payload))
        if action == "prepare-frame-reader":
            return self._handle_prepare_frame_reader(dict(payload))
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
        raise InvalidRequestError(
            "LocalBufferBroker 收到未知控制动作", details={"action": action}
        )

    def close(self) -> None:
        """关闭全部 mmap pool。"""

        for pool in self._pools.values():
            pool.close()

    def sweep_reclaiming_leases(self) -> dict[str, int]:
        """非阻塞推进全部 external lease 的 deadline 回收状态机。"""

        summaries = [pool.sweep_reclaiming_leases() for pool in self._pools.values()]
        return {
            "released_count": sum(item["released_count"] for item in summaries),
            "quarantined_count": sum(
                item["quarantined_count"] for item in summaries
            ),
        }

    def _handle_allocate_buffer(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 allocate-buffer 控制动作。"""

        pool = self._require_pool(
            _read_optional_str(payload, "pool_name") or self.settings.default_pool_name
        )
        lease = pool.allocate(
            size=_require_positive_int(payload, "size"),
            owner_kind=_require_str(payload, "owner_kind"),
            owner_id=_require_str(payload, "owner_id"),
            ttl_seconds=_read_optional_float(payload, "ttl_seconds"),
            trace_id=_read_optional_str(payload, "trace_id"),
        )
        return {"lease": lease.model_dump(mode="json")}

    def _handle_allocate_external_buffer(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """处理外部 writer 精确长度 lease PREPARE。"""

        pool = self._require_pool(
            _read_optional_str(payload, "pool_name") or self.settings.default_pool_name
        )
        allocation = pool.allocate_external(
            size=_require_positive_int(payload, "size"),
            owner_kind=_require_str(payload, "owner_kind"),
            owner_id=_require_str(payload, "owner_id"),
            deadline_ns=_require_positive_int(payload, "deadline_ns"),
            ttl_seconds=_read_optional_float(payload, "ttl_seconds"),
            trace_id=_read_optional_str(payload, "trace_id"),
        )
        return {
            "lease": allocation.lease.model_dump(mode="json"),
            "receipt": allocation.receipt.model_dump(mode="json"),
            "slot_capacity_bytes": allocation.slot_capacity_bytes,
        }

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

    def _handle_commit_external_buffer(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """校验 external writer guard 与 checksum 后发布 BufferRef。"""

        receipt = _require_receipt(payload)
        pool = self._require_pool(receipt.pool_name)
        result = pool.commit_external_lease(
            receipt=receipt,
            checksum_algorithm=_require_positive_int(
                payload, "checksum_algorithm"
            ),
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
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """确认 external writer 已结束并原子完成发布与首次 owner handoff。"""

        receipt = _require_receipt(payload)
        pool = self._require_pool(receipt.pool_name)
        result = pool.publish_external_lease_and_transfer(
            receipt=receipt,
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
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """跨 pool 两阶段校验后原子语义地转移一组 lease owner。"""

        receipts_payload = payload.get("receipts")
        if not isinstance(receipts_payload, list):
            raise InvalidRequestError("transfer-lease-ownership 缺少 receipts")
        receipts = tuple(
            LeaseOwnershipReceipt.model_validate(item) for item in receipts_payload
        )
        groups: dict[str, list[LeaseOwnershipReceipt]] = {}
        for receipt in receipts:
            groups.setdefault(receipt.pool_name, []).append(receipt)
        for pool_name, group in groups.items():
            self._require_pool(pool_name).validate_ownership_batch(
                receipts=tuple(group)
            )
        transferred_by_identity: dict[
            tuple[str, str, int], LeaseOwnershipReceipt
        ] = {}
        for pool_name, group in groups.items():
            transferred = self._require_pool(pool_name).transfer_ownership_batch(
                receipts=tuple(group),
                new_owner_kind=_require_str(payload, "new_owner_kind"),
                new_owner_id=_require_str(payload, "new_owner_id"),
                deadline_ns=_require_positive_int(payload, "deadline_ns"),
            )
            for receipt in transferred:
                transferred_by_identity[
                    (receipt.pool_name, receipt.lease_id, receipt.generation)
                ] = receipt
        ordered = [
            transferred_by_identity[
                (receipt.pool_name, receipt.lease_id, receipt.generation)
            ].model_dump(mode="json")
            for receipt in receipts
        ]
        return {"receipts": ordered}

    def _handle_conditional_release(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """按完整 receipt fence 释放或转入撤销状态。"""

        receipt = _require_receipt(payload)
        status = self._require_pool(receipt.pool_name).conditional_release(
            receipt=receipt
        )
        return {"status": status}

    def _handle_sweep_reclaiming_leases(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """触发所有或指定 pool 的非阻塞撤销清理。"""

        pool_name = _read_optional_str(payload, "pool_name")
        pools = (
            (self._require_pool(pool_name),)
            if pool_name is not None
            else tuple(self._pools.values())
        )
        summaries = [pool.sweep_reclaiming_leases() for pool in pools]
        return {
            "released_count": sum(item["released_count"] for item in summaries),
            "quarantined_count": sum(
                item["quarantined_count"] for item in summaries
            ),
        }

    def _handle_validate_buffer_ref(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """处理 validate-buffer-ref 控制动作。"""

        buffer_ref_payload = payload.get("buffer_ref")
        if not isinstance(buffer_ref_payload, dict):
            raise InvalidRequestError(
                "LocalBufferBroker validate-buffer-ref 缺少 buffer_ref"
            )
        buffer_ref = BufferRef.model_validate(buffer_ref_payload)
        pool = self._select_pool_for_buffer_ref(buffer_ref)
        pool.validate_buffer_ref(buffer_ref)
        return {"valid": True}

    def _handle_prepare_buffer_reader(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """返回 BufferRef 对应的稳定 reader guard 位置。"""

        buffer_ref_payload = payload.get("buffer_ref")
        if not isinstance(buffer_ref_payload, dict):
            raise InvalidRequestError(
                "LocalBufferBroker prepare-buffer-reader 缺少 buffer_ref"
            )
        buffer_ref = BufferRef.model_validate(buffer_ref_payload)
        pool = self._select_pool_for_buffer_ref(buffer_ref)
        pool.validate_buffer_ref(buffer_ref)
        slot_index = buffer_ref.offset // pool.config.slot_size_bytes
        _writer_path, reader_path = pool.ensure_slot_guard_files(slot_index)
        return {
            "reader_guard_path": str(reader_path),
            "reader_guard_slots": pool.config.reader_guard_slots,
        }

    def _handle_create_frame_channel(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """处理 create-frame-channel 控制动作。"""

        pool = self._require_pool(
            _read_optional_str(payload, "pool_name") or self.settings.default_pool_name
        )
        channel = pool.create_frame_channel(
            stream_id=_require_str(payload, "stream_id"),
            frame_capacity=_require_positive_int(payload, "frame_capacity"),
        )
        return {"channel": channel}

    def _handle_allocate_frame(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 allocate-frame 控制动作。"""

        pool = self._require_pool(
            _read_optional_str(payload, "pool_name") or self.settings.default_pool_name
        )
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
        pool = self._require_pool(
            str(reservation.get("pool_name") or self.settings.default_pool_name)
        )
        frame_ref = pool.commit_frame(
            reservation=dict(reservation),
            media_type=_require_str(payload, "media_type"),
            shape=_read_int_tuple(payload.get("shape")),
            dtype=_read_optional_str(payload, "dtype"),
            layout=_read_optional_str(payload, "layout"),
            pixel_format=_read_optional_str(payload, "pixel_format"),
            metadata=dict(
                payload.get("metadata")
                if isinstance(payload.get("metadata"), dict)
                else {}
            ),
        )
        return {"frame_ref": frame_ref.model_dump(mode="json")}

    def _handle_abort_frame(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 abort-frame 控制动作。"""

        reservation = payload.get("reservation")
        if not isinstance(reservation, dict):
            raise InvalidRequestError("LocalBufferBroker abort-frame 缺少 reservation")
        pool = self._require_pool(
            str(reservation.get("pool_name") or self.settings.default_pool_name)
        )
        pool.abort_frame(reservation=dict(reservation))
        return {"aborted": True}

    def _handle_destroy_frame_channel(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """处理 destroy-frame-channel 控制动作。"""

        pool = self._require_pool(
            _read_optional_str(payload, "pool_name") or self.settings.default_pool_name
        )
        stream_id = _require_str(payload, "stream_id")
        released_slot_count = pool.destroy_frame_channel(stream_id=stream_id)
        return {
            "destroyed": True,
            "stream_id": stream_id,
            "released_slot_count": released_slot_count,
        }

    def _handle_validate_frame_ref(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """处理 validate-frame-ref 控制动作。"""

        frame_ref_payload = payload.get("frame_ref")
        if not isinstance(frame_ref_payload, dict):
            raise InvalidRequestError(
                "LocalBufferBroker validate-frame-ref 缺少 frame_ref"
            )
        frame_ref = FrameRef.model_validate(frame_ref_payload)
        pool = self._select_pool_for_buffer_id(frame_ref.buffer_id)
        pool.validate_frame_ref(frame_ref)
        return {"valid": True}

    def _handle_prepare_frame_reader(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        """校验 FrameRef 并返回服务端内部 reader guard 定位。"""

        frame_ref_payload = payload.get("frame_ref")
        if not isinstance(frame_ref_payload, dict):
            raise InvalidRequestError(
                "LocalBufferBroker prepare-frame-reader 缺少 frame_ref"
            )
        frame_ref = FrameRef.model_validate(frame_ref_payload)
        pool = self._select_pool_for_buffer_id(frame_ref.buffer_id)
        pool.validate_frame_ref(frame_ref)
        slot_index = frame_ref.offset // pool.config.slot_size_bytes
        _writer_path, reader_path = pool.ensure_slot_guard_files(slot_index)
        return {
            "reader_guard_path": str(reader_path),
            "reader_guard_slots": pool.config.reader_guard_slots,
        }

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
        raise InvalidRequestError(
            "mmap buffer lease 不存在", details={"lease_id": lease_id}
        )

    def _handle_release_owner(self, payload: dict[str, object]) -> dict[str, object]:
        """处理 release-owner 控制动作。"""

        owner_kind = _read_optional_str(payload, "owner_kind")
        owner_id = _read_optional_str(payload, "owner_id")
        owner_id_prefix = _read_optional_str(payload, "owner_id_prefix")
        if owner_id is None and owner_id_prefix is None:
            raise InvalidRequestError(
                "LocalBufferBroker release-owner 缺少 owner_id 或 owner_id_prefix"
            )
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
            "pools": [pool.build_status() for pool in self._pools.values()],
        }

    def _require_pool(self, pool_name: str) -> MmapBufferPool:
        """按名称读取 pool。"""

        normalized_pool_name = pool_name.strip()
        pool = self._pools.get(normalized_pool_name)
        if pool is None:
            raise InvalidRequestError(
                "LocalBufferBroker pool 不存在",
                details={"pool_name": normalized_pool_name},
            )
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
        raise InvalidRequestError(
            "LocalBufferBroker 找不到 buffer 所属 pool",
            details={"buffer_id": buffer_id},
        )


def run_local_buffer_broker_process(
    *,
    settings_payload: dict[str, object],
    startup_queue: Any,
    request_connection: Any,
    response_connection: Any,
) -> None:
    """LocalBufferBroker companion process 入口。

    参数：
    - settings_payload：LocalBufferBrokerSettings 的可序列化配置。
    - startup_queue：向 supervisor 回报启动状态的队列。
    - request_connection：接收控制事件的单向连接。
    - response_connection：返回控制事件处理结果的单向连接。
    """

    registry: LocalBufferBrokerRegistry | None = None
    instance_lock: LocalBufferBrokerInstanceLock | None = None
    try:
        settings = LocalBufferBrokerSettings.model_validate(settings_payload)
        instance_lock = LocalBufferBrokerInstanceLock(Path(settings.root_dir))
        instance_lock.acquire()
        registry = LocalBufferBrokerRegistry(settings=settings)
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
                    # Windows 不会保证强制结束父进程时同步结束 multiprocessing 子进程。
                    # broker 定期检查 supervisor，避免孤立进程长期占用默认 mmap pool。
                    if (
                        supervisor_process is not None
                        and not supervisor_process.is_alive()
                    ):
                        break
                    continue
                message = request_connection.recv()
            except (EOFError, OSError):
                # 父进程退出后单向控制连接会关闭。
                break
            request_id = (
                str(message.get("request_id") or "")
                if isinstance(message, dict)
                else ""
            )
            try:
                action = (
                    str(message.get("action") or "")
                    if isinstance(message, dict)
                    else ""
                )
                payload = registry.handle(message)
                response_connection.send(
                    {"request_id": request_id, "ok": True, "payload": payload}
                )
                if action == "shutdown":
                    stop_requested = True
            except ServiceError as exc:
                response_connection.send(
                    {"request_id": request_id, **_serialize_error(exc)}
                )
            except Exception as exc:  # pragma: no cover - broker 进程兜底错误封装
                response_connection.send(
                    {
                        "request_id": request_id,
                        **_serialize_error(
                            ServiceConfigurationError(
                                "LocalBufferBroker 控制请求执行失败",
                                details={
                                    "error_type": type(exc).__name__,
                                    "error_message": str(exc),
                                },
                            )
                        ),
                    }
                )
    except KeyboardInterrupt:
        # Uvicorn reload 和控制台关闭可能把中断信号同时发送给父进程与 broker。
        # broker 只需执行 finally 中的 mmap 清理，不重复输出子进程 traceback。
        pass
    except Exception as exc:  # pragma: no cover - 启动失败需要跨进程回传
        _publish_startup_message(
            startup_queue,
            {
                "ok": False,
                "error": {
                    "code": getattr(exc, "code", "service_configuration_error"),
                    "message": getattr(exc, "message", str(exc) or type(exc).__name__),
                    "details": getattr(
                        exc, "details", {"error_type": type(exc).__name__}
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
    """发布唯一一条启动结果，并确保 Windows Queue feeder 已完成刷新。"""

    startup_queue.put(message)
    close = getattr(startup_queue, "close", None)
    if callable(close):
        close()
    join_thread = getattr(startup_queue, "join_thread", None)
    if callable(join_thread):
        join_thread()


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
        raise InvalidRequestError(
            "LocalBufferBroker payload 缺少必需字符串字段",
            details={"field_name": field_name},
        )
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
        raise InvalidRequestError(
            "LocalBufferBroker payload 字段必须是数字",
            details={"field_name": field_name},
        )
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(
            "LocalBufferBroker payload 字段必须是数字",
            details={"field_name": field_name},
        ) from exc


def _require_positive_int(payload: dict[str, object], field_name: str) -> int:
    """读取正整数字段。"""

    value = payload.get(field_name)
    if isinstance(value, bool):
        raise InvalidRequestError(
            "LocalBufferBroker payload 字段必须是正整数",
            details={"field_name": field_name},
        )
    try:
        normalized_value = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(
            "LocalBufferBroker payload 字段必须是正整数",
            details={"field_name": field_name},
        ) from exc
    if normalized_value <= 0:
        raise InvalidRequestError(
            "LocalBufferBroker payload 字段必须是正整数",
            details={"field_name": field_name},
        )
    return normalized_value


def _require_nonnegative_int(payload: dict[str, object], field_name: str) -> int:
    """读取非负整数字段。"""

    value = payload.get(field_name)
    if isinstance(value, bool):
        raise InvalidRequestError(
            "LocalBufferBroker payload 字段必须是非负整数",
            details={"field_name": field_name},
        )
    try:
        normalized_value = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(
            "LocalBufferBroker payload 字段必须是非负整数",
            details={"field_name": field_name},
        ) from exc
    if normalized_value < 0:
        raise InvalidRequestError(
            "LocalBufferBroker payload 字段必须是非负整数",
            details={"field_name": field_name},
        )
    return normalized_value


def _require_receipt(payload: dict[str, object]) -> LeaseOwnershipReceipt:
    """读取并校验私有 LocalBuffer ownership receipt。"""

    receipt_payload = payload.get("receipt")
    if not isinstance(receipt_payload, dict):
        raise InvalidRequestError("LocalBufferBroker payload 缺少 receipt")
    return LeaseOwnershipReceipt.model_validate(receipt_payload)


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
