"""同一 ONNX 的 TensorRT 默认 TF32 与严格 fp32 构建及执行成本对比。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import psutil

from backend.service.application.models.rfdetr_core.export._tensorrt import (
    parse_trtexec_output,
)
from backend.service.application.runtime.support.tensorrt_runtime import (
    build_tensorrt_process_environment,
    resolve_trtexec_path,
)


def run(source: Path, output: Path) -> dict:
    """串行构建并测试相同静态模型，不改写来源或登记发布产物。"""
    output.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "source": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "note": "trtexec 相同默认输入、固定 workspace；单进程资源峰值包含构建阶段。",
        "variants": {},
    }
    for name, precision_flags in (
        ("previous-default-tf32", []),
        ("strict-fp32", ["--noTF32"]),
    ):
        command = [
            str(resolve_trtexec_path()),
            f"--onnx={source.resolve()}",
            f"--saveEngine={output.resolve() / (name + '.engine')}",
            "--memPoolSize=workspace:1024",
            "--warmUp=1000",
            "--duration=15",
            "--iterations=200",
            "--percentile=50,95,99",
            f"--exportTimes={output.resolve() / (name + '-times.json')}",
            *precision_flags,
        ]
        log_path = output / (name + ".log")
        samples = []
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as handle:
            process = subprocess.Popen(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                env=build_tensorrt_process_environment(),
            )
            observer = psutil.Process(process.pid)
            while process.poll() is None:
                try:
                    memory = observer.memory_info()
                    samples.append(
                        {
                            "elapsed_seconds": time.monotonic() - started,
                            "rss_bytes": memory.rss,
                            "private_bytes": getattr(memory, "private", None),
                            "threads": observer.num_threads(),
                            "handles": observer.num_handles()
                            if hasattr(observer, "num_handles")
                            else None,
                            "cpu_percent": observer.cpu_percent(),
                        }
                    )
                except psutil.NoSuchProcess:
                    break
                time.sleep(0.5)
            code = process.wait()
        entry = {
            "command": command,
            "exit_code": code,
            "total_seconds": time.monotonic() - started,
            "resources": samples,
        }
        result["variants"][name] = entry
        if code == 0:
            entry["statistics"] = parse_trtexec_output(
                log_path.read_text(encoding="utf-8")
            )
        (output / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if code:
            raise RuntimeError(f"{name} 退出码 {code}，见 {log_path}")
    return result


def main() -> None:
    """要求显式来源及输出目录，不能隐式覆盖已发布模型。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.output)


if __name__ == "__main__":
    main()
