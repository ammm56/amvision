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
    select_matrix_cases,
    validate_case_result,
)
from tests.integration.yolo_model_full_chain_smoke import (
    ManagedProcess,
    build_e2e_process_environment,
    collect_generated_working_directory_artifacts,
    extract_sample_image_from_archive,
    snapshot_working_directory_artifacts,
    start_process,
    stop_managed_processes,
    validate_task_case_source,
)


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
    for item in build_model_task_matrix():
        validate_task_case_source(item.task_case)
        if item.task_case.task_type == "obb":
            assert item.task_case.import_format == "dota"
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
