"""Deployment runtime 持久化恢复协调器测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessConfig,
    DeploymentProcessStatus,
)
from backend.service.application.runtime.deployment.deployment_runtime_reconciler import (
    DeploymentRuntimeBinding,
    DeploymentRuntimeReconciler,
)
from backend.service.application.runtime.deployment.deployment_runtime_state_service import (
    DeploymentRuntimeStateService,
)
from backend.service.domain.deployments.deployment_runtime_state import (
    DeploymentRuntimeState,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
    serialize_deployment_runtime_configuration,
)
from backend.service.infrastructure.persistence.deployment_orm import (
    DeploymentInstanceRecord,
)
from backend.service.settings import BackendServiceDeploymentRuntimeReconcilerConfig
from tests.api_test_support import create_test_runtime
from tests.runtime_pool_test_support import build_test_runtime_target


class _DeploymentService:
    """返回固定 process config 的测试 deployment service。"""

    def __init__(self, config: DeploymentProcessConfig) -> None:
        self.config = config

    def resolve_process_config(self, deployment_instance_id: str):
        assert deployment_instance_id == self.config.deployment_instance_id
        return self.config


class _LookupService:
    """返回固定 task type 的测试查询服务。"""

    def get_deployment_instance(self, deployment_instance_id: str):
        return SimpleNamespace(
            deployment_instance_id=deployment_instance_id,
            task_type="detection",
        )


class _Supervisor:
    """模拟 daemon 重启后最初没有任何子进程的 supervisor。"""

    def __init__(self, runtime_mode: str) -> None:
        self.runtime_mode = runtime_mode
        self.running = False
        self.start_count = 0
        self.stop_count = 0

    def get_status(self, config: DeploymentProcessConfig) -> DeploymentProcessStatus:
        return self._status(config)

    def start_deployment(
        self,
        config: DeploymentProcessConfig,
    ) -> DeploymentProcessStatus:
        self.start_count += 1
        self.running = True
        return self._status(config)

    def stop_deployment(
        self,
        config: DeploymentProcessConfig,
    ) -> DeploymentProcessStatus:
        self.stop_count += 1
        self.running = False
        return self._status(config)

    def _status(self, config: DeploymentProcessConfig) -> DeploymentProcessStatus:
        return DeploymentProcessStatus(
            deployment_instance_id=config.deployment_instance_id,
            runtime_mode=self.runtime_mode,  # type: ignore[arg-type]
            instance_count=1,
            desired_state="running" if self.running else "stopped",
            process_state="running" if self.running else "stopped",
            process_id=4321 if self.running else None,
            auto_restart=True,
            restart_count=0,
        )


class _Registry:
    """记录 async dispatcher 恢复动作。"""

    def __init__(self) -> None:
        self.started: list[str] = []

    def ensure_dispatcher_for_deployment(self, deployment_instance_id: str) -> None:
        self.started.append(deployment_instance_id)

    def stop_dispatcher_for_deployment(self, deployment_instance_id: str) -> None:
        if deployment_instance_id in self.started:
            self.started.remove(deployment_instance_id)


def test_reconciler_restores_persisted_desired_running_after_runtime_restart(
    tmp_path: Path,
) -> None:
    """验证新 controller 会按 DB 期望状态恢复 sync 子进程。"""

    session_factory, dataset_storage, _queue_backend = create_test_runtime(
        tmp_path,
        database_name="deployment-runtime-recovery.db",
    )
    deployment_instance_id = "deployment-runtime-recovery-1"
    _insert_deployment_record(session_factory, deployment_instance_id)
    target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="pytorch",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="model.pt",
        runtime_artifact_file_type="pytorch-state-dict",
    )
    process_config = DeploymentProcessConfig(
        deployment_instance_id=deployment_instance_id,
        runtime_target=target,
        project_id="project-1",
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    first_state_service = DeploymentRuntimeStateService(
        session_factory=session_factory
    )
    desired = first_state_service.set_desired_state(
        deployment_instance_id=deployment_instance_id,
        runtime_mode="sync",
        desired_state="running",
    )

    restarted_state_service = DeploymentRuntimeStateService(
        session_factory=session_factory
    )
    supervisor = _Supervisor("sync")
    async_supervisor = _Supervisor("async")
    registry = _Registry()
    reconciler = DeploymentRuntimeReconciler(
        state_service=restarted_state_service,
        lookup_service=_LookupService(),  # type: ignore[arg-type]
        bindings_by_task_type={
            "detection": DeploymentRuntimeBinding(
                deployment_service=_DeploymentService(process_config),  # type: ignore[arg-type]
                sync_supervisor=supervisor,  # type: ignore[arg-type]
                async_supervisor=async_supervisor,  # type: ignore[arg-type]
                async_gateway_registry=registry,
            )
        },
        settings=BackendServiceDeploymentRuntimeReconcilerConfig(
            reconcile_interval_seconds=0.01,
            controller_lease_seconds=1.0,
        ),
        controller_id="new-daemon-controller",
    )

    reconciler.reconcile_once()
    restored = restarted_state_service.get_runtime_state(
        deployment_instance_id=deployment_instance_id,
        runtime_mode="sync",
    )

    assert desired.generation == 1
    assert supervisor.start_count == 1
    assert restored.desired_state == "running"
    assert restored.observed_state == "running"
    assert restored.process_id == 4321
    assert restored.restart_count == 1
    assert restored.controller_owner_id == "new-daemon-controller"
    assert restored.last_started_at is not None
    session_factory.engine.dispose()


def test_runtime_state_generation_rejects_stale_controller_write(
    tmp_path: Path,
) -> None:
    """验证较旧 start 结果不能覆盖随后提交的 stop 命令。"""

    session_factory, _dataset_storage, _queue_backend = create_test_runtime(
        tmp_path,
        database_name="deployment-runtime-generation.db",
    )
    deployment_instance_id = "deployment-runtime-generation-1"
    _insert_deployment_record(session_factory, deployment_instance_id)
    state_service = DeploymentRuntimeStateService(session_factory=session_factory)
    running = state_service.set_desired_state(
        deployment_instance_id=deployment_instance_id,
        runtime_mode="sync",
        desired_state="running",
    )
    stopped = state_service.set_desired_state(
        deployment_instance_id=deployment_instance_id,
        runtime_mode="sync",
        desired_state="stopped",
    )

    stale_result = state_service.record_observed_state(
        deployment_instance_id=deployment_instance_id,
        runtime_mode="sync",
        generation=running.generation,
        observed_state="running",
        process_id=9999,
        restart_count=0,
    )

    assert stopped.generation == running.generation + 1
    assert stale_result.generation == stopped.generation
    assert stale_result.desired_state == "stopped"
    assert stale_result.observed_state == "stopped"
    assert stale_result.process_id is None
    session_factory.engine.dispose()


def test_restart_backoff_is_bounded_for_extremely_large_failure_count() -> None:
    """验证长期启动失败不会在指数计算时产生巨大整数或超过最大退避。"""

    settings = BackendServiceDeploymentRuntimeReconcilerConfig(
        restart_backoff_initial_seconds=1.0,
        restart_backoff_max_seconds=60.0,
        restart_backoff_jitter_ratio=0.2,
    )
    reconciler = DeploymentRuntimeReconciler(
        state_service=SimpleNamespace(),  # type: ignore[arg-type]
        lookup_service=SimpleNamespace(),  # type: ignore[arg-type]
        bindings_by_task_type={},
        settings=settings,
    )
    state = DeploymentRuntimeState(
        deployment_instance_id="deployment-long-running-failure",
        runtime_mode="sync",
    )

    delay = reconciler._build_restart_delay(  # noqa: SLF001 - 定向验证内部数值边界
        state,
        10**100,
    )

    assert 0.1 <= delay <= settings.restart_backoff_max_seconds


def _insert_deployment_record(session_factory, deployment_instance_id: str) -> None:
    """写入 runtime state 外键所需的最小 DeploymentInstance。"""

    now = datetime.now(timezone.utc).isoformat()
    session = session_factory.create_session()
    try:
        session.add(
            DeploymentInstanceRecord(
                deployment_instance_id=deployment_instance_id,
                project_id="project-1",
                model_id="model-1",
                model_version_id="model-version-1",
                model_build_id=None,
                runtime_profile_id=None,
                runtime_backend="pytorch",
                device_name="cpu",
                runtime_configuration_json=serialize_deployment_runtime_configuration(
                    DeploymentRuntimeConfiguration()
                ),
                status="active",
                display_name="runtime recovery",
                created_at=now,
                updated_at=now,
                created_by=None,
                metadata_json={"task_type": "detection"},
            )
        )
        session.commit()
    finally:
        session.close()
