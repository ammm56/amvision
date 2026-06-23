"""RF-DETR 真实短链路验收工具。

该工具用于手动验证 RF-DETR 在平台里的真实使用链路，不属于默认测试。
默认链路为：

- 真实数据目录打包为 zip。
- 通过公开 API 执行 DatasetImport。
- 通过公开 API 执行 DatasetExport。
- 创建 RF-DETR 训练任务并等待完成。
- 创建 ONNX / OpenVINO / TensorRT 转换任务。
- 创建 deployment，分别验证 sync / async 推理。
- stop / reset deployment，并输出资源和结果摘要。

工具只会停止自己启动的 backend-service / worker，不会停止外部已有进程。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tests.integration.yolo_model_full_chain_smoke import (
    DEFAULT_PROJECT_ID,
    DEFAULT_TOKEN,
    ManagedProcess,
    SmokeApiClient,
    YoloModelTaskCase,
    collect_process_snapshots,
    find_free_port,
    run_task_case,
    start_service_processes,
    stop_managed_processes,
    wait_for_service,
    write_result,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SMOKE_ROOT = PROJECT_ROOT / ".tmp" / "model-full-core-validation"
DEFAULT_MODEL_TYPE = "rfdetr"
DEFAULT_MODEL_SCALE = "nano"


def build_rfdetr_task_cases() -> dict[str, YoloModelTaskCase]:
    """返回 RF-DETR 当前正式验收使用的真实数据资产。"""

    dataset_root = PROJECT_ROOT / "data" / "files" / "datasets"
    return {
        "detection": YoloModelTaskCase(
            task_type="detection",
            dataset_dir=dataset_root / "detection" / "coco128",
            export_format="coco-detection-v1",
            input_size=(384, 384),
            conversion_route="/models/detection/conversion-tasks",
            deployment_route="/models/detection/deployment-instances",
            inference_route="/models/detection",
        ),
        "segmentation": YoloModelTaskCase(
            task_type="segmentation",
            dataset_dir=dataset_root / "segmentation" / "fire-smoke",
            export_format="coco-instance-seg-v1",
            input_size=(384, 384),
            conversion_route="/models/segmentation/conversion-tasks",
            deployment_route="/models/segmentation/deployment-instances",
            inference_route="/models/segmentation",
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""

    args = parse_args(argv)
    run_id = args.run_id or f"rfdetr-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    run_dir = SMOKE_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "run_id": run_id,
        "model_type": DEFAULT_MODEL_TYPE,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "tasks": {},
        "processes": {},
    }
    processes: list[ManagedProcess] = []
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
        try:
            cases = build_rfdetr_task_cases()
            selected_cases = [cases[task_type] for task_type in args.tasks]
            for case in selected_cases:
                try:
                    result["tasks"][case.task_type] = run_task_case(
                        client=client,
                        case=case,
                        run_dir=run_dir,
                        project_id=args.project_id,
                        model_type=DEFAULT_MODEL_TYPE,
                        model_scale=args.model_scale,
                        target_formats=args.target_formats,
                        max_epochs=args.max_epochs,
                        batch_size=args.batch_size,
                        timeout_seconds=args.task_timeout_seconds,
                        skip_deployment=args.skip_deployment,
                        run_workflow=args.run_workflow,
                        max_images_per_split=args.max_images_per_split,
                    )
                except Exception as error:
                    result["tasks"][case.task_type] = {
                        "status": "failed",
                        "finished_at": datetime.now().isoformat(timespec="seconds"),
                        "error": str(error),
                    }
                    raise
        finally:
            client.close()

        result["processes"] = collect_process_snapshots(processes)
        result["finished_at"] = datetime.now().isoformat(timespec="seconds")
        result["status"] = "succeeded"
        write_result(run_dir=run_dir, result=result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        result["finished_at"] = datetime.now().isoformat(timespec="seconds")
        result["status"] = "failed"
        result["error"] = str(error)
        result["processes"] = collect_process_snapshots(processes)
        write_result(run_dir=run_dir, result=result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    finally:
        stop_managed_processes(processes)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析命令行参数。"""

    cases = build_rfdetr_task_cases()
    parser = argparse.ArgumentParser(description="运行 RF-DETR 真实短链路验收")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="已有 backend-service 地址",
    )
    parser.add_argument(
        "--token",
        default=DEFAULT_TOKEN,
        help="调用 API 使用的 Bearer token",
    )
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--model-scale", default=DEFAULT_MODEL_SCALE)
    parser.add_argument(
        "--tasks",
        nargs="+",
        choices=tuple(cases),
        default=tuple(cases),
    )
    parser.add_argument(
        "--target-formats",
        nargs="+",
        choices=("onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine"),
        default=("onnx",),
    )
    parser.add_argument("--max-epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument(
        "--start-processes",
        action="store_true",
        help="由脚本启动 service 和 worker",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="由脚本启动 service 时使用的端口",
    )
    parser.add_argument("--port-start", type=int, default=18160)
    parser.add_argument("--port-end", type=int, default=18250)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--http-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--service-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--task-timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--max-images-per-split",
        type=int,
        default=4,
        help="每个 split 抽取的真实图片数量；0 表示打包完整数据目录",
    )
    parser.add_argument("--skip-deployment", action="store_true")
    parser.add_argument(
        "--run-workflow",
        action="store_true",
        help="deployment sync 验收后继续用正式 workflow app runtime 调用一次",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
