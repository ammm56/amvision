"""18 个公开模型/任务组合的真实小数据集端到端验收入口。

默认执行完整矩阵：DatasetImport -> DatasetExport -> 1 epoch 训练 -> 独立评估 ->
ONNX/OpenVINO/TensorRT 转换 -> 每种产物独立加载 -> sync/async 各一次推理 ->
deployment stop/reset。结果写入 ``.tmp/model-task-e2e-matrix/<run-id>/result.json``。

该入口使用真实本地数据、预训练权重、转换器和 runtime，不属于默认 pytest。
任一矩阵项失败都会保留其余项的结果，并最终返回非零退出码。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from tests.integration.yolo_model_full_chain_smoke import (
    DEFAULT_PROJECT_ID,
    DEFAULT_TOKEN,
    REQUIRED_CONVERSION_FORMATS,
    YOLO_MAIN_MODEL_TYPES,
    ManagedProcess,
    SmokeApiClient,
    YoloModelTaskCase,
    build_default_task_cases,
    collect_process_snapshots,
    find_free_port,
    run_task_case,
    start_service_processes,
    stop_managed_processes,
    wait_for_service,
    write_result,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATRIX_ROOT = PROJECT_ROOT / ".tmp" / "model-task-e2e-matrix"
ALL_MODEL_TYPES = ("yolox", *YOLO_MAIN_MODEL_TYPES, "rfdetr")
ALL_TASK_TYPES = ("detection", "classification", "segmentation", "pose", "obb")
SUPPORTED_MODEL_TASK_PAIRS = (
    ("yolox", "detection"),
    *((model_type, "detection") for model_type in YOLO_MAIN_MODEL_TYPES),
    ("rfdetr", "detection"),
    *((model_type, "classification") for model_type in YOLO_MAIN_MODEL_TYPES),
    *((model_type, "segmentation") for model_type in YOLO_MAIN_MODEL_TYPES),
    ("rfdetr", "segmentation"),
    *((model_type, "pose") for model_type in YOLO_MAIN_MODEL_TYPES),
    *((model_type, "obb") for model_type in YOLO_MAIN_MODEL_TYPES),
)


@dataclass(frozen=True)
class ModelTaskMatrixCase:
    """描述一个可独立执行和审计的模型/任务链路。"""

    case_id: str
    model_type: str
    model_scale: str
    task_case: YoloModelTaskCase


def build_model_task_matrix() -> tuple[ModelTaskMatrixCase, ...]:
    """构造 18 个公开支持组合的唯一矩阵。"""

    task_cases = build_default_task_cases()
    matrix: list[ModelTaskMatrixCase] = []
    for model_type, task_type in SUPPORTED_MODEL_TASK_PAIRS:
        task_case = task_cases[task_type]
        if model_type in {"yolox", "rfdetr"} and task_type == "detection":
            task_case = replace(
                task_case,
                export_format="coco-detection-v1",
                input_size=(384, 384),
            )
        elif model_type == "rfdetr" and task_type == "segmentation":
            task_case = replace(
                task_case,
                export_format="coco-instance-seg-v1",
                input_size=(384, 384),
            )
        matrix.append(
            ModelTaskMatrixCase(
                case_id=f"{model_type}-{task_type}",
                model_type=model_type,
                model_scale="nano",
                task_case=task_case,
            )
        )
    return tuple(matrix)


def main(argv: list[str] | None = None) -> int:
    """执行选择后的矩阵，并为完整性和失败状态设置退出码。"""

    args = parse_args(argv)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d%H%M%S")
    run_dir = MATRIX_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    selected_cases = select_matrix_cases(
        model_types=set(args.models),
        task_types=set(args.tasks),
    )
    is_full_scope = (
        len(selected_cases) == len(SUPPORTED_MODEL_TASK_PAIRS)
        and tuple(args.target_formats) == REQUIRED_CONVERSION_FORMATS
        and not args.skip_deployment
    )
    result: dict[str, Any] = {
        "contract_version": 1,
        "run_id": run_id,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "coverage": "full" if is_full_scope else "partial",
        "required_case_count": len(SUPPORTED_MODEL_TASK_PAIRS),
        "selected_case_count": len(selected_cases),
        "required_conversion_formats": list(REQUIRED_CONVERSION_FORMATS),
        "selected_conversion_formats": list(args.target_formats),
        "cases": {},
        "processes": {},
    }
    processes: list[ManagedProcess] = []
    client: SmokeApiClient | None = None
    base_url = args.base_url

    try:
        if args.start_processes:
            port = args.port or find_free_port(args.port_start, args.port_end)
            base_url = f"http://127.0.0.1:{port}"
            processes = start_service_processes(
                run_dir=run_dir,
                port=port,
                service_timeout_seconds=args.service_timeout_seconds,
            )
        wait_for_service(
            base_url=base_url,
            timeout_seconds=args.service_timeout_seconds,
        )
        client = SmokeApiClient(
            base_url=base_url,
            token=args.token,
            timeout_seconds=args.http_timeout_seconds,
        )
        for matrix_case in selected_cases:
            case_run_dir = run_dir / matrix_case.case_id
            case_run_dir.mkdir(parents=True, exist_ok=True)
            try:
                case_result = run_task_case(
                    client=client,
                    case=matrix_case.task_case,
                    run_dir=case_run_dir,
                    project_id=args.project_id,
                    model_type=matrix_case.model_type,
                    model_scale=matrix_case.model_scale,
                    target_formats=tuple(args.target_formats),
                    max_epochs=args.max_epochs,
                    batch_size=args.batch_size,
                    training_device=args.training_device,
                    timeout_seconds=args.task_timeout_seconds,
                    skip_deployment=args.skip_deployment,
                    run_workflow=args.run_workflow,
                    max_images_per_split=args.max_images_per_split,
                )
                validate_case_result(
                    case_result,
                    task_type=matrix_case.task_case.task_type,
                    target_formats=tuple(args.target_formats),
                    require_deployment=not args.skip_deployment,
                    require_workflow=args.run_workflow,
                )
                result["cases"][matrix_case.case_id] = case_result
            except Exception as error:  # noqa: BLE001 - 需要形成完整失败矩阵。
                result["cases"][matrix_case.case_id] = {
                    "status": "failed",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error": str(error),
                }
                if args.fail_fast:
                    break
    except Exception as error:  # noqa: BLE001 - 顶层必须持久化启动失败。
        result["startup_error"] = str(error)
    finally:
        if client is not None:
            client.close()
        result["processes"] = collect_process_snapshots(processes)
        stop_managed_processes(processes)

    failed_case_ids = [
        case_id
        for case_id, case_result in result["cases"].items()
        if case_result.get("status") != "succeeded"
    ]
    missing_case_ids = [
        item.case_id for item in selected_cases if item.case_id not in result["cases"]
    ]
    result["failed_case_ids"] = failed_case_ids
    result["missing_case_ids"] = missing_case_ids
    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    result["status"] = (
        "succeeded" if not failed_case_ids and not missing_case_ids else "failed"
    )
    write_result(run_dir=run_dir, result=result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "succeeded" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析矩阵选择、资源和执行参数。"""

    parser = argparse.ArgumentParser(description="运行模型/任务真实小数据集端到端矩阵")
    parser.add_argument("--base-url", default="http://127.0.0.1:5600")
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=ALL_MODEL_TYPES,
        default=ALL_MODEL_TYPES,
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        choices=ALL_TASK_TYPES,
        default=ALL_TASK_TYPES,
    )
    parser.add_argument(
        "--target-formats",
        nargs="+",
        choices=("onnx", "openvino-ir", "tensorrt-engine"),
        default=REQUIRED_CONVERSION_FORMATS,
    )
    parser.add_argument("--max-epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--training-device", default="auto")
    parser.add_argument("--max-images-per-split", type=int, default=4)
    parser.add_argument("--task-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--http-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--service-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--start-processes", action="store_true")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--port-start", type=int, default=18360)
    parser.add_argument("--port-end", type=int, default=18460)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-workflow", action="store_true")
    parser.add_argument("--skip-deployment", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args(argv)
    if args.max_epochs < 1 or args.batch_size < 1:
        parser.error("max-epochs 和 batch-size 必须大于 0")
    if args.max_images_per_split < 0:
        parser.error("max-images-per-split 不能小于 0")
    if len(set(args.target_formats)) != len(args.target_formats):
        parser.error("target-formats 不能重复")
    return args


def select_matrix_cases(
    *,
    model_types: set[str],
    task_types: set[str],
) -> tuple[ModelTaskMatrixCase, ...]:
    """按模型和任务交集选择合法组合。"""

    selected = tuple(
        case
        for case in build_model_task_matrix()
        if case.model_type in model_types and case.task_case.task_type in task_types
    )
    if not selected:
        raise ValueError("模型和任务筛选后没有合法矩阵项")
    return selected


def validate_case_result(
    result: dict[str, Any],
    *,
    task_type: str,
    target_formats: tuple[str, ...],
    require_deployment: bool,
    require_workflow: bool,
) -> None:
    """拒绝只有任务成功、但转换或加载推理不完整的假阳性结果。"""

    if result.get("status") != "succeeded":
        raise RuntimeError("端到端用例未成功")
    for required_key in (
        "dataset_version_id",
        "dataset_export_id",
        "training_task_id",
        "model_version_id",
    ):
        if not result.get(required_key):
            raise RuntimeError(f"端到端结果缺少 {required_key}")
    evaluation = result.get("evaluation")
    if not isinstance(evaluation, dict) or evaluation.get("state") != "succeeded":
        raise RuntimeError("端到端结果缺少成功的 evaluation")
    sample_count = evaluation.get("sample_count")
    if not isinstance(sample_count, int) or sample_count <= 0:
        raise RuntimeError("evaluation 没有处理有效样本")
    required_metrics_by_task = {
        "detection": ("map50", "map50_95"),
        "classification": ("top1_accuracy", "top5_accuracy"),
        "segmentation": (
            "map50",
            "map50_95",
            "mask_map50",
            "mask_map50_95",
        ),
        "pose": ("oks_ap50", "oks_ap50_95"),
        "obb": ("map50", "map50_95"),
    }
    required_metrics = required_metrics_by_task.get(task_type)
    if required_metrics is None:
        raise RuntimeError(f"未知 evaluation task_type：{task_type}")
    missing_metrics = [
        metric_name
        for metric_name in required_metrics
        if not isinstance(evaluation.get(metric_name), int | float)
    ]
    if missing_metrics:
        raise RuntimeError(
            f"{task_type} evaluation 缺少指标：{', '.join(missing_metrics)}"
        )
    conversions = result.get("conversions")
    if not isinstance(conversions, dict):
        raise RuntimeError("端到端结果缺少 conversions")
    if set(conversions) != set(target_formats):
        raise RuntimeError(
            f"转换结果不完整：expected={sorted(target_formats)}, "
            f"actual={sorted(conversions)}"
        )
    for target_format in target_formats:
        conversion = conversions[target_format]
        if not isinstance(conversion, dict) or not conversion.get("model_build_id"):
            raise RuntimeError(f"{target_format} 转换没有登记 ModelBuild")
        if not require_deployment:
            continue
        deployment = conversion.get("deployment")
        if not isinstance(deployment, dict):
            raise RuntimeError(f"{target_format} 没有执行 deployment 加载")
        if require_workflow:
            workflow = deployment.get("workflow")
            if not isinstance(workflow, dict):
                raise RuntimeError(f"{target_format} 没有执行 workflow")
            workflow_run = workflow.get("run")
            if (
                not isinstance(workflow_run, dict)
                or workflow_run.get("state") != "succeeded"
            ):
                raise RuntimeError(f"{target_format} workflow 未成功")
            if not workflow_run.get("output_keys"):
                raise RuntimeError(f"{target_format} workflow 没有输出")
        sync_result = deployment.get("sync")
        async_result = deployment.get("async")
        if not isinstance(sync_result, dict) or not isinstance(async_result, dict):
            raise RuntimeError(f"{target_format} 没有完成 sync/async 推理")
        if not sync_result.get("result_summary"):
            raise RuntimeError(f"{target_format} 没有完成 sync 推理")
        async_task = async_result.get("task")
        if not isinstance(async_task, dict) or async_task.get("state") != "succeeded":
            raise RuntimeError(f"{target_format} 没有完成 async 推理")
        for runtime_mode, runtime_result in (
            ("sync", sync_result),
            ("async", async_result),
        ):
            runtime_status = runtime_result.get("status")
            if (
                not isinstance(runtime_status, dict)
                or runtime_status.get("process_state") != "running"
            ):
                raise RuntimeError(
                    f"{target_format} {runtime_mode} deployment 未成功加载"
                )


if __name__ == "__main__":
    raise SystemExit(main())
