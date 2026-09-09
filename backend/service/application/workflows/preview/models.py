"""Preview 内的模型网关；复用 task-native ModelRuntime，不进入正式部署 IPC。"""

from collections import OrderedDict
from threading import RLock
from time import perf_counter
from contextlib import contextmanager

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.deployments.published_inference_gateway import (
    PublishedInferenceBatchResult, _build_prediction_request, _build_published_inference_result,
    _normalize_task_type, _validate_batch_request,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.deployment.deployment_runtime_pool import DeploymentRuntimePool, DeploymentRuntimePoolConfig
from backend.service.application.workflows.service_runtime.builders import build_deployment_service


class PreviewModelGateway:
    """模型加载、预测和关闭都位于 Preview Worker，缓存有界且空闲时回收。"""

    def __init__(self, context, *, max_deployments=16):
        """上下文提供部署读取和本地模型文件；不访问正式 Runtime 对象。"""
        self.context = context
        self.pool = DeploymentRuntimePool(dataset_storage=context.dataset_storage)
        self.max_deployments = max_deployments
        self.deployments = OrderedDict()
        self.configurations = {}
        self.lock = RLock()

    def _config(self, request):
        """每次解析当前部署快照，runtime pool 按配置签名决定是否重载。"""
        task = _normalize_task_type(request.task_type)
        if request.runtime_mode != "sync":
            raise InvalidRequestError("Preview 模型调用要求同步返回节点结果")
        config = self.configurations.get(request.deployment_instance_id)
        if config is None:
            config = build_deployment_service(self.context, task_type=task).resolve_process_config(request.deployment_instance_id)
        if config.runtime_target.task_type != task:
            raise InvalidRequestError("部署模型任务类型与节点不一致")
        key = config.deployment_instance_id
        if key not in self.deployments:
            while len(self.deployments) >= self.max_deployments:
                stale = next((key for key, active in self.deployments.items() if not active), None)
                if stale is None:
                    raise InvalidRequestError("Preview 同时使用的模型数量超过缓存容量")
                self.pool.close_deployment(stale)
                del self.deployments[stale]
                self.configurations.pop(stale, None)
            self.deployments[key] = 0
        self.configurations[key] = config
        self.deployments.move_to_end(key)
        return DeploymentRuntimePoolConfig(deployment_instance_id=key, runtime_target=config.runtime_target,
                                           runtime_configuration=config.effective_runtime_configuration or config.runtime_configuration,
                                           requested_runtime_configuration=config.runtime_configuration)

    def begin_run(self):
        """运行边界刷新部署配置，保留模型池；同一次运行使用一致的部署配置。"""
        with self.lock:
            self.configurations.clear()

    @contextmanager
    def _lease(self, request):
        """只锁定配置登记，预测由原有实例池并发调度，活动模型不能被逐出。"""
        with self.lock:
            config = self._config(request)
            self.deployments[config.deployment_instance_id] += 1
        try:
            yield config
        finally:
            with self.lock:
                self.deployments[config.deployment_instance_id] -= 1

    def infer(self, request):
        """原始预测请求和结果序列化保持一致，不改变阈值、预处理或后处理。"""
        with self._lease(request) as config:
            prediction = _build_prediction_request(task_type=request.task_type, request=request,
                                                   normalized_image_payload=require_image_payload(request.image_payload))
            execution = self.pool.run_inference(config=config, request=prediction)
            return _build_published_inference_result(task_type=request.task_type, deployment_instance_id=execution.deployment_instance_id,
                                                     instance_id=execution.instance_id, execution_result=execution.execution_result)

    def infer_batch(self, request):
        """批量调用复用既有批次验证及 reserved-instance 执行语义。"""
        items = _validate_batch_request(request)
        with self._lease(items[0]) as config:
            predictions = tuple(_build_prediction_request(task_type=item.task_type, request=item,
                                                          normalized_image_payload=require_image_payload(item.image_payload)) for item in items)
            started = perf_counter()
            execution = self.pool.run_inference_batch(config=config, requests=predictions)
            return PublishedInferenceBatchResult(task_type=items[0].task_type, deployment_instance_id=execution.deployment_instance_id,
                instance_id=execution.instance_id, batch_latency_ms=(perf_counter() - started) * 1000,
                results=tuple(_build_published_inference_result(task_type=items[0].task_type, deployment_instance_id=execution.deployment_instance_id,
                    instance_id=execution.instance_id, execution_result=result) for result in execution.execution_results),
                metadata={"count": len(items), "execution_mode": "sequential-reserved-instance"})

    def close(self):
        """必须在图执行结束后关闭，避免释放仍被节点使用的模型对象。"""
        with self.lock:
            if any(self.deployments.values()):
                raise RuntimeError("preview_models_still_active")
            for key in list(self.deployments):
                self.pool.close_deployment(key)
                del self.deployments[key]
            self.configurations.clear()
