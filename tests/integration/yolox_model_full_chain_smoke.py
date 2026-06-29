"""YOLOX 真实短链路验收工具。

该工具用于手动验证 YOLOX detection 在平台里的真实使用链路，不属于默认测试。
验收维度按 DatasetExport 格式拆分：

- `coco`：真实数据导入后导出 `coco-detection-v1`。
- `voc`：真实数据导入后导出 `voc-detection-v1`。

每条链都会执行 DatasetImport、DatasetExport、短训练、评估、转换、deployment
sync / async 推理和 stop / reset。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
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
DEFAULT_MODEL_TYPE = "yolox"
DEFAULT_MODEL_SCALE = "nano"


@dataclass(frozen=True)
class YoloXExportCase:
    """描述 YOLOX detection 的一个 DatasetExport 验收场景。"""

    case_id: str
    task_case: YoloModelTaskCase


def build_yolox_export_cases() -> dict[str, YoloXExportCase]:
    """返回 YOLOX 当前正式验收使用的 DatasetExport 场景。"""

    dataset_dir = PROJECT_ROOT / "data" / "files" / "datasets" / "detection" / "coco128"
    return {
        "coco": YoloXExportCase(
            case_id="coco",
            task_case=YoloModelTaskCase(
                task_type="detection",
                dataset_dir=dataset_dir,
                export_format="coco-detection-v1",
                input_size=(320, 320),
                conversion_route="/models/detection/conversion-tasks",
                deployment_route="/models/detection/deployment-instances",
                inference_route="/models/detection",
            ),
        ),
        "voc": YoloXExportCase(
            case_id="voc",
            task_case=YoloModelTaskCase(
                task_type="detection",
                dataset_dir=dataset_dir,
                export_format="voc-detection-v1",
                input_size=(320, 320),
                conversion_route="/models/detection/conversion-tasks",
                deployment_route="/models/detection/deployment-instances",
                inference_route="/models/detection",
            ),
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""

    args = parse_args(argv)
    run_id = args.run_id or f"yolox-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    run_dir = SMOKE_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "run_id": run_id,
        "model_type": DEFAULT_MODEL_TYPE,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "cases": {},
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
            cases = build_yolox_export_cases()
            for case_id in args.cases:
                export_case = cases[case_id]
                case_run_dir = run_dir / case_id
                case_run_dir.mkdir(parents=True, exist_ok=True)
                try:
                    result["cases"][case_id] = run_task_case(
                        client=client,
                        case=export_case.task_case,
                        run_dir=case_run_dir,
                        project_id=args.project_id,
                        model_type=DEFAULT_MODEL_TYPE,
                        model_scale=args.model_scale,
                        target_formats=args.target_formats,
                        max_epochs=args.max_epochs,
                        batch_size=args.batch_size,
                        gpu_count=args.gpu_count,
                        timeout_seconds=args.task_timeout_seconds,
                        skip_deployment=args.skip_deployment,
                        run_workflow=args.run_workflow,
                        max_images_per_split=args.max_images_per_split,
                    )
                except Exception as error:
                    result["cases"][case_id] = {
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

    cases = build_yolox_export_cases()
    parser = argparse.ArgumentParser(description="运行 YOLOX 真实短链路验收")
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
        "--cases",
        nargs="+",
        choices=tuple(cases),
        default=tuple(cases),
        help="要验证的 YOLOX DatasetExport 场景",
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
        "--gpu-count",
        type=int,
        default=None,
        help="训练请求的 GPU 数量；不指定时沿用服务端默认解析",
    )
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
    parser.add_argument("--port-start", type=int, default=18260)
    parser.add_argument("--port-end", type=int, default=18350)
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
