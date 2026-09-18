"""从当前控制面采集视觉服务状态，仅由后台监控调用。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.ipc.service_status_channel import (
    read_inference_status,
)

if TYPE_CHECKING:
    from backend.service.api.bootstrap import BackendServiceRuntime


def status_item(
    kind: str, resource_id: str, ready: bool, code: str, **details: object
) -> dict[str, object]:
    """构造稳定状态字段，不携带磁盘路径、业务数据和历史业务错误。"""
    return {
        "kind": kind,
        "id": resource_id,
        "ready": ready,
        "code": "ok" if ready else code,
        **details,
    }


class ServiceStatusCollector:
    """复用既有资源期望状态与当前进程观测，不启动或修复任何组件。"""

    def __init__(self, runtime: BackendServiceRuntime) -> None:
        """绑定当前 HTTP 服务装配的资源。"""
        self.runtime = runtime
        self._dependencies: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {}
        self._model_modes = {
            definition.node_type_id: definition.runtime_requirements[
                "deployment_process"
            ]
            for definition in runtime.node_catalog_registry.get_workflow_node_definitions()
            if definition.runtime_requirements.get("deployment_process")
            in {"sync", "async"}
        }

    def _model_dependencies(self, workflow) -> tuple[tuple[str, str], ...]:
        """按节点声明缓存发布版本的静态部署依赖，不读取草稿或执行节点。"""
        key = (workflow.workflow_runtime_id, workflow.active_revision_id)
        if key not in self._dependencies:
            template = self.runtime.dataset_storage.read_json(
                workflow.template_snapshot_object_key
            )
            self._dependencies[key] = tuple(
                sorted(
                    {
                        (
                            node["parameters"]["deployment_instance_id"],
                            self._model_modes[node["node_type_id"]],
                        )
                        for node in template.get("nodes", [])
                        if node.get("enabled", True)
                        and node.get("node_type_id") in self._model_modes
                        and isinstance(
                            node.get("parameters", {}).get("deployment_instance_id"),
                            str,
                        )
                    }
                )
            )
        return self._dependencies[key]

    def __call__(self) -> list[dict[str, object]]:
        """采集完整资源清单；数据库失败由 monitor 撤销整体成功状态。"""
        runtime = self.runtime
        uow = SqlAlchemyUnitOfWork(runtime.session_factory.create_session())
        try:
            deployments = uow.deployment_runtime_states.list_deployment_runtime_states(
                desired_state="running"
            )
            workflows = (
                uow.workflow_runtime.list_workflow_app_runtimes_by_desired_state(
                    "running"
                )
            )
            triggers = uow.workflow_trigger_sources.list_enabled_trigger_sources()
            revisions = {
                item.workflow_runtime_id: uow.workflow_runtime.get_workflow_runtime_revision(
                    item.active_revision_id
                )
                if item.active_revision_id
                else None
                for item in workflows
            }
            expected_instances = {
                item.deployment_instance_id: deployment.runtime_configuration.instance_count
                for item in deployments
                if (
                    deployment := uow.deployments.get_deployment_instance(
                        item.deployment_instance_id
                    )
                )
                is not None
            }
        finally:
            uow.close()

        items = [status_item("service", "database", True, "database_unavailable")]
        active_keys = {
            (item.workflow_runtime_id, item.active_revision_id) for item in workflows
        }
        self._dependencies = {
            key: value
            for key, value in self._dependencies.items()
            if key in active_keys
        }
        broker = runtime.local_buffer_broker_supervisor.get_health_summary()
        broker_ready = broker.get("enabled") is not True or (
            broker.get("running") is True and broker.get("state") == "healthy"
        )
        items.append(
            status_item(
                "service", "local_buffer", broker_ready, "local_buffer_unavailable"
            )
        )

        models: list[dict[str, object]] = []
        daemon_ready = True
        if runtime.settings.inference_daemon.runtime_owner == "daemon":
            try:
                daemon = read_inference_status(runtime.settings.local_memory.root_dir)
                daemon_ready = daemon.get("ready") is True and isinstance(
                    daemon.get("deployments"), list
                )
                models = daemon.get("deployments", [])
            except Exception:  # noqa: BLE001 - 单个组件失败不能阻止其它资源状态展示
                daemon_ready = False
            items.append(
                status_item(
                    "service", "inference", daemon_ready, "inference_unavailable"
                )
            )
        else:
            for binding in runtime.deployment_runtime_reconciler.bindings_by_task_type.values():
                for supervisor in (binding.sync_supervisor, binding.async_supervisor):
                    models.extend(supervisor.service_status_snapshot())
        model_index = {(item["id"], item["mode"]): item for item in models}
        for deployment in deployments:
            observed = model_index.get(
                (deployment.deployment_instance_id, deployment.runtime_mode), {}
            )
            items.append(
                status_item(
                    "deployments",
                    deployment.deployment_instance_id,
                    broker_ready
                    and daemon_ready
                    and observed.get("ready") is True
                    and observed.get("instance_count")
                    == expected_instances.get(deployment.deployment_instance_id),
                    "deployment_not_running",
                    mode=deployment.runtime_mode,
                    instance_count=observed.get("instance_count", 0),
                )
            )

        observed_workflows = (
            runtime.workflow_runtime_worker_manager.service_status_snapshot()
        )
        workflow_ready: dict[str, bool] = {}
        for workflow in workflows:
            observed = observed_workflows.get(workflow.workflow_runtime_id, {})
            revision = revisions[workflow.workflow_runtime_id]
            dependencies = self._model_dependencies(workflow)
            models_ready = all(
                model_index.get(key, {}).get("ready") is True for key in dependencies
            ) and (daemon_ready or not dependencies)
            ready = (
                broker_ready
                and models_ready
                and observed.get("ready") is True
                and revision is not None
                and revision.state == "active"
                and workflow.active_revision_id == workflow.desired_revision_id
                and observed.get("revision_id") == workflow.active_revision_id
                and observed.get("generation")
                == revision.generation
                == workflow.revision_generation
                and observed.get("fingerprint")
                == revision.expected_snapshot_fingerprint
            )
            workflow_ready[workflow.workflow_runtime_id] = ready
            items.append(
                status_item(
                    "runtimes",
                    workflow.workflow_runtime_id,
                    ready,
                    "runtime_not_running"
                    if models_ready
                    else "model_dependency_unavailable",
                )
            )
        for trigger in triggers:
            try:
                health = runtime.trigger_source_supervisor.get_health(
                    trigger.trigger_source_id
                )
                adapter = health.get("adapter_health", {})
                running = (
                    adapter.get("running") is True
                    and adapter.get("stopping") is not True
                )
            except Exception:  # noqa: BLE001 - 隔离单个适配器的探测失败
                running = False
            dependency_ready = workflow_ready.get(trigger.workflow_runtime_id, False)
            items.append(
                status_item(
                    "triggers",
                    trigger.trigger_source_id,
                    running and dependency_ready,
                    "trigger_not_running"
                    if not running
                    else "runtime_dependency_unavailable",
                )
            )
        return items
