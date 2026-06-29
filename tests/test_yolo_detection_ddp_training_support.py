from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.support.distributed_training import (
    DdpBackendAvailability,
    DdpTrainingContext,
    DistributedTrainingError,
)
from backend.service.application.models.training.yolo_detection_training_service import (
    SqlAlchemyYoloDetectionTrainingTaskService,
)
from backend.service.application.models.yolo_core_common.training import (
    YOLO_DETECTION_DDP_ENTRY_MODULE,
    YoloDetectionDdpTrainingLaunchRequest,
    prepare_yolo_detection_ddp_launch,
)
from backend.workers.training import yolo_detection_ddp_runner


class _FakeCuda:
    """测试用 CUDA 能力描述。"""

    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def device_count() -> int:
        return 2


class _FakeCudaSingleGpu(_FakeCuda):
    """只暴露 1 张 GPU 的测试 CUDA 能力描述。"""

    @staticmethod
    def device_count() -> int:
        return 1


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


class _FakeSingleGpuTorch:
    """测试单 GPU 机器请求 DDP 时的 torch 模块。"""

    cuda = _FakeCudaSingleGpu()
    distributed = _FakeDistributed()


def test_yolo_detection_ddp_launch_uses_model_type_and_torchrun_module() -> None:
    """普通 YOLO detection DDP 启动命令应带 task_id 和 model_type。"""

    launch = prepare_yolo_detection_ddp_launch(
        YoloDetectionDdpTrainingLaunchRequest(
            task_id="task-yolo-ddp",
            model_type="yolo11",
            project_root=Path("W:/workspace/codex/python/amvision"),
            world_size=2,
            available_gpu_count=2,
            backend_availability=DdpBackendAvailability(nccl=False, gloo=True),
            python_executable="python",
        )
    )

    assert launch.world_size == 2
    assert launch.backend == "gloo"
    assert launch.env["AMVISION_TRAINING_TASK_ID"] == "task-yolo-ddp"
    assert launch.env["AMVISION_TRAINING_MODEL_TYPE"] == "yolo11"
    assert launch.env["AMVISION_TRAINING_TASK_TYPE"] == "detection"
    assert "--module" in launch.command
    assert YOLO_DETECTION_DDP_ENTRY_MODULE in launch.command
    assert "--model-type" in launch.command
    assert "yolo11" in launch.command


def test_yolo_detection_ddp_launch_rejects_unsupported_model_type() -> None:
    """普通 YOLO DDP 只允许 yolov8 / yolo11 / yolo26 detection。"""

    with pytest.raises(DistributedTrainingError, match="暂不支持"):
        prepare_yolo_detection_ddp_launch(
            YoloDetectionDdpTrainingLaunchRequest(
                task_id="task-yolo-ddp",
                model_type="yolox",
                project_root=Path("."),
                world_size=2,
                available_gpu_count=2,
                backend_availability=DdpBackendAvailability(gloo=True),
            )
        )


def test_yolo_detection_ddp_launch_rejects_single_process_world_size() -> None:
    """普通 YOLO DDP 不接受 world_size=1。"""

    with pytest.raises(DistributedTrainingError, match="world_size"):
        prepare_yolo_detection_ddp_launch(
            YoloDetectionDdpTrainingLaunchRequest(
                task_id="task-yolo-ddp",
                model_type="yolov8",
                project_root=Path("."),
                world_size=1,
                available_gpu_count=2,
                backend_availability=DdpBackendAvailability(gloo=True),
            )
        )


def test_yolo_detection_worker_starts_torchrun_for_multi_gpu_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """父 worker 在 gpu_count>1 时应启动 torchrun，不直接跑 service。"""

    subprocess_calls: list[dict[str, object]] = []

    class _FakeService:
        def read_requested_gpu_count(self, task_id: str) -> int:
            assert task_id == "task-yolo-ddp"
            return 2

        def process_training_task(self, task_id: str) -> object:
            raise AssertionError(f"DDP 任务不应在父 worker 内直接执行: {task_id}")

        def get_existing_training_result(self, task_id: str) -> object:
            assert task_id == "task-yolo-ddp"
            return SimpleNamespace(task_id=task_id, status="succeeded")

    fake_launch = SimpleNamespace(
        command=(
            "python",
            "-m",
            YOLO_DETECTION_DDP_ENTRY_MODULE,
            "--task-id",
            "task-yolo-ddp",
            "--model-type",
            "yolo11",
        ),
        env={"AMVISION_DDP_BACKEND": "gloo"},
        world_size=2,
        backend="gloo",
    )

    def _fake_prepare_launch(
        request: YoloDetectionDdpTrainingLaunchRequest,
    ) -> SimpleNamespace:
        assert request.task_id == "task-yolo-ddp"
        assert request.model_type == "yolo11"
        assert request.world_size == 2
        assert request.available_gpu_count == 2
        assert request.backend_availability.gloo is True
        return fake_launch

    def _fake_run_ddp_launch_processes(
        *,
        launch: SimpleNamespace,
        cwd: Path,
    ) -> SimpleNamespace:
        subprocess_calls.append(
            {
                "command": launch.command,
                "cwd": cwd,
                "env": launch.env,
            }
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        yolo_detection_ddp_runner,
        "_require_torch_module",
        lambda: _FakeTorch(),
    )
    monkeypatch.setattr(
        yolo_detection_ddp_runner,
        "prepare_yolo_detection_ddp_launch",
        _fake_prepare_launch,
    )
    monkeypatch.setattr(
        yolo_detection_ddp_runner,
        "run_ddp_launch_processes",
        _fake_run_ddp_launch_processes,
    )

    result = yolo_detection_ddp_runner.run_yolo_detection_training_with_optional_ddp(
        service=_FakeService(),
        model_type="yolo11",
        training_task_id="task-yolo-ddp",
    )

    assert result.task_id == "task-yolo-ddp"
    assert result.status == "succeeded"
    assert len(subprocess_calls) == 1
    assert subprocess_calls[0]["command"] == fake_launch.command
    assert subprocess_calls[0]["env"]["AMVISION_DDP_BACKEND"] == "gloo"


def test_yolo_detection_worker_rejects_ddp_when_machine_has_single_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单 GPU 机器请求普通 YOLO DDP 时应明确失败，不回退单进程训练。"""

    class _FakeService:
        def read_requested_gpu_count(self, task_id: str) -> int:
            assert task_id == "task-yolo-ddp"
            return 2

        def process_training_task(self, task_id: str) -> object:
            raise AssertionError(f"DDP 请求不应回退到单进程训练: {task_id}")

    def _fail_run_ddp_launch_processes(*_: object, **__: object) -> SimpleNamespace:
        raise AssertionError("GPU 数量不足时不应启动 torchrun 子进程")

    monkeypatch.setattr(
        yolo_detection_ddp_runner,
        "_require_torch_module",
        lambda: _FakeSingleGpuTorch(),
    )
    monkeypatch.setattr(
        yolo_detection_ddp_runner,
        "run_ddp_launch_processes",
        _fail_run_ddp_launch_processes,
    )

    with pytest.raises(ServiceConfigurationError, match="无法启动 yolo11 detection DDP"):
        yolo_detection_ddp_runner.run_yolo_detection_training_with_optional_ddp(
            service=_FakeService(),
            model_type="yolo11",
            training_task_id="task-yolo-ddp",
        )


@pytest.mark.parametrize(
    ("model_type", "model_label"),
    [
        ("yolov8", "YOLOv8"),
        ("yolo11", "YOLO11"),
        ("yolo26", "YOLO26"),
    ],
)
def test_yolo_detection_ddp_rank_dispatches_to_rank_aware_training(
    model_type: str,
    model_label: str,
) -> None:
    """普通 YOLO detection DDP rank 入口应进入内部 rank-aware 训练执行。"""

    recorded: dict[str, object] = {}

    class _FakeYoloDetectionService(SqlAlchemyYoloDetectionTrainingTaskService):
        def __init__(self) -> None:
            pass

        def _require_training_task(self, task_id: str) -> SimpleNamespace:
            assert task_id == f"task-{model_type}-ddp"
            return SimpleNamespace(task_id=task_id)

        def _build_request_from_task_record(
            self,
            task_record: SimpleNamespace,
        ) -> SimpleNamespace:
            assert task_record.task_id == f"task-{model_type}-ddp"
            return SimpleNamespace(gpu_count=2)

        def _process_training_task_internal(
            self,
            *,
            task_id: str,
            ddp_context: DdpTrainingContext | None,
        ) -> None:
            recorded["task_id"] = task_id
            recorded["ddp_context"] = ddp_context

    _FakeYoloDetectionService.model_type = model_type
    _FakeYoloDetectionService.model_label = model_label

    ddp_context = DdpTrainingContext(
        rank=1,
        local_rank=1,
        world_size=2,
        device="cuda:1",
        backend="gloo",
        master_addr="127.0.0.1",
        master_port=29500,
    )

    _FakeYoloDetectionService().process_detection_ddp_rank(
        task_id=f"task-{model_type}-ddp",
        ddp_context=ddp_context,
    )

    assert recorded["task_id"] == f"task-{model_type}-ddp"
    assert recorded["ddp_context"] is ddp_context
