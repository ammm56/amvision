"""真实小数据集端到端矩阵的静态完整性和结果门禁测试。"""

from __future__ import annotations

import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

from backend.service.api.rest.v1.routes.training_parameter_schemas import (
    TRAINING_PARAMETER_SCHEMA_BY_TASK_AND_MODEL,
)
from tests.integration.model_task_e2e_matrix import (
    REQUIRED_CONVERSION_FORMATS,
    SUPPORTED_MODEL_TASK_PAIRS,
    build_model_task_matrix,
    parse_args,
    resolve_pretrained_warm_start_model_version_id,
    resolve_dataset_dir_override,
    select_matrix_cases,
    validate_case_result,
)
from tests.integration.yolo_model_full_chain_smoke import (
    ManagedProcess,
    build_default_task_cases,
    build_e2e_process_environment,
    collect_generated_working_directory_artifacts,
    extract_sample_image_from_archive,
    snapshot_working_directory_artifacts,
    start_process,
    stop_managed_processes,
    submit_training_task,
    validate_task_case_source,
)


class _RecordingApiClient:
    """记录 E2E helper 发出的 API 请求。"""

    def __init__(self) -> None:
        self.path = ""
        self.payload: dict[str, object] = {}

    def post(self, path: str, *, json: dict[str, object]) -> dict[str, object]:
        self.path = path
        self.payload = json
        return {"task_id": "task-1"}


def test_e2e_process_environment_isolates_database_queue_and_ipc(
    tmp_path: Path,
) -> None:
    """验证并行开发服务不会消费 E2E 的数据库、队列或 daemon 控制消息。"""

    first = build_e2e_process_environment(run_dir=tmp_path / "run-a", port=18101)
    second = build_e2e_process_environment(run_dir=tmp_path / "run-b", port=18102)

    assert first["AMVISION_DATABASE__URL"] != second["AMVISION_DATABASE__URL"]
    assert first["AMVISION_QUEUE__ROOT_DIR"] != second["AMVISION_QUEUE__ROOT_DIR"]
    assert (
        first["AMVISION_INFERENCE_DAEMON__SERVICE_ID"]
        != second["AMVISION_INFERENCE_DAEMON__SERVICE_ID"]
    )
    assert first["AMVISION_WORKER_DATABASE__URL"] == first["AMVISION_DATABASE__URL"]
    assert first["AMVISION_WORKER_QUEUE__ROOT_DIR"] == first["AMVISION_QUEUE__ROOT_DIR"]
    assert first["AMVISION_TASK_MANAGER__ENABLED"] == "false"


def test_e2e_runner_collects_new_working_directory_diagnostics(
    tmp_path: Path,
) -> None:
    working_directory = tmp_path / "working-directory"
    working_directory.mkdir()
    snapshot = snapshot_working_directory_artifacts(
        working_directory=working_directory,
        artifact_names=("kernel.errors.txt",),
    )
    generated_artifact = working_directory / "kernel.errors.txt"
    generated_artifact.write_text("compiler diagnostics", encoding="utf-8")

    collected_paths = collect_generated_working_directory_artifacts(
        snapshot=snapshot,
        destination_root=tmp_path / "run" / "diagnostics",
    )

    assert collected_paths == (tmp_path / "run" / "diagnostics" / "kernel.errors.txt",)
    assert collected_paths[0].read_text(encoding="utf-8") == "compiler diagnostics"
    assert not generated_artifact.exists()


def test_e2e_runner_preserves_preexisting_working_directory_diagnostics(
    tmp_path: Path,
) -> None:
    working_directory = tmp_path / "working-directory"
    working_directory.mkdir()
    preexisting_artifact = working_directory / "kernel.errors.txt"
    preexisting_artifact.write_text("existing diagnostics", encoding="utf-8")
    snapshot = snapshot_working_directory_artifacts(
        working_directory=working_directory,
        artifact_names=("kernel.errors.txt",),
    )

    collected_paths = collect_generated_working_directory_artifacts(
        snapshot=snapshot,
        destination_root=tmp_path / "run" / "diagnostics",
    )

    assert collected_paths == ()
    assert preexisting_artifact.read_text(encoding="utf-8") == "existing diagnostics"


def test_e2e_matrix_matches_all_public_training_combinations() -> None:
    matrix = build_model_task_matrix()

    assert len(matrix) == 18
    assert len({item.case_id for item in matrix}) == 18
    assert (
        tuple((item.model_type, item.task_case.task_type) for item in matrix)
        == SUPPORTED_MODEL_TASK_PAIRS
    )
    assert set(SUPPORTED_MODEL_TASK_PAIRS) == {
        (model_type, task_type)
        for task_type, model_type in TRAINING_PARAMETER_SCHEMA_BY_TASK_AND_MODEL
    }


def test_e2e_matrix_uses_existing_sources_and_model_native_exports() -> None:
    default_cases = build_default_task_cases()
    assert default_cases["detection"].dataset_dir is not None
    assert default_cases["detection"].dataset_dir.name == "barcodeqrcode"
    assert default_cases["pose"].dataset_dir is not None
    assert default_cases["pose"].dataset_dir.name == "hand-keypoints-clean-v1"
    assert default_cases["obb"].dataset_dir is not None
    assert default_cases["obb"].dataset_dir.name == "rotated-components-v1"
    for item in build_model_task_matrix():
        validate_task_case_source(item.task_case)
        if item.task_case.task_type == "obb":
            assert item.task_case.import_format is None
        if item.model_type in {"yolox", "rfdetr"}:
            assert item.task_case.export_format.startswith("coco-")
        elif item.task_case.task_type == "classification":
            assert item.task_case.export_format == "imagenet-classification-v1"
        else:
            assert item.task_case.export_format.startswith("yolo-")


def test_e2e_matrix_defaults_to_three_conversions_and_full_scope() -> None:
    args = parse_args([])
    selected = select_matrix_cases(
        model_types=set(args.models),
        task_types=set(args.tasks),
    )

    assert tuple(args.target_formats) == REQUIRED_CONVERSION_FORMATS
    assert len(selected) == 18
    assert args.skip_deployment is False
    assert args.training_device == "auto"
    assert args.enable_augmentation is False
    assert args.evaluation_interval == 1
    assert args.model_scale is None
    assert args.input_size is None
    assert args.use_pretrained_warm_start is False
    assert args.training_precision == "auto"
    assert args.batch_mode == "auto"
    assert args.batch_target_memory_fraction == 0.6
    assert args.batch_minimum_size == 1
    assert args.batch_maximum_size is None
    assert args.batch_recover_on_oom is True
    assert args.batch_max_oom_retries == 3
    assert args.checkpoint_interval == 5
    assert args.checkpoint_keep_periodic == 2
    assert args.training_num_workers == 0
    assert args.training_prefetch_factor == 2
    assert args.dataset_dir is None


def test_e2e_matrix_accepts_explicit_accuracy_benchmark_options() -> None:
    """真实准确率基准不得被 smoke 的禁用增强和 nano 默认值锁死。"""

    args = parse_args(
        [
            "--models",
            "yolov8",
            "yolo11",
            "yolo26",
            "--tasks",
            "segmentation",
            "--model-scale",
            "m",
            "--input-size",
            "640",
            "640",
            "--enable-augmentation",
            "--evaluation-interval",
            "5",
            "--use-pretrained-warm-start",
            "--training-precision",
            "fp16",
            "--training-num-workers",
            "8",
            "--training-prefetch-factor",
            "4",
            "--batch-target-memory-fraction",
            "0.75",
            "--batch-minimum-size",
            "2",
            "--batch-maximum-size",
            "32",
            "--batch-max-oom-retries",
            "4",
            "--checkpoint-interval",
            "10",
            "--checkpoint-keep-periodic",
            "3",
        ]
    )

    assert args.model_scale == "m"
    assert args.input_size == [640, 640]
    assert args.enable_augmentation is True
    assert args.evaluation_interval == 5
    assert args.use_pretrained_warm_start is True
    assert args.training_precision == "fp16"
    assert args.training_num_workers == 8
    assert args.training_prefetch_factor == 4
    assert args.batch_target_memory_fraction == 0.75
    assert args.batch_minimum_size == 2
    assert args.batch_maximum_size == 32
    assert args.batch_max_oom_retries == 4
    assert args.checkpoint_interval == 10
    assert args.checkpoint_keep_periodic == 3


def test_e2e_matrix_resolves_single_task_dataset_override(tmp_path: Path) -> None:
    """精度矩阵可让多个 model family 共用一个显式全量数据集。"""

    selected = select_matrix_cases(
        model_types={"yolov8", "yolo11", "yolo26"},
        task_types={"pose"},
    )

    assert resolve_dataset_dir_override(
        dataset_dir=tmp_path,
        selected_cases=selected,
    ) == tmp_path.resolve()


def test_e2e_matrix_rejects_dataset_override_for_multiple_tasks(
    tmp_path: Path,
) -> None:
    """同一目录不得被静默解释成多个不兼容 task 的数据源。"""

    selected = select_matrix_cases(
        model_types={"yolov8"},
        task_types={"pose", "segmentation"},
    )

    with pytest.raises(ValueError, match="一个 task"):
        resolve_dataset_dir_override(
            dataset_dir=tmp_path,
            selected_cases=selected,
        )


def test_e2e_matrix_rejects_missing_dataset_override(tmp_path: Path) -> None:
    selected = select_matrix_cases(
        model_types={"yolov8"},
        task_types={"pose"},
    )

    with pytest.raises(ValueError, match="目录不存在"):
        resolve_dataset_dir_override(
            dataset_dir=tmp_path / "missing",
            selected_cases=selected,
        )


def test_e2e_matrix_resolves_only_supported_yolo_pretrained_versions() -> None:
    assert resolve_pretrained_warm_start_model_version_id(
        model_type="yolo11",
        task_type="segmentation",
        model_scale="m",
    ) == "mv-pretrained-yolo11-segmentation-m"

    with pytest.raises(ValueError, match="仅支持"):
        resolve_pretrained_warm_start_model_version_id(
            model_type="rfdetr",
            task_type="segmentation",
            model_scale="m",
        )


def test_e2e_training_submission_forwards_performance_and_warm_start_options() -> None:
    client = _RecordingApiClient()

    submit_training_task(
        client=client,
        case=build_default_task_cases()["segmentation"],
        project_id="project-1",
        model_type="yolov8",
        model_scale="m",
        dataset_export_id="dataset-export-1",
        manifest_key="manifest.json",
        output_model_name="model-1",
        max_epochs=200,
        batch_size=16,
        training_device="cuda:0",
        enable_augmentation=True,
        evaluation_interval=5,
        warm_start_model_version_id="mv-pretrained-yolov8-segmentation-m",
        training_precision="fp16",
        training_num_workers=8,
        training_prefetch_factor=4,
    )

    assert client.path == "/models/segmentation/training-tasks"
    assert client.payload["execution"] == {
        "max_epochs": 200,
        "input_size": {"width": 384, "height": 256},
        "batch": {
            "mode": "fixed",
            "size": 16,
            "target_memory_fraction": 0.6,
            "minimum_size": 1,
            "maximum_size": 16,
            "recover_on_oom": True,
            "max_oom_retries": 3,
        },
        "amp": {"mode": "enabled", "dtype": "fp16"},
        "checkpoint": {"interval_epochs": 5, "keep_periodic": 2},
        "validation": {"interval_epochs": 5},
    }
    assert client.payload["warm_start_model_version_id"] == (
        "mv-pretrained-yolov8-segmentation-m"
    )
    assert client.payload["parameters"] == {
        "runtime": {
            "device": "cuda:0",
            "num_workers": 8,
            "prefetch_factor": 4,
        },
        "augmentation": {"enabled": True},
    }


def test_e2e_training_submission_supports_auto_batch_oom_and_amp() -> None:
    """真实矩阵必须能走自动 batch、OOM 恢复和自动 AMP 正式 schema。"""

    client = _RecordingApiClient()

    submit_training_task(
        client=client,
        case=build_default_task_cases()["pose"],
        project_id="project-1",
        model_type="yolo11",
        model_scale="m",
        dataset_export_id="dataset-export-1",
        manifest_key="manifest.json",
        output_model_name="model-1",
        max_epochs=100,
        batch_size=1,
        training_device="cuda:0",
        training_precision="auto",
        batch_mode="auto",
        batch_target_memory_fraction=0.75,
        batch_minimum_size=2,
        batch_maximum_size=32,
        batch_recover_on_oom=True,
        batch_max_oom_retries=4,
        checkpoint_interval=5,
        checkpoint_keep_periodic=3,
    )

    execution = client.payload["execution"]
    assert execution["batch"] == {
        "mode": "auto",
        "size": None,
        "target_memory_fraction": 0.75,
        "minimum_size": 2,
        "maximum_size": 32,
        "recover_on_oom": True,
        "max_oom_retries": 4,
    }
    assert execution["amp"] == {"mode": "auto", "dtype": "auto"}
    assert execution["checkpoint"] == {
        "interval_epochs": 5,
        "keep_periodic": 3,
    }


def test_e2e_matrix_result_gate_requires_build_and_both_runtime_modes() -> None:
    complete = {
        "status": "succeeded",
        "dataset_version_id": "dataset-version-1",
        "dataset_export_id": "dataset-export-1",
        "training_task_id": "training-task-1",
        "model_version_id": "model-version-1",
        "evaluation": {
            "state": "succeeded",
            "sample_count": 1,
            "map50": 0.0,
            "map50_95": 0.0,
        },
        "conversions": {
            target: {
                "model_build_id": f"build-{target}",
                "deployment": {
                    "sync": {
                        "status": {"process_state": "running"},
                        "result_summary": {"latency_ms": 1.0},
                    },
                    "async": {
                        "status": {"process_state": "running"},
                        "task": {"state": "succeeded"},
                    },
                },
            }
            for target in REQUIRED_CONVERSION_FORMATS
        },
    }
    validate_case_result(
        complete,
        task_type="detection",
        target_formats=REQUIRED_CONVERSION_FORMATS,
        require_deployment=True,
        require_workflow=False,
    )

    complete["conversions"]["openvino-ir"]["deployment"]["async"] = {}
    with pytest.raises(RuntimeError, match="async"):
        validate_case_result(
            complete,
            task_type="detection",
            target_formats=REQUIRED_CONVERSION_FORMATS,
            require_deployment=True,
            require_workflow=False,
        )


def test_e2e_matrix_result_gate_requires_task_specific_evaluation_metrics() -> None:
    """验证 segmentation 成功状态不能掩盖 mask 指标缺失。"""

    incomplete = {
        "status": "succeeded",
        "dataset_version_id": "dataset-version-1",
        "dataset_export_id": "dataset-export-1",
        "training_task_id": "training-task-1",
        "model_version_id": "model-version-1",
        "evaluation": {
            "state": "succeeded",
            "sample_count": 1,
            "map50": 0.0,
            "map50_95": 0.0,
        },
        "conversions": {},
    }

    with pytest.raises(RuntimeError, match="mask_map50"):
        validate_case_result(
            incomplete,
            task_type="segmentation",
            target_formats=(),
            require_deployment=False,
            require_workflow=False,
        )


def test_archive_sample_extraction_rejects_traversal_and_is_bounded(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "dataset.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.jpg", b"escape")
        archive.writestr("images/valid.png", b"valid-image")

    sample_path = extract_sample_image_from_archive(
        archive_path=archive_path,
        run_dir=tmp_path / "run",
        sample_extensions=(".jpg", ".png"),
    )

    assert sample_path == tmp_path / "run" / "sample" / "valid.png"
    assert sample_path.read_bytes() == b"valid-image"
    assert not (tmp_path / "escape.jpg").exists()


def test_managed_process_shutdown_terminates_multiprocessing_descendants(
    tmp_path: Path,
) -> None:
    """验证 E2E runner 收尾不会在 Windows 留下大内存孤儿进程。"""

    psutil = pytest.importorskip("psutil")
    child_pid_path = tmp_path / "child.pid"
    parent = start_process(
        name="process-tree-test",
        args=[
            sys.executable,
            "-c",
            (
                "import subprocess,sys,time; from pathlib import Path; "
                "child=subprocess.Popen([sys.executable,'-c',"
                "'import time; time.sleep(60)']); "
                "Path(sys.argv[1]).write_text(str(child.pid),encoding='utf-8'); "
                "time.sleep(60)"
            ),
            str(child_pid_path),
        ],
        env=os.environ.copy(),
        log_path=tmp_path / "parent.log",
    )
    managed = ManagedProcess(
        name="process-tree-test",
        process=parent.process,
        log_path=parent.log_path,
    )
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not child_pid_path.is_file():
            time.sleep(0.05)
        assert child_pid_path.is_file()
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        assert psutil.pid_exists(child_pid)

        stop_managed_processes((managed,))

        assert parent.process.poll() is not None
        assert not psutil.pid_exists(child_pid)
    finally:
        stop_managed_processes((managed,))
