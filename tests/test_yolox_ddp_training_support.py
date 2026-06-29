from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.backends import TrainingBackendRunRequest
from backend.service.application.models.support.distributed_training import (
    DdpBackendAvailability,
    DdpTrainingContext,
    DistributedTrainingError,
)
from backend.service.application.models.training.yolox_detection_task_types import (
    YoloXTrainingTaskResult,
)
from backend.service.application.models.yolox_core.training.ddp import (
    YOLOX_DDP_ENTRY_MODULE,
    YoloXDdpTrainingLaunchRequest,
    prepare_yolox_detection_ddp_launch,
)
from backend.service.application.models.yolox_core.training.execution import (
    _resolve_training_runtime,
)
from backend.workers.training import yolox_trainer_runner


class _FakeCuda:
    """测试用 CUDA 能力描述。"""

    selected_device: int | None = None

    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def device_count() -> int:
        return 2

    @classmethod
    def set_device(cls, device: int) -> None:
        cls.selected_device = device


class _FakeDistributed:
    """测试用 torch.distributed 能力描述。"""

    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def is_nccl_available() -> bool:
        return False

    @staticmethod
    def is_gloo_available() -> bool:
        return True

    @staticmethod
    def is_mpi_available() -> bool:
        return False


class _FakeTorch:
    """测试用 torch 模块。"""

    cuda = _FakeCuda()
    distributed = _FakeDistributed()


class _FakeCudaSingleGpu(_FakeCuda):
    """只暴露 1 张 GPU 的测试 CUDA 能力描述。"""

    @staticmethod
    def device_count() -> int:
        return 1


class _FakeSingleGpuTorch:
    """测试单 GPU 机器请求 DDP 时的 torch 模块。"""

    cuda = _FakeCudaSingleGpu()
    distributed = _FakeDistributed()


def test_yolox_detection_ddp_launch_uses_torchrun_module() -> None:
    launch = prepare_yolox_detection_ddp_launch(
        YoloXDdpTrainingLaunchRequest(
            task_id="task-yolox-ddp",
            project_root=Path("W:/workspace/codex/python/amvision"),
            world_size=2,
            available_gpu_count=2,
            backend_availability=DdpBackendAvailability(nccl=False, gloo=True),
            python_executable="python",
        )
    )

    assert launch.world_size == 2
    assert launch.backend == "gloo"
    assert launch.env["AMVISION_TRAINING_TASK_ID"] == "task-yolox-ddp"
    assert launch.env["AMVISION_TRAINING_MODEL_TYPE"] == "yolox"
    assert launch.env["AMVISION_TRAINING_TASK_TYPE"] == "detection"
    assert "--module" in launch.command
    assert YOLOX_DDP_ENTRY_MODULE in launch.command


def test_yolox_detection_ddp_launch_rejects_single_process_world_size() -> None:
    with pytest.raises(DistributedTrainingError, match="world_size"):
        prepare_yolox_detection_ddp_launch(
            YoloXDdpTrainingLaunchRequest(
                task_id="task-yolox-ddp",
                project_root=Path("."),
                world_size=1,
                available_gpu_count=2,
                backend_availability=DdpBackendAvailability(gloo=True),
            )
        )


def test_yolox_sync_training_runtime_rejects_data_parallel_path() -> None:
    imports = SimpleNamespace(torch=_FakeTorch())

    with pytest.raises(InvalidRequestError, match="DDP TrainingBackend"):
        _resolve_training_runtime(
            imports=imports,
            requested_gpu_count=2,
            extra_options={},
            ddp_context=None,
        )


def test_yolox_ddp_training_runtime_accepts_rank_context() -> None:
    imports = SimpleNamespace(torch=_FakeTorch())
    ddp_context = DdpTrainingContext(
        rank=1,
        local_rank=1,
        world_size=2,
        device="cuda:1",
        backend="gloo",
        master_addr="127.0.0.1",
        master_port=29500,
    )

    runtime = _resolve_training_runtime(
        imports=imports,
        requested_gpu_count=2,
        extra_options={},
        ddp_context=ddp_context,
    )

    assert runtime.distributed_mode == "ddp"
    assert runtime.rank == 1
    assert runtime.local_rank == 1
    assert runtime.world_size == 2
    assert runtime.is_rank_zero is False
    assert runtime.device == "cuda:1"
    assert _FakeCuda.selected_device == 1


def test_yolox_ddp_training_runtime_rejects_gpu_count_mismatch() -> None:
    imports = SimpleNamespace(torch=_FakeTorch())
    ddp_context = DdpTrainingContext(
        rank=0,
        local_rank=0,
        world_size=2,
        device="cuda:0",
        backend="gloo",
        master_addr="127.0.0.1",
        master_port=29500,
    )

    with pytest.raises(InvalidRequestError, match="gpu_count"):
        _resolve_training_runtime(
            imports=imports,
            requested_gpu_count=4,
            extra_options={},
            ddp_context=ddp_context,
        )


def test_yolox_worker_starts_torchrun_for_multi_gpu_task(monkeypatch: pytest.MonkeyPatch) -> None:
    service_instances: list[object] = []
    subprocess_calls: list[dict[str, object]] = []

    class _FakeYoloXTrainingService:
        def __init__(self, **_: object) -> None:
            service_instances.append(self)

        def read_requested_gpu_count(self, task_id: str) -> int:
            assert task_id == "task-yolox-ddp"
            return 2

        def process_training_task(self, task_id: str) -> YoloXTrainingTaskResult:
            raise AssertionError(f"DDP 任务不应在父 worker 内直接执行: {task_id}")

        def get_existing_training_result(self, task_id: str) -> YoloXTrainingTaskResult:
            assert task_id == "task-yolox-ddp"
            return YoloXTrainingTaskResult(
                task_id=task_id,
                status="succeeded",
                dataset_export_id="dataset-export-1",
                dataset_export_manifest_key="exports/manifest.json",
                dataset_version_id="dataset-version-1",
                format_id="coco-detection-v1",
                output_object_prefix="task-runs/training/task-yolox-ddp",
                checkpoint_object_key="task-runs/training/task-yolox-ddp/checkpoints/best.pth",
                latest_checkpoint_object_key="task-runs/training/task-yolox-ddp/checkpoints/latest.pth",
                labels_object_key="task-runs/training/task-yolox-ddp/labels.txt",
                metrics_object_key="task-runs/training/task-yolox-ddp/training-metrics.json",
                validation_metrics_object_key=(
                    "task-runs/training/task-yolox-ddp/validation-metrics.json"
                ),
                summary_object_key="task-runs/training/task-yolox-ddp/summary.json",
                best_metric_name="map50_95",
                best_metric_value=0.9,
                summary={"distributed_mode": "ddp"},
            )

    fake_launch = SimpleNamespace(
        command=("python", "-m", YOLOX_DDP_ENTRY_MODULE, "--task-id", "task-yolox-ddp"),
        env={"AMVISION_DDP_BACKEND": "gloo"},
        world_size=2,
        backend="gloo",
    )

    def _fake_prepare_launch(request: YoloXDdpTrainingLaunchRequest) -> SimpleNamespace:
        assert request.task_id == "task-yolox-ddp"
        assert request.world_size == 2
        assert request.available_gpu_count == 2
        assert request.backend_availability.gloo is True
        return fake_launch

    def _fake_subprocess_run(
        command: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
    ) -> SimpleNamespace:
        subprocess_calls.append(
            {
                "command": command,
                "cwd": cwd,
                "env": env,
                "check": check,
            }
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        yolox_trainer_runner,
        "SqlAlchemyYoloXTrainingTaskService",
        _FakeYoloXTrainingService,
    )
    monkeypatch.setattr(
        yolox_trainer_runner,
        "require_yolox_core_dependencies",
        lambda: SimpleNamespace(torch=_FakeTorch()),
    )
    monkeypatch.setattr(
        yolox_trainer_runner,
        "prepare_yolox_detection_ddp_launch",
        _fake_prepare_launch,
    )
    monkeypatch.setattr(yolox_trainer_runner.subprocess, "run", _fake_subprocess_run)

    runner = yolox_trainer_runner.SqlAlchemyYoloXTrainerRunner(
        session_factory=object(),
        dataset_storage=object(),
    )
    result = runner.run_training(
        TrainingBackendRunRequest(training_task_id="task-yolox-ddp")
    )

    assert service_instances
    assert len(subprocess_calls) == 1
    assert subprocess_calls[0]["command"] == fake_launch.command
    assert subprocess_calls[0]["env"]["AMVISION_DDP_BACKEND"] == "gloo"
    assert result.training_task_id == "task-yolox-ddp"
    assert result.status == "succeeded"
    assert result.summary == {"distributed_mode": "ddp"}


def test_yolox_worker_rejects_ddp_when_machine_has_single_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeYoloXTrainingService:
        def __init__(self, **_: object) -> None:
            pass

        def read_requested_gpu_count(self, task_id: str) -> int:
            assert task_id == "task-yolox-ddp"
            return 2

        def process_training_task(self, task_id: str) -> YoloXTrainingTaskResult:
            raise AssertionError(f"DDP 请求不应回退到单进程训练: {task_id}")

    def _fail_subprocess_run(*_: object, **__: object) -> SimpleNamespace:
        raise AssertionError("GPU 数量不足时不应启动 torchrun 子进程")

    monkeypatch.setattr(
        yolox_trainer_runner,
        "SqlAlchemyYoloXTrainingTaskService",
        _FakeYoloXTrainingService,
    )
    monkeypatch.setattr(
        yolox_trainer_runner,
        "require_yolox_core_dependencies",
        lambda: SimpleNamespace(torch=_FakeSingleGpuTorch()),
    )
    monkeypatch.setattr(yolox_trainer_runner.subprocess, "run", _fail_subprocess_run)

    runner = yolox_trainer_runner.SqlAlchemyYoloXTrainerRunner(
        session_factory=object(),
        dataset_storage=object(),
    )

    with pytest.raises(ServiceConfigurationError, match="无法启动 YOLOX DDP"):
        runner.run_training(TrainingBackendRunRequest(training_task_id="task-yolox-ddp"))
