"""有界 Preview 进程池，长执行与 HTTP loop 和正式 Runtime 分离。"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
import multiprocessing
from queue import Empty, Full
from threading import Lock
from time import monotonic, perf_counter
import logging
import math
import psutil

from backend.service.application.errors import (
    OperationCancelledError, OperationTimeoutError, ServiceConfigurationError,
    ServiceError, WorkflowRuntimeBusyError,
)
from backend.service.application.workflows.preview_process import run_preview_process
from backend.service.application.workflows.worker.process import (
    close_local_buffer_broker_channel, close_published_inference_gateway_channel)


@dataclass
class _Slot:
    """一个常驻子进程及其私有控制通道；执行期间不允许复用。"""

    process: object = None
    requests: object = None
    responses: object = None
    cancellation: object = None
    broker: object = None
    gateway: object = None
    dispatcher: object = None
    busy: bool = False
    failed: bool = False


class PreviewExecutionPool:
    """容量满立即拒绝；每个应用最多一个预览，不积累无界任务队列。"""

    def __init__(self, *, settings, worker_manager):
        """复用已有 Broker/Gateway 通道装配，不改变正式 Runtime 数据面。"""
        self.settings = settings
        self.worker_manager = worker_manager
        self._context = multiprocessing.get_context("spawn")
        self._lock = Lock()
        self._stopping = False
        self._slots = [_Slot(cancellation=self._context.Event()) for _ in range(settings.workflow_runtime.preview_worker_count)]
        self._executor = ThreadPoolExecutor(max_workers=len(self._slots), thread_name_prefix="preview-control")
        self._active: dict[str, tuple[_Slot, Future, tuple[str, str]]] = {}
        owner = psutil.Process()
        self.owner_identity = {"pid": owner.pid, "create_time": owner.create_time()}

    @staticmethod
    def _identity_has_exited(identity):
        """PID 和启动时间共同判断所有者；权限不足或缺失身份时不推断死亡。"""
        if not isinstance(identity, dict) or not isinstance(identity.get("pid"), int):
            return False
        try:
            return abs(psutil.Process(identity["pid"]).create_time() - float(identity["create_time"])) > .001
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return True
        except (psutil.AccessDenied, KeyError, TypeError, ValueError):
            return False

    def reconcile(self, service, record):
        """查询时收敛已失去所有者的运行记录，活着的长任务绝不按时长判死。"""
        if record.state not in {"created", "running"}:
            return record
        if not self._identity_has_exited(record.metadata.get("preview_owner")):
            return record
        worker = record.metadata.get("preview_worker")
        if worker is not None and not self._identity_has_exited(worker):
            return record
        self._cleanup_upload(service, record.project_id, record.metadata.get("preview_owned_upload_root", ""))
        return service._finish_inline_preview_run_failed(
            record.preview_run_id, ServiceConfigurationError("Preview 执行所属服务已退出，任务已中断"),
            inline_started_at=perf_counter(), graph_execute_ms=0, event_persist_ms=0)

    @staticmethod
    def _cleanup_upload(service, project_id, upload_root):
        """仅回收路由持有的随机上传目录，不能接受任意删除路径。"""
        prefix = f"workflows/runtime-inputs/{project_id}/preview/"
        suffix = upload_root.removeprefix(prefix) if isinstance(upload_root, str) else ""
        if (isinstance(upload_root, str) and upload_root.startswith(prefix) and len(suffix) == 32
                and all(char in "0123456789abcdef" for char in suffix)):
            service.dataset_storage.delete_tree(upload_root)
            if service.dataset_storage.resolve(upload_root).exists():
                raise OSError("Preview 上传输入仍有残留")

    def submit(self, service, request):
        """登记执行所有权后返回 Future；只携带引用和控制数据进入执行进程。"""
        scope = (request.project_id, request.application_id)
        with self._lock:
            slot = next((item for item in self._slots if not item.busy and not item.failed), None)
            if self._stopping or slot is None or any(item[2] == scope for item in self._active.values()):
                raise WorkflowRuntimeBusyError("Preview 执行资源繁忙，请等待当前预览完成")
            slot.busy = True
            slot.cancellation.clear()
            future = self._executor.submit(self._execute, slot, service, request)
            self._active[request.preview_run_id] = (slot, future, scope)
        future.add_done_callback(lambda done: self._finished(request.preview_run_id, slot))
        return future

    def _finished(self, run_id, slot):
        """完成后释放容量，结果和历史保留在既有 Preview 存储中。"""
        with self._lock:
            self._active.pop(run_id, None)
            slot.busy = False

    def cancel(self, run_id: str) -> bool:
        """只请求协作取消；资源直到真实执行结束才释放。"""
        with self._lock:
            active = self._active.get(run_id)
            if active is None:
                return False
            if active[0].cancellation is not None:
                active[0].cancellation.set()
            return True

    def _receive(self, slot, deadline=None, *, execution=False, service=None):
        """只观察执行进程和控制消息，任务耗时不参与 HTTP 存活判断。"""
        cancellation_started = None
        expired_node = None
        invocations = {}
        while True:
            try:
                message = slot.responses.get(timeout=.1)
            except Empty:
                message = None
                if not slot.process.is_alive():
                    raise ServiceConfigurationError("Preview 执行进程已退出", details={"exit_code": slot.process.exitcode})
                if not execution and deadline is not None and monotonic() >= deadline:
                    raise ServiceConfigurationError("Preview 执行进程启动超时")
            if not execution:
                if message is not None:
                    return message
                if slot.cancellation.is_set():
                    if cancellation_started is None:
                        cancellation_started = monotonic()
                    if monotonic() - cancellation_started >= 5:
                        self._terminate(slot)
                        raise OperationCancelledError("Preview 启动已取消")
                continue
            if message is not None:
                kind, payload = message
                if kind == "preview-event":
                    try:
                        service.preview_run_manager._publish_preview_run_event(payload)
                        service.preview_run_manager._publish_project_summary_event(payload.preview_run_id, payload)
                    except Exception:
                        logging.getLogger(__name__).exception("Preview 实时事件分发失败，保留 JSONL 回放")
                elif kind == "node":
                    invocation = str(payload.get("node_invocation_id", ""))
                    if payload.get("message_type") == "node-ended":
                        invocations.pop(invocation, None)
                    elif payload.get("message_type") == "node-started":
                        node_deadline = payload.get("deadline_monotonic")
                        grace = payload.get("kill_grace_seconds")
                        if (isinstance(node_deadline, (int, float)) and math.isfinite(node_deadline)
                                and isinstance(grace, (int, float)) and math.isfinite(grace) and grace >= 0):
                            invocations[invocation] = (node_deadline, grace)
                else:
                    return message
            now = monotonic()
            due = [value for value in invocations.values() if value[0] <= now]
            if due and expired_node is None:
                expired_node = min(due, key=lambda value: value[0] + value[1])
            timed_out = expired_node is not None or deadline is not None and now >= deadline
            if timed_out:
                slot.cancellation.set()
            if slot.cancellation.is_set():
                if cancellation_started is None:
                    cancellation_started = now
                force_deadline = (expired_node[0] + expired_node[1] if expired_node is not None
                                  else cancellation_started + 5)
                if now >= force_deadline:
                    self._terminate(slot)
                    if timed_out:
                        raise OperationTimeoutError("Preview 执行超过声明的 timeout，执行进程已停止")
                    raise OperationCancelledError("Preview 已取消，执行进程已停止")

    def _terminate(self, slot):
        """仅处理本池拥有的进程；确认退出后调用方才可释放输入。"""
        slot.cancellation.set()
        if slot.process.is_alive():
            slot.process.terminate()
            slot.process.join(5)
        if slot.process.is_alive():
            raise ServiceConfigurationError("Preview 进程未退出，保留输入与槽位所有权")

    def _start(self, slot):
        """首次执行延迟启动，后续复用进程、注册表和模型缓存。"""
        if slot.process is not None:
            if slot.process.is_alive():
                return
            self._close_slot(slot)
        slot.requests = self._context.Queue(maxsize=1)
        slot.responses = self._context.Queue(maxsize=1)
        slot.broker = self.worker_manager._resolve_local_buffer_broker_event_channel()
        slot.gateway = self.worker_manager._build_published_inference_gateway_channel()
        slot.dispatcher = self.worker_manager._build_published_inference_gateway_dispatcher(slot.gateway)
        if slot.dispatcher is not None:
            slot.dispatcher.start()
        slot.process = self._context.Process(target=run_preview_process, kwargs={
            "settings_payload": self.settings.model_dump(mode="python"),
            "requests": slot.requests, "responses": slot.responses,
            "cancellation": slot.cancellation, "broker_channel": slot.broker,
            "gateway_channel": slot.gateway}, name="workflow-preview")
        slot.process.start()
        kind, _ = self._receive(slot, monotonic() + self.settings.workflow_runtime.model_startup_timeout_seconds)
        if kind != "ready":
            raise ServiceConfigurationError("Preview 执行进程未就绪")

    def _execute(self, slot, service, request):
        """阻塞等待在专用控制线程内进行；失败也写入已有 Preview 终态。"""
        started = perf_counter()
        completed = False
        try:
            self._start(slot)
            with service._open_unit_of_work() as unit_of_work:
                record = service._require_preview_run(unit_of_work, request.preview_run_id)
                process = psutil.Process(slot.process.pid)
                unit_of_work.workflow_runtime.save_preview_run(replace(record, metadata={
                    **record.metadata, "preview_worker": {"pid": process.pid, "create_time": process.create_time()}}))
                unit_of_work.commit()
            slot.requests.put(request)
            kind, result = self._receive(slot, monotonic() + request.timeout_seconds, execution=True, service=service)
            completed = kind in {"result", "error"}
            if kind != "result":
                raise ServiceConfigurationError("Preview 执行失败", details={"reason": result})
            return result
        except Exception as error:
            slot.failed = not completed
            if not completed and slot.process is not None and slot.process.is_alive():
                # 控制通道损坏时仍可能有活跃节点；取消后必须确认进程退出，
                # 才能宣布失败并释放输入。期间槽位保持占用，排空明确失败。
                try:
                    self._terminate(slot)
                except ServiceConfigurationError:
                    logging.getLogger(__name__).exception("Preview 进程停止失败，继续保留资源所有权")
                while slot.process.is_alive():
                    slot.process.join(.5)
            # 已确认死亡的进程可在下次接入时重建，不能永久耗尽容量。
            if slot.process is not None and not slot.process.is_alive():
                slot.failed = False
            result = service._finish_inline_preview_run_failed(
                request.preview_run_id, error if isinstance(error, ServiceError) else ServiceConfigurationError(str(error)[:1024]),
                inline_started_at=started, graph_execute_ms=0, event_persist_ms=0)
            service._append_inline_terminal_event(
                request.preview_run_id, event_type=f"preview.{result.state}",
                message=result.error_message or "Preview 执行结束", payload={"state": result.state})
            return result
        finally:
            if request.owned_upload_root:
                try:
                    self._cleanup_upload(service, request.project_id, request.owned_upload_root)
                except Exception:
                    logging.getLogger(__name__).exception("Preview 输入清理失败: %s", request.preview_run_id)

    def _close_slot(self, slot):
        """只在子进程确认退出后关闭通道，不提前破坏共享内存使用者。"""
        if slot.process is not None:
            if slot.process.pid is None:
                slot.process.close()
                slot.process = None
            else:
                self._stop_process(slot)
        if slot.dispatcher is not None:
            slot.dispatcher.stop()
        close_local_buffer_broker_channel(slot.broker)
        close_published_inference_gateway_channel(slot.gateway)
        for queue in (slot.requests, slot.responses):
            if queue is not None:
                # 子进程可能在读取请求之前退出；此时 feeder 无消费者，不能无限 join。
                queue.cancel_join_thread()
                queue.close()
        slot.process = None

    def _stop_process(self, slot):
        """等待执行进程按正常 finally 释放模型和上下文。"""
        if slot.process is not None:
            if slot.process.is_alive():
                try:
                    slot.requests.put(None, timeout=.5)
                    slot.process.join(15)
                except Full:
                    # 仅在已排空或启动失败的槽位关闭路径执行，不能无限等待 feeder。
                    self._terminate(slot)
            if slot.process.is_alive():
                self._terminate(slot)
            slot.process.close()

    def close(self):
        """停止新接入，协作取消已有执行；排空失败时阻止整栈释放依赖。"""
        with self._lock:
            self._stopping = True
            active = tuple(self._active.values())
            for slot, _, _ in active:
                if slot.cancellation is not None:
                    slot.cancellation.set()
        _, pending = wait([item[1] for item in active], timeout=30)
        if pending:
            raise ServiceConfigurationError("Preview 执行尚未结束，不能释放输入和运行时依赖")
        self._executor.shutdown(wait=True)
        for slot in self._slots:
            self._close_slot(slot)
