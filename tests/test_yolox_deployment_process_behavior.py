"""deployment warmup 与 keep-warm 行为测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from queue import Queue
from threading import BoundedSemaphore, Event, Thread

from backend.service.application.local_buffers import (
    DirectMmapLocalBufferReader,
    DirectMmapLocalBufferWriter,
    LocalBufferBrokerSettings,
)
from backend.service.infrastructure.local_buffers.local_buffer_arena_pool import (
    LocalBufferArenaPool,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    MmapBufferArenaConfig,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessConfig,
)
from backend.service.application.runtime.support.safe_counter import (
    JSON_SAFE_INTEGER_MAX,
    SafeCounterState,
    increment_safe_counter,
)
from backend.service.application.runtime.deployment.deployment_process_worker import (
    _DeploymentWarmupBehavior,
    _KeepWarmState,
    _LocalBufferBrokerRuntimeHealth,
    _activate_keep_warm,
    _begin_real_inference,
    _finish_real_inference,
    _resolve_warmup_behavior,
    _run_deployment_parent_watchdog,
    _run_dummy_warmup_passes,
    _run_inference_request,
    _run_inference_batch_request,
    _run_keep_warm_loop,
    _snapshot_local_buffer_health,
    _snapshot_keep_warm_state,
)
from backend.service.application.runtime.deployment.deployment_runtime_pool import (
    DeploymentRuntimeBatchExecution,
    DeploymentRuntimeExecution,
    DeploymentRuntimePoolConfig,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionRequest,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentExecutionPolicy,
    DeploymentLifecycleOptions,
    DeploymentRuntimeConfiguration,
    TensorRtRuntimeOptions,
)
from backend.service.settings import BackendServiceDeploymentProcessSupervisorConfig
from tests.runtime_pool_test_support import build_test_execution_result


class _DeadParentProcess:
    """模拟已异常退出的 inference daemon。"""

    def is_alive(self) -> bool:
        """返回父进程已退出。"""

        return False


def test_deployment_worker_exits_when_inference_daemon_is_lost() -> None:
    """父 daemon 失联后 deployment worker 不得作为孤儿进程常驻。"""

    exit_codes: list[int] = []

    _run_deployment_parent_watchdog(
        parent_process=_DeadParentProcess(),
        stop_event=Event(),
        force_exit=exit_codes.append,
        poll_seconds=0.001,
    )

    assert exit_codes == [0]


def test_deployment_worker_watchdog_stops_during_normal_shutdown() -> None:
    """正常 shutdown 已开始时 watchdog 不得强制结束进程。"""

    stop_event = Event()
    stop_event.set()
    exit_codes: list[int] = []

    _run_deployment_parent_watchdog(
        parent_process=_DeadParentProcess(),
        stop_event=stop_event,
        force_exit=exit_codes.append,
        poll_seconds=0.001,
    )

    assert exit_codes == []


def test_deployment_keep_warm_is_disabled_by_default() -> None:
    """验证未显式配置时不会启动设备保活。"""

    settings = BackendServiceDeploymentProcessSupervisorConfig()

    assert settings.keep_warm_enabled is False


class _FakeRuntimePool:
    """提供最小计数能力的 fake runtime pool。"""

    def __init__(
        self,
        *,
        stop_state: _KeepWarmState | None = None,
        error_message: str | None = None,
        started_event: Event | None = None,
        release_event: Event | None = None,
    ) -> None:
        """初始化 fake runtime pool。

        参数：
        - stop_state：第一次执行后需要通知退出的 keep-warm 状态。
        - error_message：如果提供，则每次 fake 推理都会抛出这个错误。
        - started_event：开始 fake 推理时设置的同步事件。
        - release_event：提供后，fake 推理会等待该事件再返回。
        """

        self.stop_state = stop_state
        self.error_message = error_message
        self.started_event = started_event
        self.release_event = release_event
        self.call_count = 0
        self.requests: list[DetectionPredictionRequest] = []

    def run_inference(
        self,
        *,
        config: DeploymentRuntimePoolConfig,
        request: DetectionPredictionRequest,
    ) -> None:
        """记录一次 fake 推理调用。

        参数：
        - config：当前 deployment 的 runtime pool 配置。
        - request：本次推理请求。
        """

        del config
        self.call_count += 1
        self.requests.append(request)
        if self.started_event is not None:
            self.started_event.set()
        if self.release_event is not None:
            self.release_event.wait(timeout=0.5)
        if self.stop_state is not None:
            self.stop_state.stop_event.set()
        if self.error_message is not None:
            raise RuntimeError(self.error_message)


class _PreviewRuntimePool:
    """返回一张测试预览图并核对 LocalBuffer 输入的 runtime pool。"""

    def __init__(self, *, execution_result) -> None:
        self.execution_result = execution_result

    def run_inference(self, *, config, request) -> DeploymentRuntimeExecution:
        """返回固定结果，并确认 worker 已把 BufferRef 解析为图片 view。"""

        assert isinstance(request.input_image_bytes, memoryview)
        assert request.input_image_bytes.tobytes() == b"input-image"
        return DeploymentRuntimeExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id="instance-preview",
            execution_result=self.execution_result,
        )


class _ObjectStorePreviewRuntimePool:
    """核对异步 worker 直接保留 ObjectStore key 的测试 runtime pool。"""

    def __init__(self, *, dataset_storage, execution_result) -> None:
        """保存对象存储和固定执行结果。"""

        self.dataset_storage = dataset_storage
        self.execution_result = execution_result

    def run_inference(self, *, config, request) -> DeploymentRuntimeExecution:
        """直接从请求 key 读取输入并返回固定结果。"""

        assert request.input_image_bytes is None
        assert request.input_uri == "runtime/transfers/request/input.bin"
        assert self.dataset_storage.resolve(request.input_uri).read_bytes() == b"input"
        return DeploymentRuntimeExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id="instance-object-store-preview",
            execution_result=self.execution_result,
        )


class _BatchRuntimePool:
    """核对 Batch worker 保持 mmap view 并只调用一次 runtime pool。"""

    def __init__(self, *, execution_result, fail_item_index: int | None = None) -> None:
        self.execution_result = execution_result
        self.fail_item_index = fail_item_index
        self.call_count = 0

    def run_inference_batch(self, *, config, requests) -> DeploymentRuntimeBatchExecution:
        """校验有序图片 view，或返回带 item_index 的输入错误。"""

        self.call_count += 1
        assert [request.input_image_bytes.tobytes() for request in requests] == [
            b"batch-image-0",
            b"batch-image-1",
        ]
        if self.fail_item_index is not None:
            from backend.service.application.errors import InvalidRequestError

            raise InvalidRequestError(
                "batch item invalid",
                details={"item_index": self.fail_item_index},
            )
        return DeploymentRuntimeBatchExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id="instance-batch",
            execution_results=(self.execution_result, self.execution_result),
        )


def test_deployment_worker_returns_preview_only_through_localbuffer(
    tmp_path: Path,
) -> None:
    """验证 worker 响应不携带图片 bytes/Base64，只返回 LocalBuffer 元数据。"""

    settings = LocalBufferBrokerSettings(
        arena_size_bytes=16 * 1024 * 1024,
        min_block_size_bytes=1024 * 1024,
        max_allocation_bytes=8 * 1024 * 1024,
        reader_guard_slots=4,
    )
    pool = LocalBufferArenaPool(
        MmapBufferArenaConfig(
            root_dir=tmp_path / "buffers",
            arena_id=settings.arena_id,
            arena_size_bytes=settings.arena_size_bytes,
            min_block_size_bytes=settings.min_block_size_bytes,
            max_allocation_bytes=settings.max_allocation_bytes,
            reader_guard_slots=settings.reader_guard_slots,
        )
    )
    input_lease = pool.allocate(
        content_length=len(b"input-image"),
        owner_kind="workflow-runtime",
        owner_id="run-1",
    )
    pool.write_lease_bytes(lease=input_lease, content=memoryview(b"input-image"))
    input_result = pool.commit_lease(lease=input_lease, media_type="image/jpeg")
    lease = pool.allocate(
        content_length=1024 * 1024,
        owner_kind="deployment-preview",
        owner_id="request-preview",
        ttl_seconds=60,
    )
    runtime_target = _build_runtime_target(tmp_path)
    preview_bytes = b"\xff\xd8\xffpreview-image"
    execution_result = replace(
        build_test_execution_result(runtime_target=runtime_target),
        preview_image_bytes=preview_bytes,
    )
    response_queue: Queue = Queue()
    infer_slots = BoundedSemaphore(1)
    assert infer_slots.acquire(blocking=False) is True

    writer = DirectMmapLocalBufferWriter(settings, root_dir=tmp_path / "buffers")
    reader = DirectMmapLocalBufferReader(settings, root_dir=tmp_path / "buffers")
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )
    try:
        _run_inference_request(
            response_queue=response_queue,
            request_id="request-preview",
            runtime_pool=_PreviewRuntimePool(execution_result=execution_result),
            runtime_pool_config=DeploymentRuntimePoolConfig(
                deployment_instance_id="deployment-preview",
                runtime_target=runtime_target,
            ),
            payload={
                "task_type": "detection",
                "prediction_request": {
                    "input_uri": None,
                    "input_image_payload": {
                        "transport_kind": "buffer",
                        "media_type": "image/jpeg",
                        "buffer_ref": input_result.buffer_ref.model_dump(mode="json"),
                    },
                    "score_threshold": 0.3,
                    "save_result_image": True,
                    "extra_options": {},
                },
                "preview_output_lease": lease.model_dump(mode="json"),
            },
            local_buffer_reader=reader,
            local_buffer_writer=writer,
            local_buffer_health=_LocalBufferBrokerRuntimeHealth(
                connected=True,
                channel_id="direct-mmap",
            ),
            dataset_storage=dataset_storage,
            infer_slots=infer_slots,
            keep_warm_state=None,
        )
    finally:
        reader.close()
        writer.close()

    response = response_queue.get_nowait()
    assert response["ok"] is True
    payload = response["payload"]
    assert payload["preview_image_transfer"] == {
        "size": len(preview_bytes),
        "media_type": "image/jpeg",
    }
    assert "preview_image_bytes" not in payload["execution_result"]
    assert "preview_image_bytes_base64" not in payload["execution_result"]
    output = pool.commit_lease(
        lease=lease,
        media_type="image/jpeg",
        content_length=len(preview_bytes),
    )
    assert pool.read_buffer_ref(output.buffer_ref) == preview_bytes
    pool.close()


def test_deployment_worker_batch_reads_ordered_mmap_views_and_releases_slot(
    tmp_path: Path,
) -> None:
    """验证 infer_batch 一次占用 slot、同序返回并正确释放 mmap reader guard。"""

    settings = LocalBufferBrokerSettings(
        arena_size_bytes=16 * 1024 * 1024,
        min_block_size_bytes=1024 * 1024,
        max_allocation_bytes=8 * 1024 * 1024,
        reader_guard_slots=4,
    )
    pool = LocalBufferArenaPool(
        MmapBufferArenaConfig(
            root_dir=tmp_path / "buffers",
            arena_id=settings.arena_id,
            arena_size_bytes=settings.arena_size_bytes,
            min_block_size_bytes=settings.min_block_size_bytes,
            max_allocation_bytes=settings.max_allocation_bytes,
            reader_guard_slots=settings.reader_guard_slots,
        )
    )
    buffer_refs = []
    for item_index in range(2):
        content = f"batch-image-{item_index}".encode()
        lease = pool.allocate(
            content_length=len(content),
            owner_kind="workflow-runtime",
            owner_id=f"run-batch-{item_index}",
        )
        pool.write_lease_bytes(lease=lease, content=memoryview(content))
        buffer_refs.append(
            pool.commit_lease(lease=lease, media_type="image/jpeg").buffer_ref
        )
    runtime_target = _build_runtime_target(tmp_path)
    execution_result = build_test_execution_result(runtime_target=runtime_target)
    runtime_pool = _BatchRuntimePool(execution_result=execution_result)
    response_queue: Queue = Queue()
    infer_slots = BoundedSemaphore(1)
    assert infer_slots.acquire(blocking=False) is True
    reader = DirectMmapLocalBufferReader(settings, root_dir=tmp_path / "buffers")
    health = _LocalBufferBrokerRuntimeHealth(
        connected=True,
        channel_id="direct-mmap",
    )
    try:
        _run_inference_batch_request(
            response_queue=response_queue,
            request_id="request-batch",
            runtime_pool=runtime_pool,
            runtime_pool_config=DeploymentRuntimePoolConfig(
                deployment_instance_id="deployment-batch",
                runtime_target=runtime_target,
            ),
            payload={
                "task_type": "detection",
                "prediction_requests": [
                    {
                        "input_uri": None,
                        "input_image_payload": {
                            "transport_kind": "buffer",
                            "media_type": "image/jpeg",
                            "buffer_ref": buffer_ref.model_dump(mode="json"),
                        },
                        "score_threshold": 0.3,
                        "save_result_image": False,
                        "extra_options": {},
                    }
                    for buffer_ref in buffer_refs
                ],
            },
            local_buffer_reader=reader,
            local_buffer_writer=None,
            local_buffer_health=health,
            dataset_storage=LocalDatasetStorage(
                DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
            ),
            infer_slots=infer_slots,
            keep_warm_state=None,
        )
    finally:
        reader.close()

    response = response_queue.get_nowait()
    assert response["ok"] is True
    assert response["payload"]["instance_id"] == "instance-batch"
    assert len(response["payload"]["execution_results"]) == 2
    assert runtime_pool.call_count == 1
    assert health.buffer_input_count == 2
    assert health.error_count == 0
    assert infer_slots.acquire(blocking=False) is True
    pool.close()


def test_batch_prediction_failure_is_not_counted_as_local_buffer_read_error(
    tmp_path: Path,
) -> None:
    """验证下游模型输入错误不会污染 LocalBuffer 读取健康计数。"""

    settings = LocalBufferBrokerSettings(
        arena_size_bytes=8 * 1024 * 1024,
        min_block_size_bytes=1024 * 1024,
        max_allocation_bytes=4 * 1024 * 1024,
        reader_guard_slots=4,
    )
    pool = LocalBufferArenaPool(
        MmapBufferArenaConfig(
            root_dir=tmp_path / "buffers",
            arena_id=settings.arena_id,
            arena_size_bytes=settings.arena_size_bytes,
            min_block_size_bytes=settings.min_block_size_bytes,
            max_allocation_bytes=settings.max_allocation_bytes,
            reader_guard_slots=settings.reader_guard_slots,
        )
    )
    refs = []
    for item_index in range(2):
        content = f"batch-image-{item_index}".encode()
        lease = pool.allocate(
            content_length=len(content),
            owner_kind="workflow-runtime",
            owner_id=f"run-error-{item_index}",
        )
        pool.write_lease_bytes(lease=lease, content=memoryview(content))
        refs.append(pool.commit_lease(lease=lease, media_type="image/jpeg").buffer_ref)
    runtime_target = _build_runtime_target(tmp_path)
    response_queue: Queue = Queue()
    infer_slots = BoundedSemaphore(1)
    assert infer_slots.acquire(blocking=False) is True
    reader = DirectMmapLocalBufferReader(settings, root_dir=tmp_path / "buffers")
    health = _LocalBufferBrokerRuntimeHealth(True, "direct-mmap")
    try:
        _run_inference_batch_request(
            response_queue=response_queue,
            request_id="request-batch-error",
            runtime_pool=_BatchRuntimePool(
                execution_result=build_test_execution_result(
                    runtime_target=runtime_target
                ),
                fail_item_index=1,
            ),
            runtime_pool_config=DeploymentRuntimePoolConfig(
                deployment_instance_id="deployment-batch-error",
                runtime_target=runtime_target,
            ),
            payload={
                "task_type": "detection",
                "prediction_requests": [
                    {
                        "input_image_payload": {
                            "transport_kind": "buffer",
                            "media_type": "image/jpeg",
                            "buffer_ref": ref.model_dump(mode="json"),
                        },
                        "score_threshold": 0.3,
                        "save_result_image": False,
                        "extra_options": {},
                    }
                    for ref in refs
                ],
            },
            local_buffer_reader=reader,
            local_buffer_writer=None,
            local_buffer_health=health,
            dataset_storage=LocalDatasetStorage(
                DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
            ),
            infer_slots=infer_slots,
            keep_warm_state=None,
        )
    finally:
        reader.close()

    response = response_queue.get_nowait()
    assert response["ok"] is False
    assert response["error"]["details"]["item_index"] == 1
    assert health.buffer_input_count == 2
    assert health.error_count == 0
    assert infer_slots.acquire(blocking=False) is True
    pool.close()


def test_async_deployment_worker_reads_and_writes_object_store_directly(
    tmp_path: Path,
) -> None:
    """验证异步 worker 不经过 LocalBuffer，直接消费和发布 ObjectStore 文件。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )
    input_key = "runtime/transfers/request/input.bin"
    output_key = "runtime/transfers/request/preview.bin"
    dataset_storage.write_bytes(input_key, b"input")
    runtime_target = _build_runtime_target(tmp_path)
    preview_bytes = b"\xff\xd8\xffpreview-image"
    execution_result = replace(
        build_test_execution_result(runtime_target=runtime_target),
        preview_image_bytes=preview_bytes,
    )
    response_queue: Queue = Queue()
    infer_slots = BoundedSemaphore(1)
    assert infer_slots.acquire(blocking=False) is True

    _run_inference_request(
        response_queue=response_queue,
        request_id="request-object-store-preview",
        runtime_pool=_ObjectStorePreviewRuntimePool(
            dataset_storage=dataset_storage,
            execution_result=execution_result,
        ),
        runtime_pool_config=DeploymentRuntimePoolConfig(
            deployment_instance_id="deployment-preview",
            runtime_target=runtime_target,
        ),
        payload={
            "task_type": "detection",
            "prediction_request": {
                "input_uri": input_key,
                "input_image_payload": {},
                "score_threshold": 0.3,
                "save_result_image": True,
                "extra_options": {},
            },
            "preview_output_object_key": output_key,
        },
        local_buffer_reader=None,
        local_buffer_writer=None,
        local_buffer_health=_LocalBufferBrokerRuntimeHealth(
            connected=False,
            channel_id=None,
        ),
        dataset_storage=dataset_storage,
        infer_slots=infer_slots,
        keep_warm_state=None,
    )

    response = response_queue.get_nowait()
    assert response["ok"] is True
    payload = response["payload"]
    assert payload["preview_image_transfer"] == {
        "object_key": output_key,
        "size": len(preview_bytes),
        "media_type": "image/jpeg",
    }
    assert "preview_image_bytes" not in payload["execution_result"]
    assert dataset_storage.resolve(output_key).read_bytes() == preview_bytes


def test_increment_safe_counter_normalizes_negative_value_and_rolls_over() -> None:
    """验证统一安全计数器会收敛负数，并在达到安全整数上限后 rollover。"""

    counter = SafeCounterState(value=-5, rollover_count=-3)

    assert counter.value == 0
    assert counter.rollover_count == 0

    counter.value = JSON_SAFE_INTEGER_MAX
    rolled_over = increment_safe_counter(counter)

    assert rolled_over is True
    assert counter.value == 1
    assert counter.rollover_count == 1


def test_process_runtime_configuration_keeps_lifecycle_and_backend_options_explicit(
    tmp_path: Path,
) -> None:
    """验证生命周期和 TensorRT 配置不再从 metadata 隐式读取。"""

    runtime_configuration = _runtime_configuration(
        lifecycle=DeploymentLifecycleOptions(
            warmup_dummy_inference_count=12,
            warmup_dummy_image_size=(80, 48),
            keep_warm_enabled=True,
            keep_warm_interval_seconds=0.2,
        ),
        backend_options=TensorRtRuntimeOptions(
            pinned_output_buffer_enabled=False,
            pinned_output_buffer_max_bytes=2_097_152,
        ),
    )
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-explicit-config",
        runtime_target=_build_runtime_target(tmp_path),
        runtime_configuration=runtime_configuration,
    )

    assert config.runtime_configuration == runtime_configuration
    assert config.instance_count == 1


def test_resolve_warmup_behavior_merges_supervisor_defaults_and_deployment_overrides(
    tmp_path: Path,
) -> None:
    """验证 worker 会优先使用 deployment 覆盖值，并保留 supervisor 默认值。"""

    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-keep-warm-1",
        runtime_target=_build_runtime_target(tmp_path),
        runtime_configuration=_runtime_configuration(
            lifecycle=DeploymentLifecycleOptions(
                warmup_dummy_inference_count=9,
                keep_warm_enabled=True,
            ),
        ),
    )
    behavior = _resolve_warmup_behavior(
        config=config,
        supervisor_settings=BackendServiceDeploymentProcessSupervisorConfig(
            warmup_dummy_inference_count=6,
            warmup_dummy_image_size=(64, 64),
            keep_warm_enabled=False,
            keep_warm_interval_seconds=0.1,
            keep_warm_yield_timeout_seconds=0.7,
        ).model_dump(mode="python"),
    )

    assert behavior == _DeploymentWarmupBehavior(
        warmup_dummy_inference_count=9,
        warmup_dummy_image_size=(64, 64),
        keep_warm_enabled=True,
        keep_warm_interval_seconds=0.1,
        keep_warm_yield_timeout_seconds=0.7,
    )


def test_run_dummy_warmup_passes_executes_requested_count(tmp_path: Path) -> None:
    """验证真实 warmup 会按指定次数执行 dummy infer。"""

    runtime_pool = _FakeRuntimePool()
    runtime_pool_config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-warmup-1",
        runtime_target=_build_runtime_target(tmp_path),
        runtime_configuration=_runtime_configuration(),
    )
    dummy_request = DetectionPredictionRequest(
        input_image_bytes=b"dummy-image-bytes",
        score_threshold=0.3,
        save_result_image=False,
        extra_options={"internal_request_kind": "test"},
    )

    _run_dummy_warmup_passes(
        runtime_pool=runtime_pool,
        runtime_pool_config=runtime_pool_config,
        dummy_request=dummy_request,
        count=3,
    )

    assert runtime_pool.call_count == 3
    assert runtime_pool.requests == [dummy_request, dummy_request, dummy_request]


def test_real_inference_does_not_implicitly_activate_keep_warm() -> None:
    """验证只有显式 warmup 才会开启设备保活。"""

    keep_warm_state = _KeepWarmState(
        dummy_request=DetectionPredictionRequest(
            input_image_bytes=b"dummy-image-bytes",
            score_threshold=0.3,
            save_result_image=False,
            extra_options={"internal_request_kind": "test"},
        )
    )

    _begin_real_inference(keep_warm_state)
    assert keep_warm_state.pause_event.is_set() is True

    _finish_real_inference(keep_warm_state)
    assert keep_warm_state.activated_event.is_set() is False
    assert keep_warm_state.pause_event.is_set() is False

    _activate_keep_warm(keep_warm_state)
    assert keep_warm_state.activated_event.is_set() is True


def test_keep_warm_loop_runs_after_activation_and_stops_cleanly(tmp_path: Path) -> None:
    """验证 keep-warm 线程激活后会执行 dummy infer，并能及时退出。"""

    keep_warm_state = _KeepWarmState(
        dummy_request=DetectionPredictionRequest(
            input_image_bytes=b"dummy-image-bytes",
            score_threshold=0.3,
            save_result_image=False,
            extra_options={"internal_request_kind": "test"},
        )
    )
    keep_warm_state.activated_event.set()
    runtime_pool = _FakeRuntimePool(stop_state=keep_warm_state)
    runtime_pool_config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-keep-warm-2",
        runtime_target=_build_runtime_target(tmp_path),
        runtime_configuration=_runtime_configuration(),
    )
    behavior = _DeploymentWarmupBehavior(
        warmup_dummy_inference_count=0,
        warmup_dummy_image_size=(64, 64),
        keep_warm_enabled=True,
        keep_warm_interval_seconds=0.01,
        keep_warm_yield_timeout_seconds=0.2,
    )

    thread = Thread(
        target=_run_keep_warm_loop,
        kwargs={
            "runtime_pool": runtime_pool,
            "runtime_pool_config": runtime_pool_config,
            "keep_warm_state": keep_warm_state,
            "behavior": behavior,
        },
        daemon=True,
    )
    thread.start()
    thread.join(timeout=0.5)

    assert runtime_pool.call_count == 1
    assert keep_warm_state.idle_event.is_set() is True
    assert keep_warm_state.success_counter.value == 1
    assert keep_warm_state.success_counter.rollover_count == 0
    assert keep_warm_state.error_counter.value == 0
    assert keep_warm_state.error_counter.rollover_count == 0
    assert thread.is_alive() is False


def test_real_inference_blocks_new_keep_warm_pass_and_waits_only_inflight_pass(
    tmp_path: Path,
) -> None:
    """验证真实请求会阻止新保活，并只等待已经开始的一轮设备调用。"""

    started_event = Event()
    release_event = Event()
    keep_warm_state = _KeepWarmState(
        dummy_request=DetectionPredictionRequest(
            input_image_bytes=b"dummy-image-bytes",
            score_threshold=0.3,
            save_result_image=False,
            extra_options={"internal_request_kind": "test"},
        )
    )
    keep_warm_state.activated_event.set()
    runtime_pool = _FakeRuntimePool(
        started_event=started_event,
        release_event=release_event,
    )
    runtime_pool_config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-keep-warm-priority",
        runtime_target=_build_runtime_target(tmp_path),
        runtime_configuration=_runtime_configuration(),
    )
    behavior = _DeploymentWarmupBehavior(
        warmup_dummy_inference_count=0,
        warmup_dummy_image_size=(64, 64),
        keep_warm_enabled=True,
        keep_warm_interval_seconds=0.01,
        keep_warm_yield_timeout_seconds=0.2,
    )
    thread = Thread(
        target=_run_keep_warm_loop,
        kwargs={
            "runtime_pool": runtime_pool,
            "runtime_pool_config": runtime_pool_config,
            "keep_warm_state": keep_warm_state,
            "behavior": behavior,
        },
        daemon=True,
    )
    thread.start()
    assert started_event.wait(timeout=0.2) is True
    assert keep_warm_state.idle_event.is_set() is False

    _begin_real_inference(keep_warm_state)
    assert keep_warm_state.pause_event.is_set() is True
    release_event.set()
    assert keep_warm_state.idle_event.wait(timeout=0.2) is True
    keep_warm_state.stop_event.set()
    _finish_real_inference(keep_warm_state)
    thread.join(timeout=0.5)

    assert runtime_pool.call_count == 1
    assert thread.is_alive() is False


def test_keep_warm_loop_rolls_success_counter_and_exposes_rollover_count(
    tmp_path: Path,
) -> None:
    """验证 keep-warm 成功计数到达安全上限后会 rollover，并继续通过快照对外可观测。"""

    keep_warm_state = _KeepWarmState(
        dummy_request=DetectionPredictionRequest(
            input_image_bytes=b"dummy-image-bytes",
            score_threshold=0.3,
            save_result_image=False,
            extra_options={"internal_request_kind": "test"},
        ),
        success_counter=SafeCounterState(value=JSON_SAFE_INTEGER_MAX),
    )
    keep_warm_state.activated_event.set()
    runtime_pool = _FakeRuntimePool(stop_state=keep_warm_state)
    runtime_pool_config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-keep-warm-rollover-1",
        runtime_target=_build_runtime_target(tmp_path),
        runtime_configuration=_runtime_configuration(),
    )
    behavior = _DeploymentWarmupBehavior(
        warmup_dummy_inference_count=0,
        warmup_dummy_image_size=(64, 64),
        keep_warm_enabled=True,
        keep_warm_interval_seconds=0.01,
        keep_warm_yield_timeout_seconds=0.2,
    )

    thread = Thread(
        target=_run_keep_warm_loop,
        kwargs={
            "runtime_pool": runtime_pool,
            "runtime_pool_config": runtime_pool_config,
            "keep_warm_state": keep_warm_state,
            "behavior": behavior,
        },
        daemon=True,
    )
    thread.start()
    thread.join(timeout=0.5)

    snapshot = _snapshot_keep_warm_state(
        behavior=behavior,
        keep_warm_state=keep_warm_state,
    )

    assert runtime_pool.call_count == 1
    assert snapshot["success_count"] == 1
    assert snapshot["success_count_rollover_count"] == 1
    assert snapshot["error_count"] == 0
    assert snapshot["error_count_rollover_count"] == 0


def test_snapshot_keep_warm_state_exposes_last_error(tmp_path: Path) -> None:
    """验证 keep-warm 状态快照会暴露最近一次失败错误。"""

    keep_warm_state = _KeepWarmState(
        dummy_request=DetectionPredictionRequest(
            input_image_bytes=b"dummy-image-bytes",
            score_threshold=0.3,
            save_result_image=False,
            extra_options={"internal_request_kind": "test"},
        ),
        error_counter=SafeCounterState(value=JSON_SAFE_INTEGER_MAX),
    )
    keep_warm_state.activated_event.set()
    runtime_pool = _FakeRuntimePool(
        stop_state=keep_warm_state,
        error_message="keep warm infer failed",
    )
    runtime_pool_config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-keep-warm-3",
        runtime_target=_build_runtime_target(tmp_path),
        runtime_configuration=_runtime_configuration(),
    )
    behavior = _DeploymentWarmupBehavior(
        warmup_dummy_inference_count=0,
        warmup_dummy_image_size=(64, 64),
        keep_warm_enabled=True,
        keep_warm_interval_seconds=0.01,
        keep_warm_yield_timeout_seconds=0.2,
    )

    thread = Thread(
        target=_run_keep_warm_loop,
        kwargs={
            "runtime_pool": runtime_pool,
            "runtime_pool_config": runtime_pool_config,
            "keep_warm_state": keep_warm_state,
            "behavior": behavior,
        },
        daemon=True,
    )
    thread.start()
    thread.join(timeout=0.5)

    snapshot = _snapshot_keep_warm_state(
        behavior=behavior,
        keep_warm_state=keep_warm_state,
    )

    assert snapshot["enabled"] is True
    assert snapshot["activated"] is True
    assert snapshot["success_count"] == 0
    assert snapshot["success_count_rollover_count"] == 0
    assert snapshot["error_count"] == 1
    assert snapshot["error_count_rollover_count"] == 1
    assert snapshot["last_error"] == "keep warm infer failed"


def test_snapshot_local_buffer_health_exposes_input_counts_and_recent_error() -> None:
    """验证 deployment worker 会在 health 中暴露 broker 输入计数和最近错误。"""

    broker_health = _LocalBufferBrokerRuntimeHealth(
        connected=True,
        channel_id="broker-channel-1",
        buffer_input_count=2,
        frame_input_count=1,
        error_count=1,
        last_error="broker read failed",
    )

    snapshot = _snapshot_local_buffer_health(
        local_buffer_reader=None,
        local_buffer_health=broker_health,
    )

    assert snapshot["connected"] is True
    assert snapshot["channel_id"] == "broker-channel-1"
    assert snapshot["buffer_input_count"] == 2
    assert snapshot["frame_input_count"] == 1
    assert snapshot["error_count"] == 1
    assert snapshot["recent_error"] == "broker read failed"


def _runtime_configuration(
    *,
    instance_count: int = 1,
    lifecycle: DeploymentLifecycleOptions | None = None,
    backend_options: TensorRtRuntimeOptions | None = None,
) -> DeploymentRuntimeConfiguration:
    """构造 TensorRT deployment 的显式运行时配置。"""

    return DeploymentRuntimeConfiguration(
        execution=DeploymentExecutionPolicy(instance_count=instance_count),
        lifecycle=lifecycle or DeploymentLifecycleOptions(),
        backend_options=backend_options or TensorRtRuntimeOptions(),
    )


def _build_runtime_target(tmp_path: Path) -> RuntimeTargetSnapshot:
    """构建测试使用的最小 runtime target。

    参数：
    - tmp_path：pytest 提供的临时目录。

    返回：
    - 可供 deployment process config 使用的最小 RuntimeTargetSnapshot。
    """

    runtime_artifact_path = tmp_path / "fake-runtime-artifact.engine"
    runtime_artifact_path.write_bytes(b"fake-runtime-artifact")
    return RuntimeTargetSnapshot(
        project_id="project-1",
        model_id="model-1",
        model_version_id="model-version-1",
        model_build_id="model-build-1",
        model_name="yolox-test",
        model_scale="nano",
        model_type="yolox",
        task_type="detection",
        source_kind="training_output",
        runtime_profile_id=None,
        runtime_backend="tensorrt",
        runtime_precision="fp16",
        device_name="cuda:0",
        input_size=(640, 640),
        labels=("bolt",),
        runtime_artifact_file_id="artifact-1",
        runtime_artifact_storage_uri=str(runtime_artifact_path),
        runtime_artifact_path=runtime_artifact_path,
        runtime_artifact_file_type="engine",
        checkpoint_file_id="checkpoint-1",
        checkpoint_storage_uri=str(runtime_artifact_path.with_suffix(".pth")),
        checkpoint_path=runtime_artifact_path,
        labels_storage_uri=str(runtime_artifact_path.with_suffix(".labels.txt")),
    )
