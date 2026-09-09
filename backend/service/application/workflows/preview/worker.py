"""常驻 Preview Worker 的内存执行入口，重任务不进入 HTTP loop。"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from base64 import b64encode
from queue import Empty
from multiprocessing.shared_memory import SharedMemory

from backend.service.application.workflows.worker import process as runtime_process
from backend.service.application.workflows.preview.events import PreviewNodeEvents
from backend.service.application.workflows.preview.execution import PreviewMemoryExecutionRequest, PreviewMemoryExecutionService
from backend.service.application.workflows.preview.bridge import PreviewMemoryBridge
from backend.service.application.workflows.preview.display import PreviewDisplayCapture
from backend.service.application.workflows.preview.models import PreviewModelGateway
from backend.service.application.workflows.preview.inputs import PreviewInputStore


def refresh_node_resources(loader, catalog, registry_loader, models, cache, signature):
    """只在空闲边界一致刷新，沿用上一轮已经验证的目录失效逻辑。"""
    loader.refresh()
    next_signature = tuple(item.model_dump_json() for item in loader.get_node_pack_manifests())
    if next_signature != signature:
        models.close_all()
        cache.clear()
        catalog.invalidate_cache()
        registry_loader.refresh()
    return next_signature


def run_preview_worker(settings_payload, requests, responses, cancellation, replies):
    """只消费内存请求和发送控制事件；进程数、退出及超时由父进程监督。"""
    from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
    from backend.service.application.errors import OperationCancelledError, OperationTimeoutError

    runtime_process.configure_managed_child_signals()
    parent = runtime_process.multiprocessing.parent_process()
    with ExitStack() as resources:
        watch_stop = runtime_process.Event()
        watch = runtime_process.Thread(target=runtime_process._run_supervisor_watchdog, kwargs={
            "supervisor_process": parent, "stop_event": watch_stop,
            "supervisor_lost_event": runtime_process.Event(), "run_cancellation_event": cancellation},
            name="preview-session-parent-watchdog", daemon=True)
        watch.start()

        def stop_watch():
            """模型与上下文退出后才停止父进程监视。"""
            watch_stop.set()
            watch.join(1)

        resources.callback(stop_watch)
        settings = runtime_process.BackendServiceSettings.model_validate(settings_payload)
        runtime_process.configure_workflow_process_threads(settings.workflow_runtime.operator_thread_count)
        sessions = runtime_process.SessionFactory(settings.to_database_settings())
        resources.callback(sessions.engine.dispose)
        storage = runtime_process.LocalDatasetStorage(settings.to_dataset_storage_settings())
        loader = runtime_process.LocalNodePackLoader(settings.custom_nodes.root_dir)
        loader.refresh()
        catalog = runtime_process.NodeCatalogRegistry(node_pack_loader=loader)
        registry_loader = runtime_process.WorkflowNodeRuntimeRegistryLoader(node_catalog_registry=catalog, node_pack_loader=loader)
        registry_loader.refresh()
        registry = registry_loader.get_runtime_registry()
        signature = tuple(item.model_dump_json() for item in loader.get_node_pack_manifests())
        models = runtime_process.WorkflowModelSessionManager(
            runtime_registry=registry, max_parallel_loads=settings.workflow_runtime.model_startup_parallelism)
        cache = runtime_process.ExecutionImageRegistry(
            decoded_cache_max_entries=settings.workflow_runtime.storage_image_cache_max_entries,
            decoded_cache_max_bytes=settings.workflow_runtime.storage_image_cache_max_bytes)
        resources.callback(cache.clear)
        context = runtime_process.WorkflowServiceNodeRuntimeContext(
            session_factory=sessions, dataset_storage=storage,
            workflow_model_session_manager=models, workflow_storage_image_cache=cache)
        gateway = PreviewModelGateway(context)
        context = replace(context, published_inference_gateway=gateway)
        resources.callback(context.close)
        resources.callback(gateway.close)
        resources.callback(models.close_all)
        responses.put(("ready", {}), timeout=2)
        while parent is None or parent.is_alive():
            try:
                message = requests.get(timeout=.5)
            except Empty:
                continue
            if message is None:
                return
            refreshing = True
            displays = None
            images = runtime_process.ExecutionImageRegistry()
            input_store = PreviewInputStore(storage, message["project_id"], message["session_id"])
            try:
                previous_signature = signature
                signature = refresh_node_resources(loader, catalog, registry_loader, models, cache, signature)
                if signature != previous_signature:
                    gateway.close()
                gateway.begin_run()
                models.enforce_scope_limit(scope_prefix="preview-session:", current_scope_id=f"preview-session:{message['session_id']}",
                                           max_scope_count=settings.workflow_runtime.preview_model_session_scope_limit)
                refreshing = False

                def emit(kind, payload):
                    """有界控制交接；通道损坏需使当前执行失败而非静默丢消息。"""
                    responses.put(("event", {"type": kind, "payload": payload}), timeout=2)

                emit("run.started", {})
                body = message["request"]
                from backend.nodes.runtime_support import build_memory_image_payload
                bindings = dict(body.get("input_bindings", {}))
                application = FlowApplication.model_validate(body["application"])
                template = WorkflowGraphTemplate.model_validate(body["template"])
                ports = {port.input_id: port.payload_type_id for port in template.template_inputs}
                input_types = {binding.binding_id: ports.get(binding.template_port_id) for binding in application.bindings if binding.direction == "input"}
                bridge = PreviewMemoryBridge(responses, replies)
                for binding, descriptors in message.get("inputs", {}).items():
                    payload_type = input_types.get(binding)
                    if payload_type not in {"image-ref.v1", "image-base64.v1", "file-ref.v1", "file-refs.v1"}:
                        raise ValueError("preview_input_type_invalid")
                    if payload_type != "file-refs.v1" and len(descriptors) != 1:
                        raise ValueError("preview_input_file_count_invalid")
                    payloads = []
                    for descriptor in descriptors:
                        memory = SharedMemory(name=descriptor["name"])
                        try:
                            content = bytes(memory.buf[:descriptor["byte_length"]])
                        finally:
                            memory.close()
                        if payload_type == "image-ref.v1":
                            entry = images.register_image_bytes(content=content, media_type=descriptor["media_type"])
                            payload = build_memory_image_payload(image_handle=entry.image_handle, media_type=entry.media_type)
                        elif payload_type == "image-base64.v1":
                            payload = {"image_base64": b64encode(content).decode("ascii"), "media_type": descriptor["media_type"]}
                        else:
                            payload = input_store.register(content, media_type=descriptor["media_type"], file_name=descriptor["file_name"])
                        payloads.append(payload)
                        retained_bytes = len(payload["image_base64"]) if payload_type == "image-base64.v1" else len(content)
                        del content
                        bridge.call("input-consumed", blob_id=descriptor["blob_id"], byte_length=retained_bytes)
                    bindings[binding] = {"items": payloads, "count": len(payloads)} if payload_type == "file-refs.v1" else payloads[0]
                events = PreviewNodeEvents(emit, (node.node_id for node in template.nodes))
                displays = PreviewDisplayCapture(bridge, emit, events)
                scope = body.get("execution_scope", {})
                execution = PreviewMemoryExecutionRequest(
                    project_id=message["project_id"], application_id=message["application_id"],
                    application=application, template=template,
                    session_id=message["session_id"], input_bindings=bindings,
                    execution_metadata={"workflow_run_id": message["run_id"], "retain_node_records_enabled": False,
                                        "debug_image_panels_enabled": True,
                                        "execution_image_registry": images, "_runtime_preview_capture": displays,
                                        "_editor_preview_image_sink": displays.image, "_editor_preview_video_sink": displays.video,
                                        "_editor_preview_observer": events},
                    target_node_id=scope.get("target_node_id") if scope.get("kind") == "node" else None)
                result = PreviewMemoryExecutionService(
                    dataset_storage=input_store, node_catalog_registry=catalog, runtime_registry=registry,
                    runtime_context=context, event_sink=events, node_cancellation_event=cancellation,
                    node_lifecycle_sink=lambda payload: responses.put(("lifecycle", payload), timeout=2),
                    decoded_image_cache_max_entries=settings.workflow_runtime.decoded_image_cache_max_entries,
                    decoded_image_cache_max_bytes=settings.workflow_runtime.decoded_image_cache_max_bytes,
                ).execute(execution)
                displays.close()
                output_value = displays.values.describe(displays.resolve_outputs(result.outputs))
                outputs = output_value["value"] if output_value["kind"] == "inline" else {"preview_value": output_value}
                responses.put(("finished", {"status": "succeeded", "outputs": outputs}), timeout=2)
            except Exception as error:
                if displays is not None:
                    try:
                        displays.close()
                    except Exception:
                        # 原始业务异常优先；父进程仍能收到终态并回收所有权。
                        pass
                status = ("cancelled" if isinstance(error, OperationCancelledError) else
                          "timed_out" if isinstance(error, OperationTimeoutError) else "failed")
                responses.put(("finished", {"status": status, "error": {
                    "message": str(error)[:1024], "type": type(error).__name__,
                    "details": str(getattr(error, "details", {}))[:2048],
                    "node_id": getattr(error, "details", {}).get("node_id")}}), timeout=2)
                if refreshing:
                    return
            finally:
                images.clear()
                input_store.clear()
