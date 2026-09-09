"""编辑态 Preview 常驻执行进程；复用节点执行和模型会话，不启动 HTTP 或 Trigger。"""

from __future__ import annotations

from contextlib import ExitStack
from queue import Empty

from backend.service.application.workflows.worker import process as runtime_process
from backend.service.application.workflows.preview_run_manager import WorkflowPreviewRunManager


class _ProcessPreviewRunManager(WorkflowPreviewRunManager):
    """子进程只写一次 JSONL，父进程负责既有 WebSocket 与项目摘要分发。"""

    def _publish_preview_run_event(self, event):
        """先刷新文件，再发送小型事件，保证回放与 live 使用相同序号。"""
        self.flush_event_stream(event.preview_run_id)
        self.responses.put(("preview-event", event))

    def _publish_project_summary_event(self, preview_run_id, event):
        """摘要在父进程发布，避免重复读取和重复通知。"""


def refresh_preview_node_resources(loader, catalog, registry_loader, models, cache, signature):
    """空闲边界一致刷新目录和执行器；同版本继续复用模型，失败由调用方回收槽位。"""
    loader.refresh()
    next_signature = tuple(item.model_dump_json() for item in loader.get_node_pack_manifests())
    if next_signature != signature:
        models.close_all()
        cache.clear()
        catalog.invalidate_cache()
        registry_loader.refresh()
    return next_signature


def run_preview_process(settings_payload, requests, responses, cancellation, broker_channel, gateway_channel):
    """串行执行编辑快照，进程内独占 registry、SessionFactory 和模型缓存。"""

    from backend.service.application.workflows.runtime_service import WorkflowRuntimeService

    runtime_process.configure_managed_child_signals()
    parent = runtime_process.multiprocessing.parent_process()
    with ExitStack() as resources:
        watch_stop = runtime_process.Event()
        watch = runtime_process.Thread(target=runtime_process._run_supervisor_watchdog, kwargs={
            "supervisor_process": parent, "stop_event": watch_stop,
            "supervisor_lost_event": runtime_process.Event(), "run_cancellation_event": cancellation},
            name="preview-parent-watchdog", daemon=True)
        watch.start()
        def stop_watch():
            """资源清理结束后停止父进程监视线程。"""
            watch_stop.set()
            watch.join(1)
        resources.callback(stop_watch)
        settings = runtime_process.BackendServiceSettings.model_validate(settings_payload)
        runtime_process.configure_workflow_process_threads(settings.workflow_runtime.operator_thread_count)
        sessions = runtime_process.SessionFactory(settings.to_database_settings())
        resources.callback(sessions.engine.dispose)
        storage = runtime_process.LocalDatasetStorage(settings.to_dataset_storage_settings())
        reader = runtime_process.build_local_buffer_reader(broker_channel)
        if reader is not None:
            resources.callback(reader.close)
        gateway = runtime_process.build_published_inference_gateway(gateway_channel)
        if gateway is not None:
            resources.callback(gateway.close)
        loader = runtime_process.LocalNodePackLoader(settings.custom_nodes.root_dir)
        loader.refresh()
        catalog = runtime_process.NodeCatalogRegistry(node_pack_loader=loader)
        registry_loader = runtime_process.WorkflowNodeRuntimeRegistryLoader(
            node_catalog_registry=catalog, node_pack_loader=loader)
        registry_loader.refresh()
        catalog_signature = tuple(item.model_dump_json() for item in loader.get_node_pack_manifests())
        registry = registry_loader.get_runtime_registry()
        models = runtime_process.WorkflowModelSessionManager(
            runtime_registry=registry, max_parallel_loads=settings.workflow_runtime.model_startup_parallelism)
        cache = runtime_process.ExecutionImageRegistry(
            decoded_cache_max_entries=settings.workflow_runtime.storage_image_cache_max_entries,
            decoded_cache_max_bytes=settings.workflow_runtime.storage_image_cache_max_bytes)
        resources.callback(cache.clear)
        supervisors = {}
        for mode in ("sync", "async"):
            supervisor = runtime_process.LazyDeploymentProcessSupervisor(
                dataset_storage_root_dir=str(storage.root_dir), runtime_mode=mode,
                settings=settings.deployment_process_supervisor,
                local_buffer_broker_event_channel=reader.channel if reader is not None else None)
            resources.callback(supervisor.stop)
            for task in ("detection", "classification", "segmentation", "pose", "obb"):
                supervisors[f"{task}_{mode}_deployment_process_supervisor"] = supervisor
        context = runtime_process.WorkflowServiceNodeRuntimeContext(
            session_factory=sessions, dataset_storage=storage, **supervisors,
            async_inference_service_id="workflow-preview", local_buffer_reader=reader,
            published_inference_gateway=gateway, workflow_model_session_manager=models,
            workflow_storage_image_cache=cache)
        resources.callback(context.close)
        previews = _ProcessPreviewRunManager(session_factory=sessions, dataset_storage=storage)
        previews.responses = responses
        resources.callback(previews.close)
        # 正常退出先卸载模型，再关闭其依赖的上下文与 supervisor。
        resources.callback(models.close_all)
        service = WorkflowRuntimeService(
            settings=settings, session_factory=sessions, dataset_storage=storage,
            node_catalog_registry=catalog, worker_manager=None,
            workflow_node_runtime_registry=registry, workflow_service_node_runtime_context=context,
            preview_run_manager=previews, published_inference_gateway=gateway)
        service.preview_cancellation_event = cancellation
        service.preview_node_lifecycle_sink = lambda message: responses.put(("node", message))
        responses.put(("ready", None))
        while parent is None or parent.is_alive():
            try:
                request = requests.get(timeout=.5)
            except Empty:
                continue
            if request is None:
                return
            refreshing = True
            try:
                catalog_signature = refresh_preview_node_resources(
                    loader, catalog, registry_loader, models, cache, catalog_signature)
                refreshing = False
                result = service._execute_preview_run_inline(
                    request.preview_run_id, request,
                    retain_node_records_enabled=request.retain_node_records_enabled,
                    return_sync_response_payload_enabled=request.return_sync_response_payload_enabled)
                responses.put(("result", result))
            except Exception as error:
                # 只传稳定的错误类型和有界文本，不序列化任意异常对象。
                responses.put(("error", f"{type(error).__name__}: {str(error)[:1024]}"))
                if refreshing:
                    # 半更新的 handler/schema 不能进入下一次运行，由池重建本槽位。
                    return
