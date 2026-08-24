"""Conversion attempt 子进程入口。"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
import traceback

from backend.service.application.error_serialization import serialize_error
from backend.service.application.conversions.publication import (
    serialize_conversion_run_result,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def _build_runner(*, runner_kind: str, dataset_storage: LocalDatasetStorage) -> object:
    """按稳定类型名创建实际 conversion runner。"""

    if runner_kind == "yolox":
        from backend.service.application.conversions.runtime.yolox_conversion_runner import (
            LocalYoloXConversionRunner,
        )

        return LocalYoloXConversionRunner(dataset_storage=dataset_storage)
    if runner_kind == "yolov8":
        from backend.workers.conversion.yolov8_conversion_runner import (
            LocalYoloV8ConversionRunner,
        )

        return LocalYoloV8ConversionRunner(dataset_storage=dataset_storage)
    if runner_kind == "yolo11":
        from backend.workers.conversion.yolo11_conversion_runner import (
            LocalYolo11ConversionRunner,
        )

        return LocalYolo11ConversionRunner(dataset_storage=dataset_storage)
    if runner_kind == "yolo26":
        from backend.workers.conversion.yolo26_conversion_runner import (
            LocalYolo26ConversionRunner,
        )

        return LocalYolo26ConversionRunner(dataset_storage=dataset_storage)
    if runner_kind == "rfdetr":
        from backend.service.application.conversions.runtime.rfdetr_conversion_runner import (
            LocalRfdetrConversionRunner,
        )

        return LocalRfdetrConversionRunner(dataset_storage=dataset_storage)
    raise ValueError(f"不支持的 conversion runner_kind: {runner_kind}")


def run_attempt(
    *,
    runner_kind: str,
    dataset_root: Path,
    request_path: Path,
    result_path: Path,
) -> int:
    """执行一次 conversion attempt，并把结构化结果写入控制文件。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(dataset_root))
    )
    with request_path.open("rb") as stream:
        request = pickle.load(stream)  # noqa: S301 - 仅消费父进程创建的本地控制文件
    try:
        runner = _build_runner(
            runner_kind=runner_kind,
            dataset_storage=dataset_storage,
        )
        result = runner.run_conversion(request)
        payload = {"ok": True, "result": serialize_conversion_run_result(result)}
        exit_code = 0
    except BaseException as error:
        payload = {
            "ok": False,
            "error": serialize_error(error),
            "traceback": traceback.format_exc(),
        }
        exit_code = 1
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = result_path.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
    temporary_path.replace(result_path)
    return exit_code


def main() -> None:
    """解析命令行并执行 attempt。"""

    parser = argparse.ArgumentParser(description="运行受监督 conversion attempt")
    parser.add_argument("--runner-kind", required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--request-path", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(
        run_attempt(
            runner_kind=args.runner_kind,
            dataset_root=args.dataset_root,
            request_path=args.request_path,
            result_path=args.result_path,
        )
    )


if __name__ == "__main__":
    main()
