"""手动运行真实数据短训练，验证结果落盘后的资源与 Windows 工作集裁剪对照。

仅用于验收：独立常驻进程、真实 core/AutoBatch/验证/测试/输出文件写入，不写生产数据库。
不注入现有 Worker；使用项目 GPU 独占租约；临时 checkpoint 每轮核对后删除。
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import gc
import json
import os
from pathlib import Path
import time
import weakref
from unittest.mock import patch

import psutil
import torch

from backend.service.application.models.training import training_engine
from backend.service.application.models.training.yolox_detection import (
    YoloXDetectionTrainingExecutionRequest,
    run_yolox_detection_training,
)
from backend.service.application.models.yolox_core.training import execution
from backend.service.application.runtime.device_leases import DeviceLeaseMode, DeviceLeaseProvider
from backend.service.application.support.resource_cleanup import release_model_task_resources
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings, LocalDatasetStorage,
)
from backend.workers.settings import get_backend_worker_settings


def trim_working_set() -> None:
    """仅在验收进程重现旧实现，不增加生产配置或私有 CUDA 调用。"""
    if os.name != "nt":
        raise RuntimeError("EmptyWorkingSet 对照需要 Windows")
    get_process = ctypes.windll.kernel32.GetCurrentProcess
    get_process.restype = ctypes.c_void_p
    trim = ctypes.windll.psapi.EmptyWorkingSet
    trim.argtypes = [ctypes.c_void_p]
    trim.restype = ctypes.c_bool
    if not trim(get_process()):
        raise ctypes.WinError()


def snapshot(process: psutil.Process) -> dict:
    """分别记录 Private 提交内存、RSS、原生句柄、线程与 CUDA 活跃/保留字节。"""
    memory = process.memory_info()
    return {
        "private_bytes": getattr(memory, "private", None),
        "rss_bytes": memory.rss,
        "page_faults": getattr(memory, "num_page_faults", None),
        "handles": process.num_handles() if os.name == "nt" else process.num_fds(),
        "threads": process.num_threads(),
        "children": [child.pid for child in process.children(recursive=True)],
        "cuda_allocated_bytes": torch.cuda.memory_allocated(),
        "cuda_reserved_bytes": torch.cuda.memory_reserved(),
    }


def main() -> int:
    """连续执行明确数量的真实短训练，完成资源检查后逐轮输出 JSONL。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-key", required=True)
    parser.add_argument("--checkpoint-key", required=True)
    parser.add_argument("--data-root", default="data/files")
    parser.add_argument("--model-scale", default="m")
    parser.add_argument("--input-size", type=int, default=640)
    parser.add_argument("--runs", type=int, default=12)
    parser.add_argument("--compare-working-set", action="store_true")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if not 1 <= args.runs <= 100:
        parser.error("runs 必须为 1–100")
    root = Path(__file__).resolve().parents[2]
    destination = Path(args.output_dir).resolve()
    if not destination.is_relative_to(root / ".tmp") or destination == root / ".tmp":
        parser.error("output-dir 必须为仓库 .tmp 的独立子目录")
    destination.mkdir(parents=True, exist_ok=False)
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=args.data_root))
    output = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(destination)))
    manifest = storage.read_json(args.manifest_key)
    checkpoint = storage.resolve(args.checkpoint_key)
    process = psutil.Process()
    references = []

    def track(factory, kind):
        """仅保存弱引用，检测模型、EMA、optimizer、dataset、loader 是否存活。"""
        def create(*a, **kw):
            result = factory(*a, **kw)
            if result is not None:
                references.append((kind, weakref.ref(result)))
            return result
        return create

    original_cleanup = training_engine.release_training_runtime_resources
    use_trim = False

    def cleanup():
        """在同一调用位置切换旧裁剪策略，其他清理步骤完全一致。"""
        original_cleanup()
        if use_trim:
            trim_working_set()

    def write(record):
        """立即写入小型验收记录，不保留 checkpoint 或 tensor。"""
        record["observed_at"] = datetime.now(timezone.utc).isoformat()
        line = json.dumps(record, ensure_ascii=False)
        with (destination / "report.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)

    settings = get_backend_worker_settings()
    provider = DeviceLeaseProvider.from_config(settings.device_leases)
    with provider.acquire_cuda(
        "cuda:0", mode=DeviceLeaseMode.EXCLUSIVE, purpose="training-resource-audit",
        owner_id=f"audit-{process.pid}", timeout_seconds=0,
    ), patch.object(training_engine, "release_training_runtime_resources", cleanup), patch.object(
        execution, "build_yolox_detection_model", track(execution.build_yolox_detection_model, "model")
    ), patch.object(execution, "_build_optimizer", track(execution._build_optimizer, "optimizer")), patch.object(
        execution, "build_yolox_model_ema", track(execution.build_yolox_model_ema, "ema")
    ), patch.object(
        execution, "_build_yolox_detection_dataset", track(execution._build_yolox_detection_dataset, "dataset")
    ), patch.object(torch.utils.data, "DataLoader", track(torch.utils.data.DataLoader, "loader")):
        write({"event": "start", "pid": process.pid, "torch": torch.__version__,
               "cuda": torch.version.cuda, "device": torch.cuda.get_device_name(),
               "model_scale": args.model_scale, "input_size": args.input_size,
               "runs": args.runs, "compare_working_set": args.compare_working_set,
               "manifest": args.manifest_key, "baseline": snapshot(process)})
        previous_trim = False
        # 先做两次热身；正式对照按四次一组切换裁剪，组内增强开关交替。
        for index in range(args.runs + 2):
            augmented = bool(index % 2)
            use_trim = bool(args.compare_working_set and index >= 2 and ((index - 2) // 4) % 2 == 0)
            options = {
                "device": "cuda:0", "seed": 0, "num_workers": 0,
                "warmup_epochs": 0, "no_aug_epochs": 0, "batch_mode": "auto",
                "batch_target_memory_fraction": 0.6, "amp_mode": "auto",
            }
            if not augmented:
                options.update({"flip_prob": 0.0, "hsv_prob": 0.0, "mosaic_prob": 0.0,
                                "mixup_prob": 0.0, "enable_mixup": False, "multiscale_range": 0})
            references.clear()
            before = snapshot(process)
            started = time.perf_counter()
            first_batch = None
            peak_private = before["private_bytes"] or 0
            last_sample = started

            def batch_progress(_progress):
                """低频观察每轮峰值；不在生产训练循环添加监视逻辑。"""
                nonlocal first_batch, peak_private, last_sample
                now = time.perf_counter()
                if first_batch is None:
                    first_batch = now - started
                if now - last_sample >= 2:
                    peak_private = max(peak_private, getattr(process.memory_info(), "private", 0))
                    last_sample = now

            result = run_yolox_detection_training(YoloXDetectionTrainingExecutionRequest(
                dataset_storage=storage, manifest_payload=manifest, model_scale=args.model_scale,
                max_epochs=1, input_size=(args.input_size, args.input_size), precision="fp16",
                evaluation_interval=1, warm_start_checkpoint_path=checkpoint,
                extra_options=options, batch_callback=batch_progress,
            ))
            returned = snapshot(process)
            record = {
                "event": "completed", "index": index, "warmup": index < 2,
                "augmentation": augmented, "trim": use_trim, "previous_trim": previous_trim,
                "pid": process.pid, "batch_size": result.batch_size,
                "train_count": result.train_sample_count, "val_count": result.validation_sample_count,
                "test_count": result.test_sample_count, "first_batch_seconds": first_batch,
                "val_metric": result.best_metric_value, "test_metrics": result.test_metrics_payload,
                "before": before, "returned": returned, "peak_private_bytes": peak_private,
                "checkpoint_bytes": len(result.checkpoint_bytes) + len(result.latest_checkpoint_bytes),
            }
            # 使用与 service 相同的存储写入接口消费结果，采样时不再持有这些大 bytes。
            for key, content in (("best.pth", result.checkpoint_bytes), ("latest.pth", result.latest_checkpoint_bytes)):
                output.write_bytes(key, content)
                assert output.resolve(key).stat().st_size == len(content)
            del content, result
            release_model_task_resources()
            gc.collect()
            record["seconds"] = time.perf_counter() - started
            record["after"] = snapshot(process)
            record["live_objects"] = [kind for kind, ref in references if ref() is not None]
            record["engine_context"] = training_engine.read_active_training_runtime()
            write(record)
            # 只删除本工具在独占目录生成的两份 checkpoint，真实训练资产保持不变。
            output.resolve("best.pth").unlink()
            output.resolve("latest.pth").unlink()
            assert not record["live_objects"], record["live_objects"]
            assert not record["engine_context"]
            assert record["after"]["cuda_allocated_bytes"] == 0
            assert record["after"]["cuda_reserved_bytes"] == 0
            assert not record["after"]["children"]
            previous_trim = use_trim
        write({"event": "finished", "pid": process.pid, "after": snapshot(process)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
