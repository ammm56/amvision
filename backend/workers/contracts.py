"""backend-worker Profile、Topology 与启动身份契约。"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.workers.settings import SUPPORTED_BACKEND_WORKER_CONSUMER_KINDS


WORKER_PROFILE_FORMAT_ID = "amvision.worker-profile.v1"
WORKER_TOPOLOGY_FORMAT_ID = "amvision.worker-topology.v1"
WORKER_TOPOLOGY_POINTER_FORMAT_ID = "amvision.worker-topology-pointer.v1"
WORKER_HEARTBEAT_FORMAT_ID = "amvision.worker-heartbeat.v1"
WORKER_TOPOLOGY_ID = "amvision-backend-workers"
DEFAULT_WORKER_RUNTIME_ROOT = Path("./data/runtime/backend-workers")

WORKER_PROFILE_FILE_ENV = "AMVISION_WORKER_PROFILE_FILE"
WORKER_TOPOLOGY_ID_ENV = "AMVISION_WORKER_TOPOLOGY_ID"
WORKER_TOPOLOGY_GENERATION_ENV = "AMVISION_WORKER_TOPOLOGY_GENERATION"
WORKER_TOPOLOGY_EPOCH_ID_ENV = "AMVISION_WORKER_TOPOLOGY_EPOCH_ID"
WORKER_INSTANCE_ID_ENV = "AMVISION_WORKER_INSTANCE_ID"
WORKER_RUNTIME_ROOT_ENV = "AMVISION_WORKER_RUNTIME_ROOT"


class _StrictWorkerContract(BaseModel):
    """为 worker 运行契约提供统一的严格解析规则。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkerProfileManifest(_StrictWorkerContract):
    """描述一个不可变 backend-worker Profile。"""

    format_id: Literal["amvision.worker-profile.v1"]
    profile_id: str = Field(
        min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    enabled_consumer_kinds: tuple[str, ...] = Field(min_length=1)
    max_concurrent_tasks: int = Field(gt=0, le=1024)
    poll_interval_seconds: float = Field(gt=0, le=60)

    @field_validator("enabled_consumer_kinds")
    @classmethod
    def _validate_consumer_kinds(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """拒绝重复、空值和未注册 consumer kind。"""

        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("enabled_consumer_kinds 不能包含空值")
        if len(normalized) != len(set(normalized)):
            raise ValueError("enabled_consumer_kinds 不能包含重复值")
        unsupported = sorted(set(normalized) - SUPPORTED_BACKEND_WORKER_CONSUMER_KINDS)
        if unsupported:
            raise ValueError(f"worker profile 包含未注册 consumer kind: {unsupported}")
        return normalized

    def fingerprint(self) -> str:
        """返回 Profile 内容的稳定 SHA-256 指纹。"""

        payload = self.model_dump(mode="json")
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


class WorkerTopologyProfile(_StrictWorkerContract):
    """描述当前 Topology 期望运行的一个 Profile。"""

    profile_id: str = Field(
        min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    display_name: str = Field(min_length=1, max_length=128)
    profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    enabled_consumer_kinds: tuple[str, ...] = Field(min_length=1)
    max_concurrent_tasks: int = Field(gt=0, le=1024)
    poll_interval_seconds: float = Field(gt=0, le=60)

    @classmethod
    def from_manifest(cls, manifest: WorkerProfileManifest) -> WorkerTopologyProfile:
        """从严格 Profile Manifest 构造 Topology Profile。"""

        return cls(
            profile_id=manifest.profile_id,
            display_name=manifest.display_name,
            profile_fingerprint=manifest.fingerprint(),
            enabled_consumer_kinds=manifest.enabled_consumer_kinds,
            max_concurrent_tasks=manifest.max_concurrent_tasks,
            poll_interval_seconds=manifest.poll_interval_seconds,
        )


class WorkerTopologyManifest(_StrictWorkerContract):
    """描述 Supervisor 激活的一代 backend-worker Topology。"""

    format_id: Literal["amvision.worker-topology.v1"]
    topology_id: str = Field(min_length=1, max_length=128)
    topology_generation: int = Field(gt=0)
    topology_epoch_id: str = Field(min_length=16, max_length=128)
    state: Literal["starting", "running", "stopping", "stopped", "failed"]
    supervisor_instance_id: str = Field(min_length=16, max_length=128)
    activated_at: datetime
    heartbeat_interval_seconds: float = Field(gt=0, le=60)
    stale_after_seconds: float = Field(gt=0, le=300)
    expected_profiles: tuple[WorkerTopologyProfile, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_profile_identity(self) -> WorkerTopologyManifest:
        """确保一代 Topology 不会重复声明 Profile。"""

        profile_ids = [profile.profile_id for profile in self.expected_profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("expected_profiles 不能包含重复 profile_id")
        return self


class WorkerTopologyPointer(_StrictWorkerContract):
    """描述当前唯一激活的 Worker Topology 指针。"""

    format_id: Literal["amvision.worker-topology-pointer.v1"]
    topology_id: str = Field(min_length=1, max_length=128)
    topology_generation: int = Field(gt=0)
    topology_epoch_id: str = Field(min_length=16, max_length=128)
    activated_at: datetime


class WorkerHeartbeatRecord(_StrictWorkerContract):
    """描述一个 Profile 进程在当前 Topology epoch 中的心跳。"""

    format_id: Literal["amvision.worker-heartbeat.v1"]
    topology_id: str = Field(min_length=1, max_length=128)
    topology_generation: int = Field(gt=0)
    topology_epoch_id: str = Field(min_length=16, max_length=128)
    profile_id: str = Field(min_length=1, max_length=64)
    profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_instance_id: str = Field(min_length=16, max_length=128)
    status: Literal["starting", "running", "stopping", "stopped", "failed"]
    app_version: str = Field(min_length=1, max_length=64)
    process_id: int = Field(gt=0)
    python_executable: str = Field(min_length=1)
    process_started_at: datetime
    heartbeat_at: datetime
    workspace_dir: str = Field(min_length=1)
    queue_root_dir: str = Field(min_length=1)
    enabled_consumer_kinds: tuple[str, ...] = Field(min_length=1)
    max_concurrent_tasks: int = Field(gt=0)
    poll_interval_seconds: float = Field(gt=0)
    failure_message: str | None = None


@dataclass(frozen=True)
class BackendWorkerRuntimeLayout:
    """集中定义 Worker Topology 运行态文件路径。"""

    root_dir: Path

    @property
    def active_topology_path(self) -> Path:
        """返回当前 Topology 指针路径。"""

        return self.root_dir / "active.json"

    @property
    def topology_lock_path(self) -> Path:
        """返回 Supervisor 单实例锁路径。"""

        return self.root_dir / "topology.lock"

    def topology_dir(self, topology_epoch_id: str) -> Path:
        """返回指定 epoch 的运行目录。"""

        return self.root_dir / "topologies" / topology_epoch_id

    def topology_manifest_path(self, topology_epoch_id: str) -> Path:
        """返回指定 epoch 的 Topology Manifest 路径。"""

        return self.topology_dir(topology_epoch_id) / "manifest.json"

    def profile_heartbeat_path(self, topology_epoch_id: str, profile_id: str) -> Path:
        """返回指定 epoch/Profile 的唯一心跳路径。"""

        return self.topology_dir(topology_epoch_id) / "profiles" / f"{profile_id}.json"

    def profile_lock_path(self, topology_epoch_id: str, profile_id: str) -> Path:
        """返回指定 epoch/Profile 的单实例锁路径。"""

        return self.topology_dir(topology_epoch_id) / "locks" / f"{profile_id}.lock"


@dataclass(frozen=True)
class BackendWorkerLaunchContext:
    """描述 Supervisor 传给单个 Worker 进程的不可变启动身份。"""

    profile_file: Path
    runtime_layout: BackendWorkerRuntimeLayout
    topology_id: str
    topology_generation: int
    topology_epoch_id: str
    worker_instance_id: str


@dataclass(frozen=True)
class BackendWorkerLaunchBundle:
    """保存已完成交叉校验的 Worker 启动契约。"""

    context: BackendWorkerLaunchContext
    profile: WorkerProfileManifest
    topology: WorkerTopologyManifest


def load_worker_profile_manifest(path: str | Path) -> WorkerProfileManifest:
    """严格读取 Worker Profile Manifest。"""

    payload = _read_json_object(Path(path))
    return WorkerProfileManifest.model_validate(payload)


def load_worker_topology_manifest(path: str | Path) -> WorkerTopologyManifest:
    """严格读取 Worker Topology Manifest。"""

    payload = _read_json_object(Path(path))
    return WorkerTopologyManifest.model_validate(payload)


def load_worker_topology_pointer(path: str | Path) -> WorkerTopologyPointer:
    """严格读取当前 Worker Topology 指针。"""

    payload = _read_json_object(Path(path))
    return WorkerTopologyPointer.model_validate(payload)


def load_worker_heartbeat(path: str | Path) -> WorkerHeartbeatRecord:
    """严格读取一个 Worker Profile 心跳。"""

    payload = _read_json_object(Path(path))
    return WorkerHeartbeatRecord.model_validate(payload)


def load_backend_worker_launch_context(
    environment: Mapping[str, str] | None = None,
) -> BackendWorkerLaunchContext:
    """从 Supervisor 注入的环境变量读取严格启动身份。"""

    values = environment or os.environ
    profile_file = _require_environment_path(values, WORKER_PROFILE_FILE_ENV)
    runtime_root = _require_environment_path(values, WORKER_RUNTIME_ROOT_ENV)
    topology_id = _require_environment_text(values, WORKER_TOPOLOGY_ID_ENV)
    topology_epoch_id = _require_environment_text(values, WORKER_TOPOLOGY_EPOCH_ID_ENV)
    worker_instance_id = _require_environment_text(values, WORKER_INSTANCE_ID_ENV)
    generation_text = _require_environment_text(values, WORKER_TOPOLOGY_GENERATION_ENV)
    try:
        topology_generation = int(generation_text)
    except ValueError as error:
        raise RuntimeError(
            "AMVISION_WORKER_TOPOLOGY_GENERATION 必须是正整数"
        ) from error
    if topology_generation <= 0:
        raise RuntimeError("AMVISION_WORKER_TOPOLOGY_GENERATION 必须是正整数")
    return BackendWorkerLaunchContext(
        profile_file=profile_file,
        runtime_layout=BackendWorkerRuntimeLayout(runtime_root),
        topology_id=topology_id,
        topology_generation=topology_generation,
        topology_epoch_id=topology_epoch_id,
        worker_instance_id=worker_instance_id,
    )


def load_backend_worker_launch_bundle(
    environment: Mapping[str, str] | None = None,
) -> BackendWorkerLaunchBundle:
    """加载并交叉校验 Profile、Topology 与当前激活指针。"""

    context = load_backend_worker_launch_context(environment)
    profile = load_worker_profile_manifest(context.profile_file)
    pointer = load_worker_topology_pointer(context.runtime_layout.active_topology_path)
    topology = load_worker_topology_manifest(
        context.runtime_layout.topology_manifest_path(context.topology_epoch_id)
    )
    expected_identity = (
        context.topology_id,
        context.topology_generation,
        context.topology_epoch_id,
    )
    if (
        pointer.topology_id,
        pointer.topology_generation,
        pointer.topology_epoch_id,
    ) != expected_identity:
        raise RuntimeError("Worker 启动身份与当前 active Topology 不一致")
    if (
        topology.topology_id,
        topology.topology_generation,
        topology.topology_epoch_id,
    ) != expected_identity:
        raise RuntimeError("Worker 启动身份与 Topology Manifest 不一致")
    if topology.state not in {"starting", "running"}:
        raise RuntimeError(
            f"当前 Worker Topology 不接受新进程: state={topology.state!r}"
        )
    expected_profile = next(
        (
            item
            for item in topology.expected_profiles
            if item.profile_id == profile.profile_id
        ),
        None,
    )
    if expected_profile is None:
        raise RuntimeError(f"当前 Topology 未声明 Worker Profile: {profile.profile_id}")
    if expected_profile.profile_fingerprint != profile.fingerprint():
        raise RuntimeError("Worker Profile 指纹与当前 Topology 不一致")
    return BackendWorkerLaunchBundle(
        context=context,
        profile=profile,
        topology=topology,
    )


def write_worker_contract(path: str | Path, contract: BaseModel) -> None:
    """原子写入一个严格 Worker JSON 契约。"""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temp_path.write_text(
        json.dumps(
            contract.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    temp_path.replace(target)


def build_topology_pointer(topology: WorkerTopologyManifest) -> WorkerTopologyPointer:
    """从 Topology Manifest 构造 active pointer。"""

    return WorkerTopologyPointer(
        format_id=WORKER_TOPOLOGY_POINTER_FORMAT_ID,
        topology_id=topology.topology_id,
        topology_generation=topology.topology_generation,
        topology_epoch_id=topology.topology_epoch_id,
        activated_at=topology.activated_at,
    )


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。"""

    return datetime.now(UTC)


def _read_json_object(path: Path) -> dict[str, object]:
    """读取 JSON object，并为非法顶层结构提供明确错误。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是 JSON object")
    return {str(key): value for key, value in payload.items()}


def _require_environment_text(values: Mapping[str, str], name: str) -> str:
    """读取 Supervisor 必须注入的非空环境变量。"""

    value = values.get(name, "").strip()
    if not value:
        raise RuntimeError(f"backend-worker 缺少 Supervisor 启动参数: {name}")
    return value


def _require_environment_path(values: Mapping[str, str], name: str) -> Path:
    """读取并解析 Supervisor 必须注入的路径环境变量。"""

    return Path(_require_environment_text(values, name)).resolve()
