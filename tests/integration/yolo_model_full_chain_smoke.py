"""YOLO 主线真实短链路验收工具。

该工具用于手动验证 YOLOv8 / YOLO11 / YOLO26 在平台里的真实使用链路，不属于默认测试。
默认链路为：

- 真实数据目录打包为 zip。
- 通过公开 API 执行 DatasetImport。
- 通过公开 API 执行 DatasetExport。
- 创建指定 model_type 的训练任务并等待完成。
- 创建 ONNX / OpenVINO / TensorRT 转换任务。
- 创建 deployment，分别验证 sync / async 推理。
- stop / reset deployment，并输出资源和结果摘要。

工具只会停止自己启动的 backend-service / worker，不会停止外部已有进程。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_PREFIX = "/api/v1"
DEFAULT_TOKEN = "amvision-default-user-token"
DEFAULT_PROJECT_ID = "project-1"
DEFAULT_MODEL_TYPE = "yolov8"
DEFAULT_MODEL_SCALE = "nano"
WORKFLOW_EXAMPLES_DIR = PROJECT_ROOT / "docs" / "examples" / "workflows"
SMOKE_ROOT = PROJECT_ROOT / ".tmp" / "yolo-model-full-chain-smoke"

TERMINAL_TASK_STATES = {"succeeded", "failed", "cancelled"}
TERMINAL_RESOURCE_STATES = {"completed", "failed"}


@dataclass(frozen=True)
class YoloModelTaskCase:
    """描述一个 YOLO 主线 task 的真实短链路输入。"""

    task_type: str
    dataset_dir: Path
    export_format: str
    input_size: tuple[int, int]
    conversion_route: str
    deployment_route: str
    inference_route: str
    sample_extensions: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".bmp")


@dataclass(frozen=True)
class ManagedProcess:
    """记录由脚本启动的子进程。"""

    name: str
    process: subprocess.Popen[bytes]
    log_path: Path


WORKFLOW_EXAMPLE_BY_TASK_TYPE = {
    "detection": "detection_deployment_sync_infer_health",
    "classification": "classification_deployment_sync_class_gate",
    "segmentation": "segmentation_deployment_sync_regions_gate",
    "pose": "pose_deployment_sync_presence_gate",
    "obb": "obb_deployment_sync_angle_gate",
}


def build_default_task_cases() -> dict[str, YoloModelTaskCase]:
    """返回本项目当前真实数据资产对应的 YOLO 主线验收任务。"""

    dataset_root = PROJECT_ROOT / "data" / "files" / "datasets"
    return {
        "detection": YoloModelTaskCase(
            task_type="detection",
            dataset_dir=dataset_root / "detection" / "medical-pills",
            export_format="yolo-detection-v1",
            input_size=(320, 320),
            conversion_route="/models/detection/conversion-tasks",
            deployment_route="/models/detection/deployment-instances",
            inference_route="/models/detection",
        ),
        "classification": YoloModelTaskCase(
            task_type="classification",
            dataset_dir=dataset_root / "classification" / "computerasurfacedefect",
            export_format="imagenet-classification-v1",
            input_size=(224, 224),
            conversion_route="/models/classification/conversion-tasks",
            deployment_route="/models/classification/deployment-instances",
            inference_route="/models/classification",
        ),
        "segmentation": YoloModelTaskCase(
            task_type="segmentation",
            dataset_dir=dataset_root / "segmentation" / "package-seg",
            export_format="yolo-instance-seg-v1",
            input_size=(320, 320),
            conversion_route="/models/segmentation/conversion-tasks",
            deployment_route="/models/segmentation/deployment-instances",
            inference_route="/models/segmentation",
        ),
        "pose": YoloModelTaskCase(
            task_type="pose",
            dataset_dir=dataset_root / "pose" / "hand-keypoints",
            export_format="yolo-pose-v1",
            input_size=(320, 320),
            conversion_route="/models/pose/conversion-tasks",
            deployment_route="/models/pose/deployment-instances",
            inference_route="/models/pose",
        ),
        "obb": YoloModelTaskCase(
            task_type="obb",
            dataset_dir=dataset_root / "detection" / "dota128",
            export_format="dota-obb-v1",
            input_size=(320, 320),
            conversion_route="/models/obb/conversion-tasks",
            deployment_route="/models/obb/deployment-instances",
            inference_route="/models/obb",
        ),
    }


class SmokeApiClient:
    """封装本地验收脚本使用的 HTTP API 调用。"""

    def __init__(self, *, base_url: str, token: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.client = httpx.Client(
            base_url=f"{self.base_url}{API_PREFIX}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout_seconds),
        )

    def close(self) -> None:
        """关闭底层 HTTP client。"""

        self.client.close()

    def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """执行 GET 并返回 JSON 对象。"""

        response = self.client.get(path, **kwargs)
        return self._read_json_response(response=response, method="GET", path=path)

    def post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """执行 POST 并返回 JSON 对象。"""

        response = self.client.post(path, **kwargs)
        return self._read_json_response(response=response, method="POST", path=path)

    def put(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """执行 PUT 并返回 JSON 对象。"""

        response = self.client.put(path, **kwargs)
        return self._read_json_response(response=response, method="PUT", path=path)

    def post_no_json(self, path: str, **kwargs: Any) -> None:
        """执行不要求 JSON 响应的 POST。"""

        response = self.client.post(path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(
                f"POST {path} failed: {response.status_code} {response.text}"
            )

    @staticmethod
    def _read_json_response(
        *, response: httpx.Response, method: str, path: str
    ) -> dict[str, Any]:
        """读取 JSON 响应，并把错误响应转成可读异常。"""

        if response.status_code >= 400:
            raise RuntimeError(
                f"{method} {path} failed: {response.status_code} {response.text}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"{method} {path} did not return JSON object: {payload!r}"
            )
        return payload


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""

    args = parse_args(argv)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d%H%M%S")
    run_dir = SMOKE_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "run_id": run_id,
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
            base_url=base_url, timeout_seconds=args.service_timeout_seconds
        )

        client = SmokeApiClient(
            base_url=base_url,
            token=args.token,
            timeout_seconds=args.http_timeout_seconds,
        )
        try:
            cases = build_default_task_cases()
            selected_cases = [cases[task_type] for task_type in args.tasks]
            for case in selected_cases:
                try:
                    result["tasks"][case.task_type] = run_task_case(
                        client=client,
                        case=case,
                        run_dir=run_dir,
                        project_id=args.project_id,
                        model_type=args.model_type,
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

    cases = build_default_task_cases()
    parser = argparse.ArgumentParser(description="运行 YOLO 主线真实短链路验收")
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:8000", help="已有 backend-service 地址"
    )
    parser.add_argument(
        "--token", default=DEFAULT_TOKEN, help="调用 API 使用的 Bearer token"
    )
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--model-type", default=DEFAULT_MODEL_TYPE)
    parser.add_argument("--model-scale", default=DEFAULT_MODEL_SCALE)
    parser.add_argument(
        "--tasks", nargs="+", choices=tuple(cases), default=tuple(cases)
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
        "--start-processes", action="store_true", help="由脚本启动 service 和 worker"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="由脚本启动 service 时使用的端口"
    )
    parser.add_argument("--port-start", type=int, default=18080)
    parser.add_argument("--port-end", type=int, default=18150)
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


def start_service_processes(
    *,
    run_dir: Path,
    port: int,
    service_timeout_seconds: float,
) -> list[ManagedProcess]:
    """按真实发布顺序启动 backend-service 和 worker。

    说明：
    - backend-service 负责数据库 schema、seeder 和 runtime 控制面初始化。
    - worker 只负责消费队列；必须等 service health 可用后再启动。
    """

    process_env = os.environ.copy()
    process_env.setdefault("AMVISION_TASK_MANAGER__ENABLED", "false")
    service_log = run_dir / "backend-service.log"
    worker_log = run_dir / "backend-worker.log"
    processes: list[ManagedProcess] = []
    try:
        service_process = start_process(
            name="backend-service",
            args=[
                sys.executable,
                "-m",
                "uvicorn",
                "backend.service.api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=process_env,
            log_path=service_log,
        )
        processes.append(service_process)
        wait_for_service(
            base_url=f"http://127.0.0.1:{port}",
            timeout_seconds=service_timeout_seconds,
        )

        worker_process = start_process(
            name="backend-worker",
            args=[sys.executable, "-m", "backend.workers.main"],
            env=process_env,
            log_path=worker_log,
        )
        processes.append(worker_process)
        ensure_managed_processes_running(processes, startup_wait_seconds=2.0)
        return processes
    except Exception:
        stop_managed_processes(processes)
        raise


def start_process(
    *,
    name: str,
    args: list[str],
    env: dict[str, str],
    log_path: Path,
) -> ManagedProcess:
    """启动一个隐藏窗口子进程并写入日志。"""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("ab")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        args,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
    )
    return ManagedProcess(name=name, process=process, log_path=log_path)


def stop_managed_processes(processes: Iterable[ManagedProcess]) -> None:
    """停止本脚本启动的进程。"""

    for item in processes:
        if item.process.poll() is not None:
            continue
        item.process.terminate()
        try:
            item.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            item.process.kill()
            item.process.wait(timeout=10)


def ensure_managed_processes_running(
    processes: Iterable[ManagedProcess],
    *,
    startup_wait_seconds: float,
) -> None:
    """确认托管子进程没有在启动后立刻退出。"""

    time.sleep(max(0.1, startup_wait_seconds))
    failed_processes: list[str] = []
    for item in processes:
        return_code = item.process.poll()
        if return_code is None:
            continue
        failed_processes.append(
            f"{item.name} returncode={return_code} log={item.log_path}"
        )
    if failed_processes:
        raise RuntimeError("托管子进程启动失败：" + "; ".join(failed_processes))


def wait_for_service(*, base_url: str, timeout_seconds: float) -> None:
    """等待 backend-service health endpoint 可用。"""

    deadline = time.monotonic() + timeout_seconds
    health_url = f"{base_url.rstrip('/')}{API_PREFIX}/system/health"
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(health_url, timeout=5.0)
            if response.status_code < 500:
                return
            last_error = f"{response.status_code} {response.text}"
        except Exception as error:  # noqa: BLE001 - 启动探测需要保留最后一次错误。
            last_error = str(error)
        time.sleep(1.0)
    raise RuntimeError(
        f"backend-service 未在 {timeout_seconds:.0f}s 内就绪：{last_error}"
    )


def run_task_case(
    *,
    client: SmokeApiClient,
    case: YoloModelTaskCase,
    run_dir: Path,
    project_id: str,
    model_type: str,
    model_scale: str,
    target_formats: tuple[str, ...],
    max_epochs: int,
    batch_size: int,
    timeout_seconds: float,
    skip_deployment: bool,
    run_workflow: bool,
    max_images_per_split: int,
) -> dict[str, Any]:
    """运行单个 task_type 的完整短链路。"""

    if not case.dataset_dir.is_dir():
        raise RuntimeError(f"{case.task_type} 数据集目录不存在：{case.dataset_dir}")

    started_at = datetime.now().isoformat(timespec="seconds")
    zip_path = build_dataset_zip(
        case=case,
        run_dir=run_dir,
        max_images_per_split=max_images_per_split,
    )
    sample_image_path = find_sample_image(case.dataset_dir, case.sample_extensions)
    dataset_id = build_dataset_id(
        model_type=model_type, task_type=case.task_type, run_id=run_dir.name
    )
    dataset_import = submit_dataset_import(
        client=client,
        project_id=project_id,
        dataset_id=dataset_id,
        task_type=case.task_type,
        zip_path=zip_path,
    )
    dataset_import_detail = poll_resource(
        label=f"{case.task_type} dataset import",
        fetch=lambda: client.get(
            f"/datasets/imports/{dataset_import['dataset_import_id']}"
        ),
        state_reader=lambda payload: str(payload.get("status")),
        timeout_seconds=timeout_seconds,
    )
    dataset_version_id = read_required_string(
        dataset_import_detail, "dataset_version_id"
    )

    dataset_export = submit_dataset_export(
        client=client,
        project_id=project_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        export_format=case.export_format,
        task_type=case.task_type,
    )
    dataset_export_detail = poll_resource(
        label=f"{case.task_type} dataset export",
        fetch=lambda: client.get(
            f"/datasets/exports/{dataset_export['dataset_export_id']}"
        ),
        state_reader=lambda payload: str(payload.get("status")),
        timeout_seconds=timeout_seconds,
    )
    dataset_export_id = read_required_string(dataset_export_detail, "dataset_export_id")
    manifest_key = read_required_string(dataset_export_detail, "manifest_object_key")

    output_model_name = build_output_model_name(
        model_type=model_type,
        task_type=case.task_type,
        model_scale=model_scale,
    )
    training = submit_training_task(
        client=client,
        case=case,
        project_id=project_id,
        model_type=model_type,
        model_scale=model_scale,
        dataset_export_id=dataset_export_id,
        manifest_key=manifest_key,
        output_model_name=output_model_name,
        max_epochs=max_epochs,
        batch_size=batch_size,
    )
    training_detail = poll_task(
        client=client,
        task_id=read_required_string(training, "task_id"),
        label=f"{case.task_type} training",
        timeout_seconds=timeout_seconds,
    )
    model_version_id = find_required_string(
        training_detail,
        ("model_version_id", "output_model_version_id"),
    )
    evaluation = submit_evaluation_task(
        client=client,
        case=case,
        project_id=project_id,
        model_type=model_type,
        model_version_id=model_version_id,
        dataset_export_id=dataset_export_id,
        manifest_key=manifest_key,
    )
    evaluation_detail = poll_evaluation_task(
        client=client,
        case=case,
        task_id=read_required_string(evaluation, "task_id"),
        label=f"{case.task_type} evaluation",
        timeout_seconds=timeout_seconds,
    )

    conversions: dict[str, Any] = {}
    for target_format in target_formats:
        conversion = submit_conversion_task(
            client=client,
            case=case,
            project_id=project_id,
            model_type=model_type,
            source_model_version_id=model_version_id,
            target_format=target_format,
        )
        conversion_task_id = read_required_string(conversion, "task_id")
        conversion_detail = poll_conversion_task(
            client=client,
            case=case,
            task_id=conversion_task_id,
            label=f"{case.task_type} {target_format} conversion",
            timeout_seconds=timeout_seconds,
        )
        build = select_conversion_build(conversion_detail, target_format=target_format)
        conversion_summary: dict[str, Any] = {
            "task_id": conversion_task_id,
            "model_build_id": build.get("model_build_id"),
            "build_format": build.get("build_format"),
            "deployment": None,
        }
        if not skip_deployment:
            deployment_summary = run_deployment_smoke(
                client=client,
                case=case,
                project_id=project_id,
                model_type=model_type,
                model_build_id=read_required_string(build, "model_build_id"),
                target_format=target_format,
                sample_image_path=sample_image_path,
                timeout_seconds=timeout_seconds,
                run_workflow=run_workflow,
            )
            conversion_summary["deployment"] = deployment_summary
        conversions[target_format] = conversion_summary

    return {
        "status": "succeeded",
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_dir": str(case.dataset_dir),
        "dataset_zip": str(zip_path),
        "sample_image": str(sample_image_path),
        "dataset_import_id": dataset_import["dataset_import_id"],
        "dataset_version_id": dataset_version_id,
        "dataset_export_id": dataset_export_id,
        "dataset_export_format": case.export_format,
        "training_task_id": training["task_id"],
        "model_version_id": model_version_id,
        "evaluation": summarize_evaluation_payload(evaluation_detail),
        "conversions": conversions,
    }


def build_dataset_zip(
    *,
    case: YoloModelTaskCase,
    run_dir: Path,
    max_images_per_split: int,
) -> Path:
    """把真实数据目录打包为 API 上传使用的 zip。"""

    zip_dir = run_dir / "datasets"
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = zip_dir / f"{case.task_type}.zip"
    selected_paths = collect_smoke_dataset_paths(
        case=case,
        max_images_per_split=max_images_per_split,
    )
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(case.dataset_dir.rglob("*")):
            if not file_path.is_file():
                continue
            relative_path = file_path.relative_to(case.dataset_dir)
            if should_include_smoke_dataset_file(
                relative_path=relative_path,
                selected_paths=selected_paths,
                sample_extensions=case.sample_extensions,
            ):
                filtered_coco_payload = build_filtered_coco_annotation_payload(
                    file_path=file_path,
                    selected_paths=selected_paths,
                    sample_extensions=case.sample_extensions,
                )
                if filtered_coco_payload is not None:
                    archive.writestr(
                        relative_path.as_posix(),
                        json.dumps(filtered_coco_payload, ensure_ascii=False),
                    )
                    continue
                archive.write(file_path, relative_path.as_posix())
    return zip_path


def collect_smoke_dataset_paths(
    *,
    case: YoloModelTaskCase,
    max_images_per_split: int,
) -> set[Path] | None:
    """从真实数据集中抽取短链路验收需要的图片和配套 label。"""

    if max_images_per_split <= 0:
        return None

    selected_paths: set[Path] = set()
    for split_name in ("train", "val", "valid", "test"):
        image_paths = collect_split_image_paths(
            dataset_dir=case.dataset_dir,
            split_name=split_name,
            sample_extensions=case.sample_extensions,
        )
        for image_path in image_paths[:max_images_per_split]:
            relative_image_path = image_path.relative_to(case.dataset_dir)
            selected_paths.add(relative_image_path)
            selected_paths.update(
                resolve_matching_label_paths(
                    dataset_dir=case.dataset_dir,
                    relative_image_path=relative_image_path,
                )
            )

    if selected_paths:
        return selected_paths

    fallback_images = [
        path
        for path in sorted(
            case.dataset_dir.rglob("*"), key=lambda item: item.as_posix().lower()
        )
        if path.is_file() and path.suffix.lower() in case.sample_extensions
    ][:max_images_per_split]
    for image_path in fallback_images:
        relative_image_path = image_path.relative_to(case.dataset_dir)
        selected_paths.add(relative_image_path)
        selected_paths.update(
            resolve_matching_label_paths(
                dataset_dir=case.dataset_dir,
                relative_image_path=relative_image_path,
            )
        )
    return selected_paths


def collect_split_image_paths(
    *,
    dataset_dir: Path,
    split_name: str,
    sample_extensions: tuple[str, ...],
) -> list[Path]:
    """按常见数据集目录收集某个 split 的图片。"""

    candidate_roots = (
        dataset_dir / "images" / split_name,
        dataset_dir / split_name,
    )
    image_paths: list[Path] = []
    for candidate_root in candidate_roots:
        if not candidate_root.is_dir():
            continue
        image_paths.extend(
            path
            for path in sorted(
                candidate_root.rglob("*"), key=lambda item: item.as_posix().lower()
            )
            if path.is_file() and path.suffix.lower() in sample_extensions
        )
    return image_paths


def resolve_matching_label_paths(
    *,
    dataset_dir: Path,
    relative_image_path: Path,
) -> set[Path]:
    """根据图片相对路径推导 YOLO / DOTA 风格 label 路径。"""

    parts = relative_image_path.parts
    if len(parts) < 3 or parts[0] != "images":
        return set()

    split_name = parts[1]
    label_tail = Path(*parts[2:]).with_suffix(".txt")
    label_split_names = {split_name}
    if split_name == "valid":
        label_split_names.add("val")

    candidate_paths: set[Path] = set()
    for label_split_name in label_split_names:
        for relative_label_path in (
            Path("labels") / label_split_name / label_tail,
            Path("labels") / f"{label_split_name}_original" / label_tail,
        ):
            if (dataset_dir / relative_label_path).is_file():
                candidate_paths.add(relative_label_path)
    return candidate_paths


def should_include_smoke_dataset_file(
    *,
    relative_path: Path,
    selected_paths: set[Path] | None,
    sample_extensions: tuple[str, ...],
) -> bool:
    """判断某个文件是否需要进入短链路验收 zip。"""

    if selected_paths is None:
        return True
    if relative_path.suffix.lower() in sample_extensions:
        return relative_path in selected_paths
    if (
        relative_path.parts
        and relative_path.parts[0] == "labels"
        and relative_path.suffix.lower() == ".txt"
    ):
        return relative_path in selected_paths
    return True


def build_filtered_coco_annotation_payload(
    *,
    file_path: Path,
    selected_paths: set[Path] | None,
    sample_extensions: tuple[str, ...],
) -> dict[str, object] | None:
    """按短链路抽样图片裁剪 COCO annotation。"""

    if selected_paths is None or file_path.suffix.lower() != ".json":
        return None
    selected_file_names = {
        selected_path.name
        for selected_path in selected_paths
        if selected_path.suffix.lower() in sample_extensions
    }
    if not selected_file_names:
        return None
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    images = payload.get("images")
    annotations = payload.get("annotations")
    if not isinstance(images, list) or not isinstance(annotations, list):
        return None
    kept_images: list[dict[str, object]] = []
    kept_image_ids: set[object] = set()
    for image_payload in images:
        if not isinstance(image_payload, dict):
            continue
        file_name = Path(str(image_payload.get("file_name") or "")).name
        if file_name not in selected_file_names:
            continue
        kept_images.append(dict(image_payload))
        kept_image_ids.add(image_payload.get("id"))
    if not kept_images:
        return None
    filtered_payload = dict(payload)
    filtered_payload["images"] = kept_images
    filtered_payload["annotations"] = [
        dict(annotation_payload)
        for annotation_payload in annotations
        if isinstance(annotation_payload, dict)
        and annotation_payload.get("image_id") in kept_image_ids
    ]
    return filtered_payload


def find_sample_image(dataset_dir: Path, sample_extensions: tuple[str, ...]) -> Path:
    """从数据集中找一张推理验收图片。"""

    for file_path in sorted(dataset_dir.rglob("*")):
        if file_path.is_file() and file_path.suffix.lower() in sample_extensions:
            return file_path
    raise RuntimeError(f"数据集中找不到可用于推理的图片：{dataset_dir}")


def submit_dataset_import(
    *,
    client: SmokeApiClient,
    project_id: str,
    dataset_id: str,
    task_type: str,
    zip_path: Path,
) -> dict[str, Any]:
    """提交 DatasetImport。"""

    with zip_path.open("rb") as file_obj:
        return client.post(
            "/datasets/imports",
            data={
                "project_id": project_id,
                "dataset_id": dataset_id,
                "task_type": task_type,
                "split_strategy": "auto",
            },
            files={"package": (zip_path.name, file_obj, "application/zip")},
        )


def submit_dataset_export(
    *,
    client: SmokeApiClient,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    export_format: str,
    task_type: str,
) -> dict[str, Any]:
    """提交 DatasetExport。"""

    return client.post(
        "/datasets/exports",
        json={
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "format_id": export_format,
            "display_name": f"smoke {task_type} export",
            "include_test_split": True,
        },
    )


def submit_training_task(
    *,
    client: SmokeApiClient,
    case: YoloModelTaskCase,
    project_id: str,
    model_type: str,
    model_scale: str,
    dataset_export_id: str,
    manifest_key: str,
    output_model_name: str,
    max_epochs: int,
    batch_size: int,
) -> dict[str, Any]:
    """提交训练任务。"""

    payload: dict[str, Any] = {
        "project_id": project_id,
        "model_type": model_type,
        "dataset_export_id": dataset_export_id,
        "dataset_export_manifest_key": manifest_key,
        "recipe_id": "default",
        "model_scale": model_scale,
        "output_model_name": output_model_name,
        "max_epochs": max_epochs,
        "batch_size": batch_size,
        "input_size": list(case.input_size),
        "precision": "fp32",
        "extra_options": {
            "num_workers": 0,
            "smoke_validation": True,
        },
        "display_name": f"smoke {model_type} {case.task_type}",
    }
    if case.task_type in {"detection", "pose", "obb"}:
        payload["evaluation_interval"] = 1
    return client.post(
        f"/models/{case.task_type}/training-tasks",
        json=payload,
    )


def submit_evaluation_task(
    *,
    client: SmokeApiClient,
    case: YoloModelTaskCase,
    project_id: str,
    model_type: str,
    model_version_id: str,
    dataset_export_id: str,
    manifest_key: str,
) -> dict[str, Any]:
    """提交独立 evaluation task。"""

    payload: dict[str, Any] = {
        "project_id": project_id,
        "model_version_id": model_version_id,
        "dataset_export_id": dataset_export_id,
        "dataset_export_manifest_key": manifest_key,
        "save_result_package": True,
        "extra_options": {"smoke_validation": True},
        "display_name": f"smoke {model_type} {case.task_type} evaluation",
    }
    if case.task_type == "detection":
        payload["model_type"] = model_type
        payload["score_threshold"] = 0.01
    elif case.task_type == "classification":
        payload["top_k"] = 5
    elif case.task_type == "segmentation":
        payload["score_threshold"] = 0.01
        payload["mask_threshold"] = 0.5
    elif case.task_type in {"pose", "obb"}:
        payload["score_threshold"] = 0.01
    return client.post(
        f"/models/{case.task_type}/evaluation-tasks",
        json=payload,
    )


def submit_conversion_task(
    *,
    client: SmokeApiClient,
    case: YoloModelTaskCase,
    project_id: str,
    model_type: str,
    source_model_version_id: str,
    target_format: str,
) -> dict[str, Any]:
    """提交转换任务。"""

    if case.task_type == "detection":
        endpoint_by_format = {
            "onnx": "/models/detection/conversion-tasks/onnx",
            "onnx-optimized": "/models/detection/conversion-tasks/onnx-optimized",
            "openvino-ir": "/models/detection/conversion-tasks/openvino-ir-fp32",
            "tensorrt-engine": "/models/detection/conversion-tasks/tensorrt-engine-fp32",
        }
        return client.post(
            endpoint_by_format[target_format],
            json={
                "project_id": project_id,
                "model_type": model_type,
                "source_model_version_id": source_model_version_id,
                "extra_options": {},
                "display_name": f"smoke {model_type} detection {target_format}",
            },
        )
    return client.post(
        case.conversion_route,
        json={
            "project_id": project_id,
            "model_type": model_type,
            "source_model_version_id": source_model_version_id,
            "target_formats": [target_format],
            "extra_options": {},
            "display_name": f"smoke {model_type} {case.task_type} {target_format}",
        },
    )


def run_deployment_smoke(
    *,
    client: SmokeApiClient,
    case: YoloModelTaskCase,
    project_id: str,
    model_type: str,
    model_build_id: str,
    target_format: str,
    sample_image_path: Path,
    timeout_seconds: float,
    run_workflow: bool,
) -> dict[str, Any]:
    """用转换产物创建 deployment，并验证 sync / async 推理。"""

    runtime_backend = resolve_runtime_backend(target_format)
    deployment = client.post(
        case.deployment_route,
        json={
            "project_id": project_id,
            "model_type": model_type,
            "model_build_id": model_build_id,
            "runtime_backend": runtime_backend,
            "runtime_precision": "fp32",
            "instance_count": 1,
            "display_name": f"smoke {model_type} {case.task_type} {target_format}",
            "metadata": {"smoke_validation": True},
        },
    )
    deployment_id = read_required_string(deployment, "deployment_instance_id")
    sync_result: dict[str, Any] = {}
    async_result: dict[str, Any] = {}
    workflow_result: dict[str, Any] | None = None
    try:
        client.post(f"{case.deployment_route}/{deployment_id}/sync/start")
        sync_status = client.get(f"{case.deployment_route}/{deployment_id}/sync/status")
        direct_result = submit_direct_inference(
            client=client,
            case=case,
            deployment_id=deployment_id,
            model_type=model_type,
            sample_image_path=sample_image_path,
        )
        sync_result = {
            "status": sync_status,
            "result_summary": summarize_inference_payload(direct_result),
        }
        if run_workflow:
            workflow_result = run_workflow_app_runtime_smoke(
                client=client,
                case=case,
                project_id=project_id,
                model_type=model_type,
                deployment_id=deployment_id,
                sample_image_path=sample_image_path,
                timeout_seconds=timeout_seconds,
            )
        client.post(f"{case.deployment_route}/{deployment_id}/sync/reset")
        client.post(f"{case.deployment_route}/{deployment_id}/sync/stop")

        client.post(f"{case.deployment_route}/{deployment_id}/async/start")
        async_status = client.get(
            f"{case.deployment_route}/{deployment_id}/async/status"
        )
        async_task = submit_async_inference(
            client=client,
            case=case,
            project_id=project_id,
            deployment_id=deployment_id,
            model_type=model_type,
            sample_image_path=sample_image_path,
        )
        async_task_id = read_required_string(async_task, "task_id")
        async_detail = poll_inference_task(
            client=client,
            case=case,
            task_id=async_task_id,
            label=f"{case.task_type} async inference",
            timeout_seconds=timeout_seconds,
        )
        async_payload = client.get(
            f"{case.inference_route}/inference-tasks/{async_task_id}/result"
        )
        client.post(f"{case.deployment_route}/{deployment_id}/async/reset")
        client.post(f"{case.deployment_route}/{deployment_id}/async/stop")
        async_result = {
            "status": async_status,
            "task": summarize_task_payload(async_detail),
            "result": summarize_inference_payload(async_payload),
        }
    finally:
        safe_stop_deployment(client=client, case=case, deployment_id=deployment_id)
    return {
        "deployment_instance_id": deployment_id,
        "runtime_backend": runtime_backend,
        "sync": sync_result,
        "async": async_result,
        "workflow": workflow_result,
    }


def run_workflow_app_runtime_smoke(
    *,
    client: SmokeApiClient,
    case: YoloModelTaskCase,
    project_id: str,
    model_type: str,
    deployment_id: str,
    sample_image_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    """用正式 workflow 示例调用当前 sync deployment。"""

    example_name = WORKFLOW_EXAMPLE_BY_TASK_TYPE[case.task_type]
    template, application = load_workflow_example_documents(example_name)
    save_workflow_example_documents(
        client=client,
        project_id=project_id,
        template=template,
        application=application,
    )
    runtime_payload = client.post(
        "/workflows/app-runtimes",
        json={
            "project_id": project_id,
            "application_id": application["application_id"],
            "display_name": f"smoke {model_type} {case.task_type} workflow",
            "request_timeout_seconds": max(30, int(timeout_seconds)),
            "metadata": {
                "smoke_validation": True,
                "model_type": model_type,
                "task_type": case.task_type,
            },
        },
    )
    workflow_runtime_id = read_required_string(runtime_payload, "workflow_runtime_id")
    try:
        start_payload = client.post(
            f"/workflows/app-runtimes/{workflow_runtime_id}/start"
        )
        invoke_payload = client.post(
            f"/workflows/app-runtimes/{workflow_runtime_id}/invoke",
            json={
                "input_bindings": {
                    "request_image": build_image_base64_payload(sample_image_path),
                    "deployment_request": {
                        "value": {"deployment_instance_id": deployment_id}
                    },
                },
                "execution_metadata": {
                    "scenario": "yolo-model-full-chain-workflow-smoke",
                    "model_type": model_type,
                    "task_type": case.task_type,
                    "deployment_instance_id": deployment_id,
                },
                "timeout_seconds": max(30, int(timeout_seconds)),
            },
        )
        workflow_run_id = read_required_string(invoke_payload, "workflow_run_id")
        run_payload = client.get(f"/workflows/runs/{workflow_run_id}")
        workflow_state = str(run_payload.get("state") or invoke_payload.get("state"))
        if workflow_state != "succeeded":
            summary = summarize_workflow_payload(run_payload)
            raise RuntimeError(
                f"workflow {example_name} failed: "
                f"{json.dumps(summary, ensure_ascii=False)}"
            )
        return {
            "example_name": example_name,
            "workflow_runtime_id": workflow_runtime_id,
            "workflow_run_id": workflow_run_id,
            "start": summarize_workflow_payload(start_payload),
            "invoke": summarize_workflow_payload(invoke_payload),
            "run": summarize_workflow_payload(run_payload),
        }
    finally:
        try:
            client.post(f"/workflows/app-runtimes/{workflow_runtime_id}/stop")
        except Exception:
            pass


def load_workflow_example_documents(
    example_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """读取正式 workflow 示例 template 和 application。"""

    template_path = WORKFLOW_EXAMPLES_DIR / f"{example_name}.template.json"
    application_path = WORKFLOW_EXAMPLES_DIR / f"{example_name}.application.json"
    return (
        json.loads(template_path.read_text(encoding="utf-8")),
        json.loads(application_path.read_text(encoding="utf-8")),
    )


def save_workflow_example_documents(
    *,
    client: SmokeApiClient,
    project_id: str,
    template: dict[str, Any],
    application: dict[str, Any],
) -> None:
    """通过公开 API 保存 workflow 示例文档。"""

    client.put(
        (
            f"/workflows/projects/{project_id}/templates/{template['template_id']}"
            f"/versions/{template['template_version']}"
        ),
        json={"template": template},
    )
    client.put(
        f"/workflows/projects/{project_id}/applications/{application['application_id']}",
        json={"application": application},
    )


def build_image_base64_payload(sample_image_path: Path) -> dict[str, str]:
    """把本地样例图编码成 workflow image-base64.v1 payload。"""

    return {
        "image_base64": base64.b64encode(sample_image_path.read_bytes()).decode("ascii"),
        "media_type": resolve_image_media_type(sample_image_path),
    }


def resolve_image_media_type(sample_image_path: Path) -> str:
    """根据文件扩展名返回常见图片 media type。"""

    suffix = sample_image_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".bmp":
        return "image/bmp"
    return "image/png"


def submit_direct_inference(
    *,
    client: SmokeApiClient,
    case: YoloModelTaskCase,
    deployment_id: str,
    model_type: str,
    sample_image_path: Path,
) -> dict[str, Any]:
    """提交同步直返推理。"""

    with sample_image_path.open("rb") as file_obj:
        return client.post(
            f"{case.inference_route}/deployment-instances/{deployment_id}/infer",
            data=build_inference_form_payload(
                case=case,
                model_type=model_type,
                async_request=False,
            ),
            files={"input_image": (sample_image_path.name, file_obj, "image/jpeg")},
        )


def submit_async_inference(
    *,
    client: SmokeApiClient,
    case: YoloModelTaskCase,
    project_id: str,
    deployment_id: str,
    model_type: str,
    sample_image_path: Path,
) -> dict[str, Any]:
    """提交异步推理任务。"""

    with sample_image_path.open("rb") as file_obj:
        return client.post(
            f"{case.inference_route}/inference-tasks",
            data={
                "project_id": project_id,
                "deployment_instance_id": deployment_id,
                **build_inference_form_payload(
                    case=case,
                    model_type=model_type,
                    async_request=True,
                ),
            },
            files={"input_image": (sample_image_path.name, file_obj, "image/jpeg")},
        )


def build_inference_form_payload(
    *,
    case: YoloModelTaskCase,
    model_type: str,
    async_request: bool,
) -> dict[str, str]:
    """根据 task_type 构造推理表单字段。"""

    payload = {
        "model_type": model_type,
        "input_transport_mode": "storage",
        "save_result_image": "true",
        "return_preview_image_base64": "false",
        "extra_options": "{}",
    }
    if async_request:
        payload["display_name"] = f"smoke {case.task_type} inference"
    if case.task_type == "classification":
        payload["top_k"] = "5"
    elif case.task_type == "segmentation":
        payload["score_threshold"] = "0.25"
        payload["mask_threshold"] = "0.5"
    else:
        payload["score_threshold"] = "0.25"
    return payload


def poll_resource(
    *,
    label: str,
    fetch: Callable[[], dict[str, Any]],
    state_reader: Callable[[dict[str, Any]], str],
    timeout_seconds: float,
) -> dict[str, Any]:
    """轮询 DatasetImport / DatasetExport 资源直到完成。"""

    return poll_until(
        label=label,
        fetch=fetch,
        state_reader=state_reader,
        success_states={"completed"},
        failure_states={"failed"},
        timeout_seconds=timeout_seconds,
    )


def poll_task(
    *,
    client: SmokeApiClient,
    task_id: str,
    label: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """轮询通用任务直到结束。"""

    return poll_until(
        label=label,
        fetch=lambda: client.get(
            f"/tasks/{task_id}", params={"include_events": "true"}
        ),
        state_reader=lambda payload: str(payload.get("state")),
        success_states={"succeeded"},
        failure_states=TERMINAL_TASK_STATES - {"succeeded"},
        timeout_seconds=timeout_seconds,
    )


def poll_conversion_task(
    *,
    client: SmokeApiClient,
    case: YoloModelTaskCase,
    task_id: str,
    label: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """轮询转换任务直到结束。"""

    return poll_until(
        label=label,
        fetch=lambda: client.get(
            f"{case.conversion_route}/{task_id}", params={"include_events": "true"}
        ),
        state_reader=lambda payload: str(payload.get("state")),
        success_states={"succeeded"},
        failure_states=TERMINAL_TASK_STATES - {"succeeded"},
        timeout_seconds=timeout_seconds,
    )


def poll_evaluation_task(
    *,
    client: SmokeApiClient,
    case: YoloModelTaskCase,
    task_id: str,
    label: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """轮询 evaluation task 直到结束。"""

    return poll_until(
        label=label,
        fetch=lambda: client.get(
            f"/models/{case.task_type}/evaluation-tasks/{task_id}",
            params={"include_events": "true"},
        ),
        state_reader=lambda payload: str(payload.get("state")),
        success_states={"succeeded"},
        failure_states=TERMINAL_TASK_STATES - {"succeeded"},
        timeout_seconds=timeout_seconds,
    )


def poll_inference_task(
    *,
    client: SmokeApiClient,
    case: YoloModelTaskCase,
    task_id: str,
    label: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """轮询异步推理任务直到结束。"""

    return poll_until(
        label=label,
        fetch=lambda: client.get(f"{case.inference_route}/inference-tasks/{task_id}"),
        state_reader=lambda payload: str(payload.get("state")),
        success_states={"succeeded"},
        failure_states=TERMINAL_TASK_STATES - {"succeeded"},
        timeout_seconds=timeout_seconds,
    )


def poll_until(
    *,
    label: str,
    fetch: Callable[[], dict[str, Any]],
    state_reader: Callable[[dict[str, Any]], str],
    success_states: set[str],
    failure_states: set[str],
    timeout_seconds: float,
) -> dict[str, Any]:
    """通用轮询辅助。"""

    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        payload = fetch()
        last_payload = payload
        state = state_reader(payload)
        if state in success_states:
            return payload
        if state in failure_states:
            raise RuntimeError(
                f"{label} failed: {json.dumps(payload, ensure_ascii=False)[:4000]}"
            )
        time.sleep(2.0)
    raise RuntimeError(
        f"{label} timed out: {json.dumps(last_payload, ensure_ascii=False)[:4000]}"
    )


def select_conversion_build(
    payload: dict[str, Any], *, target_format: str
) -> dict[str, Any]:
    """从 conversion 详情中选择目标 ModelBuild。"""

    builds = payload.get("builds")
    if not isinstance(builds, list) or not builds:
        raise RuntimeError(f"conversion 没有登记 ModelBuild：{payload}")
    for build in builds:
        if isinstance(build, dict) and build.get("build_format") == target_format:
            return build
    for build in builds:
        if isinstance(build, dict):
            return build
    raise RuntimeError(f"conversion builds 格式无效：{builds}")


def resolve_runtime_backend(target_format: str) -> str:
    """根据转换格式选择 deployment runtime backend。"""

    return {
        "onnx": "onnxruntime",
        "onnx-optimized": "onnxruntime",
        "openvino-ir": "openvino",
        "tensorrt-engine": "tensorrt",
    }[target_format]


def safe_stop_deployment(
    *, client: SmokeApiClient, case: YoloModelTaskCase, deployment_id: str
) -> None:
    """尽量停止 deployment，避免失败时残留子进程。"""

    for runtime_mode in ("sync", "async"):
        try:
            client.post_no_json(
                f"{case.deployment_route}/{deployment_id}/{runtime_mode}/stop"
            )
        except Exception:
            pass


def summarize_inference_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """提取推理响应里的关键字段，避免结果摘要过大。"""

    nested_payload = payload.get("payload")
    if isinstance(nested_payload, dict):
        payload = nested_payload
    return {
        key: payload.get(key)
        for key in (
            "request_id",
            "deployment_instance_id",
            "item_count",
            "detection_count",
            "latency_ms",
            "preview_image_uri",
            "result_object_key",
        )
        if key in payload
    }


def summarize_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """提取任务响应里的关键字段。"""

    return {
        "task_id": payload.get("task_id"),
        "state": payload.get("state"),
        "result": payload.get("result"),
        "error_message": payload.get("error_message"),
    }


def summarize_workflow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """提取 workflow 响应里的关键字段。"""

    summary: dict[str, Any] = {}
    for key in (
        "workflow_runtime_id",
        "workflow_run_id",
        "state",
        "desired_state",
        "observed_state",
        "assigned_process_id",
        "worker_process_id",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
    ):
        if key in payload:
            summary[key] = payload[key]
    outputs = payload.get("outputs")
    if isinstance(outputs, dict):
        summary["output_keys"] = sorted(outputs)
    error = payload.get("error")
    if error:
        summary["error"] = error
    return summary


def summarize_evaluation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """提取 evaluation 响应里的关键字段。"""

    result = payload.get("result")
    summary: dict[str, Any] = {
        "task_id": payload.get("task_id"),
        "state": payload.get("state"),
        "sample_count": payload.get("sample_count"),
        "error_message": payload.get("error_message"),
    }
    for key in (
        "top1_accuracy",
        "top5_accuracy",
        "map50",
        "map50_95",
        "mask_map50",
        "mask_map50_95",
        "oks_ap50",
        "oks_ap50_95",
        "rotated_map50",
        "rotated_map50_95",
    ):
        if key in payload:
            summary[key] = payload.get(key)
    if isinstance(result, dict):
        summary["result_keys"] = sorted(result)
    return summary


def build_dataset_id(*, model_type: str, task_type: str, run_id: str) -> str:
    """构造本次验收使用的数据集 id。"""

    safe_run_id = "".join(
        ch if ch.isalnum() or ch == "-" else "-" for ch in run_id.lower()
    )
    return f"smoke-{model_type}-{task_type}-{safe_run_id}"


def build_output_model_name(
    *, model_type: str, task_type: str, model_scale: str
) -> str:
    """构造可追溯的训练输出模型名。"""

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{model_type}-{task_type}-{model_scale}-{timestamp}"


def read_required_string(payload: dict[str, Any], key: str) -> str:
    """从字典读取必填字符串。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise RuntimeError(f"缺少必填字段 {key}: {payload}")


def find_required_string(payload: Any, key_names: tuple[str, ...]) -> str:
    """递归查找第一个指定名称的字符串字段。"""

    found = find_string(payload, key_names)
    if found is None:
        raise RuntimeError(f"找不到字段 {key_names}: {payload}")
    return found


def find_string(payload: Any, key_names: tuple[str, ...]) -> str | None:
    """递归查找字符串字段。"""

    if isinstance(payload, dict):
        for key in key_names:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = find_string(value, key_names)
            if found is not None:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = find_string(item, key_names)
            if found is not None:
                return found
    return None


def find_free_port(start: int, end: int) -> int:
    """在指定范围中找一个可监听端口。"""

    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"找不到可用端口：{start}-{end}")


def collect_process_snapshots(processes: Iterable[ManagedProcess]) -> dict[str, Any]:
    """收集脚本启动进程的资源快照。"""

    snapshots: dict[str, Any] = {}
    try:
        import psutil  # type: ignore[import-not-found]
    except Exception:
        return {
            item.name: {
                "pid": item.process.pid,
                "resource_status": "psutil-unavailable",
            }
            for item in processes
        }

    for item in processes:
        try:
            proc = psutil.Process(item.process.pid)
            memory = proc.memory_info()
            snapshots[item.name] = {
                "pid": item.process.pid,
                "running": proc.is_running(),
                "rss_bytes": memory.rss,
                "vms_bytes": memory.vms,
                "cpu_percent": proc.cpu_percent(interval=0.0),
                "log_path": str(item.log_path),
            }
        except Exception as error:
            snapshots[item.name] = {
                "pid": item.process.pid,
                "resource_status": f"unavailable: {error}",
                "log_path": str(item.log_path),
            }
    return snapshots


def write_result(*, run_dir: Path, result: dict[str, Any]) -> None:
    """写入本次验收结果 JSON。"""

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
