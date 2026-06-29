from __future__ import annotations

import pytest

from backend.service.application.models.support.distributed_training import (
    DdpBackendAvailability,
    DdpLocalLaunchConfig,
    DdpTrainingContext,
    DistributedTrainingError,
    RankZeroReporter,
    RankZeroReportRecord,
    build_ddp_context_from_env,
    build_torchrun_module_command,
    choose_ddp_backend,
    prepare_torchrun_launch,
    initialize_torch_distributed,
    validate_ddp_world_size,
)


def test_ddp_context_defaults_to_single_process() -> None:
    context = build_ddp_context_from_env(
        backend="gloo",
        cuda_available=False,
        env={},
    )

    assert context.rank == -1
    assert context.local_rank == -1
    assert context.world_size == 1
    assert context.device == "cpu"
    assert context.is_rank_zero is True
    assert context.is_distributed is False


def test_ddp_context_reads_torchrun_environment() -> None:
    context = build_ddp_context_from_env(
        backend="nccl",
        cuda_available=True,
        env={
            "RANK": "3",
            "LOCAL_RANK": "1",
            "WORLD_SIZE": "4",
            "MASTER_ADDR": "127.0.0.1",
            "MASTER_PORT": "29677",
        },
    )

    assert context.rank == 3
    assert context.local_rank == 1
    assert context.world_size == 4
    assert context.device == "cuda:1"
    assert context.dist_url == "tcp://127.0.0.1:29677"
    assert context.is_rank_zero is False
    assert context.is_distributed is True


def test_ddp_context_rejects_missing_rank_for_multi_process() -> None:
    with pytest.raises(DistributedTrainingError, match="RANK"):
        build_ddp_context_from_env(
            backend="gloo",
            cuda_available=False,
            env={"WORLD_SIZE": "2", "LOCAL_RANK": "0"},
        )


def test_choose_ddp_backend_prefers_nccl_for_cuda() -> None:
    backend = choose_ddp_backend(
        DdpBackendAvailability(nccl=True, gloo=True),
        prefer_cuda=True,
    )

    assert backend == "nccl"


def test_choose_ddp_backend_uses_gloo_without_nccl() -> None:
    backend = choose_ddp_backend(
        DdpBackendAvailability(nccl=False, gloo=True),
        prefer_cuda=True,
    )

    assert backend == "gloo"


def test_choose_ddp_backend_rejects_unavailable_environment() -> None:
    with pytest.raises(DistributedTrainingError, match="backend"):
        choose_ddp_backend(DdpBackendAvailability(), prefer_cuda=True)


def test_validate_ddp_world_size_rejects_missing_gpus() -> None:
    with pytest.raises(DistributedTrainingError, match="2 张 GPU"):
        validate_ddp_world_size(world_size=2, available_gpu_count=1)


def test_torchrun_module_command_contains_expected_arguments() -> None:
    command = build_torchrun_module_command(
        DdpLocalLaunchConfig(
            module="backend.workers.training.yolox_ddp_entry",
            world_size=2,
            backend="gloo",
            args=("--task-id", "task-1"),
            master_port=29601,
            python_executable="python",
        )
    )

    assert command == (
        "python",
        "-m",
        "torch.distributed.run",
        "--nproc_per_node",
        "2",
        "--master_addr",
        "127.0.0.1",
        "--master_port",
        "29601",
        "--rdzv_conf",
        "use_libuv=0",
        "--module",
        "backend.workers.training.yolox_ddp_entry",
        "--task-id",
        "task-1",
    )


def test_prepare_torchrun_launch_sets_shared_environment() -> None:
    launch = prepare_torchrun_launch(
        DdpLocalLaunchConfig(
            module="backend.workers.training.yolo_ddp_entry",
            world_size=4,
            backend="gloo",
            env={"AMVISION_TASK_ID": "task-2"},
            master_port=29602,
            python_executable="python",
        )
    )

    assert launch.world_size == 4
    assert launch.backend == "gloo"
    assert launch.env["AMVISION_TASK_ID"] == "task-2"
    assert launch.env["USE_LIBUV"] == "0"
    assert launch.env["MASTER_PORT"] == "29602"
    assert launch.env["AMVISION_DDP_WORLD_SIZE"] == "4"
    assert launch.command[0] == "python"


def test_initialize_torch_distributed_can_disable_libuv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_calls: list[dict[str, object]] = []
    init_calls: list[dict[str, object]] = []

    class _FakeCuda:
        @staticmethod
        def set_device(_: int) -> None:
            return None

    class _FakeDistributed:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def is_initialized() -> bool:
            return False

        @staticmethod
        def TCPStore(*args: object, **kwargs: object) -> str:
            store_calls.append({"args": args, "kwargs": kwargs})
            return "store"

        @staticmethod
        def init_process_group(**kwargs: object) -> None:
            init_calls.append(kwargs)

    class _FakeTorch:
        cuda = _FakeCuda()
        distributed = _FakeDistributed()

    monkeypatch.setenv("AMVISION_DDP_DISABLE_LIBUV", "1")
    context = DdpTrainingContext(
        rank=0,
        local_rank=0,
        world_size=2,
        device="cuda:0",
        backend="gloo",
        master_addr="127.0.0.1",
        master_port=29601,
    )

    initialize_torch_distributed(torch_module=_FakeTorch(), context=context)

    assert store_calls
    assert store_calls[0]["kwargs"]["use_libuv"] is False
    assert init_calls == [
        {
            "backend": "gloo",
            "store": "store",
            "rank": 0,
            "world_size": 2,
        }
    ]


def test_rank_zero_reporter_only_emits_from_rank_zero() -> None:
    records: list[RankZeroReportRecord] = []
    reporter = RankZeroReporter(
        DdpTrainingContext(
            rank=0,
            local_rank=0,
            world_size=2,
            device="cuda:0",
            backend="gloo",
            master_addr="127.0.0.1",
            master_port=29603,
        ),
        records.append,
    )

    reporter.metric("epoch metrics", {"loss": 1.0})

    assert records == [
        RankZeroReportRecord(
            kind="metric",
            message="epoch metrics",
            payload={"loss": 1.0},
        )
    ]


def test_rank_zero_reporter_ignores_non_zero_ranks() -> None:
    records: list[RankZeroReportRecord] = []
    reporter = RankZeroReporter(
        DdpTrainingContext(
            rank=1,
            local_rank=1,
            world_size=2,
            device="cuda:1",
            backend="gloo",
            master_addr="127.0.0.1",
            master_port=29603,
        ),
        records.append,
    )

    reporter.artifact("checkpoint", {"path": "latest.pt"})

    assert records == []
