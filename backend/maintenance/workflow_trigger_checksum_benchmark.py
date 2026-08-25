"""对真实图片 BGR24 数据执行 Workflow Trigger checksum 跨语言基准。"""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import statistics
import subprocess
import time
import zlib
from pathlib import Path
from typing import Callable

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / ".tmp" / "workflow-trigger-stage0" / "checksum-benchmark.json"
DOTNET_PROBE = (
    ROOT
    / "sdks"
    / "dotnet"
    / "tests"
    / "Amvar.Vision.ContractTests"
    / "bin"
    / "Release"
    / "net472"
    / "Amvar.Vision.ContractTests.exe"
)
DOTNET_PROJECT = (
    ROOT
    / "sdks"
    / "dotnet"
    / "tests"
    / "Amvar.Vision.ContractTests"
    / "Amvar.Vision.ContractTests.vs2019.net472.csproj"
)


def _read_image(path: Path) -> np.ndarray:
    """使用 bytes 解码真实图片，避免 Windows 非 ASCII 路径限制。"""

    encoded = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法解码基准图片：{path}")
    return np.ascontiguousarray(image)


def _find_image(pattern: str) -> Path:
    """在开发数据中选择第一个匹配且可解码的真实图片。"""

    candidates = sorted((ROOT / "data" / "files").rglob(pattern))
    if not candidates:
        raise FileNotFoundError(f"没有找到基准图片：{pattern}")
    return candidates[0]


def _prepare_inputs(work_dir: Path) -> list[dict[str, object]]:
    """建立真实 1080p、4K 和 20MP 的连续 BGR24 基准输入。"""

    source_1080p = _find_image("*1080p*.jpg")
    source_20mp = _find_image("*20mp*.jpg")
    source_image_1080p = _read_image(source_1080p)
    image_20mp = _read_image(source_20mp)
    image_1080p = cv2.resize(
        source_image_1080p,
        (1920, 1080),
        interpolation=cv2.INTER_AREA,
    )
    image_4k = cv2.resize(image_20mp, (3840, 2160), interpolation=cv2.INTER_AREA)
    cases = (
        ("1080p", source_1080p, image_1080p),
        ("4k", source_20mp, np.ascontiguousarray(image_4k)),
        ("20mp", source_20mp, image_20mp),
    )
    results: list[dict[str, object]] = []
    for name, source, image in cases:
        raw_path = work_dir / f"{name}.bgr24"
        raw_path.write_bytes(image.tobytes(order="C"))
        results.append(
            {
                "name": name,
                "source_path": source.relative_to(ROOT).as_posix(),
                "shape": list(image.shape),
                "raw_path": raw_path,
                "size_bytes": raw_path.stat().st_size,
            }
        )
    return results


def _measure(operation: Callable[[], str], iterations: int) -> tuple[float, str]:
    """预热后返回中位耗时和最后一次校验值。"""

    operation()
    durations: list[float] = []
    value = ""
    for _ in range(iterations):
        started = time.perf_counter_ns()
        value = operation()
        durations.append((time.perf_counter_ns() - started) / 1_000_000)
    return statistics.median(durations), value


def _python_checksum(
    *, algorithm: str, path: Path, chunk_size: int, use_mmap: bool
) -> str:
    """按完整 bytes 或只读 mmap view 增量计算候选 checksum。"""

    with path.open("rb") as file:
        view: bytes | mmap.mmap
        view = mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) if use_mmap else file.read()
        try:
            if algorithm == "crc32-ieee":
                value = 0
                for offset in range(0, len(view), chunk_size):
                    value = zlib.crc32(view[offset : offset + chunk_size], value)
                return f"{value & 0xFFFFFFFF:08x}"
            if algorithm == "sha256":
                checksum = hashlib.sha256()
                for offset in range(0, len(view), chunk_size):
                    checksum.update(view[offset : offset + chunk_size])
                return checksum.hexdigest()
            raise ValueError(f"不支持的 checksum 算法：{algorithm}")
        finally:
            if isinstance(view, mmap.mmap):
                view.close()


def _ensure_dotnet_probe() -> None:
    """构建用于跨语言一致性和耗时测量的 net472 probe。"""

    build = subprocess.run(
        [
            "dotnet",
            "msbuild",
            str(DOTNET_PROJECT),
            "/t:Rebuild",
            "/p:Configuration=Release",
            "/p:TreatWarningsAsErrors=true",
            "/v:minimal",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=120,
    )
    if build.returncode != 0:
        raise RuntimeError(build.stdout + build.stderr)


def _dotnet_checksum(
    *, algorithm: str, path: Path, chunk_size: int, iterations: int
) -> dict[str, object]:
    """调用真实 net472 SDK 算法并读取结构化结果。"""

    run = subprocess.run(
        [
            str(DOTNET_PROBE),
            "--checksum-file",
            algorithm,
            str(path),
            str(chunk_size),
            str(iterations),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=120,
    )
    if run.returncode != 0:
        raise RuntimeError(run.stdout + run.stderr)
    payload = json.loads(run.stdout.strip())
    if not isinstance(payload, dict):
        raise RuntimeError(".NET checksum probe 未返回 JSON object")
    return payload


def run_benchmark(*, output_path: Path, iterations: int, chunk_size: int) -> dict[str, object]:
    """执行完整候选算法基准并写入阶段 0 报告。"""

    work_dir = output_path.parent / "inputs"
    work_dir.mkdir(parents=True, exist_ok=True)
    _ensure_dotnet_probe()
    cases = _prepare_inputs(work_dir)
    case_reports: list[dict[str, object]] = []
    for case in cases:
        raw_path = case["raw_path"]
        assert isinstance(raw_path, Path)
        algorithms: list[dict[str, object]] = []
        for algorithm in ("crc32-ieee", "sha256"):
            python_bytes_ms, python_value = _measure(
                lambda algorithm=algorithm, raw_path=raw_path: _python_checksum(
                    algorithm=algorithm,
                    path=raw_path,
                    chunk_size=chunk_size,
                    use_mmap=False,
                ),
                iterations,
            )
            python_mmap_ms, mmap_value = _measure(
                lambda algorithm=algorithm, raw_path=raw_path: _python_checksum(
                    algorithm=algorithm,
                    path=raw_path,
                    chunk_size=chunk_size,
                    use_mmap=True,
                ),
                iterations,
            )
            dotnet = _dotnet_checksum(
                algorithm=algorithm,
                path=raw_path,
                chunk_size=chunk_size,
                iterations=iterations,
            )
            dotnet_value = str(dotnet["value"])
            if len(python_value) == 8:
                dotnet_value = dotnet_value[-8:]
            if python_value != mmap_value or python_value != dotnet_value:
                raise RuntimeError(
                    f"{case['name']} {algorithm} Python/.NET checksum 不一致"
                )
            algorithms.append(
                {
                    "algorithm": algorithm,
                    "value": python_value,
                    "python_bytes_median_ms": round(python_bytes_ms, 6),
                    "python_mmap_median_ms": round(python_mmap_ms, 6),
                    "dotnet_incremental_mean_ms": float(dotnet["elapsed_ms"]),
                }
            )
        case_reports.append(
            {
                **{key: value for key, value in case.items() if key != "raw_path"},
                "algorithms": algorithms,
            }
        )
    report = {
        "format_id": "amvision.workflow-trigger-checksum-benchmark.v1",
        "iterations": iterations,
        "chunk_size": chunk_size,
        "selected_algorithm": "crc32-ieee",
        "selection_reason": (
            "Python zlib 与 .NET slicing-by-8 可增量计算且 fixture 完全一致；"
            "CRC32 IEEE 的完整性检测成本低于 SHA-256。"
        ),
        "cases": case_reports,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> int:
    """解析参数并执行阶段 0 checksum 基准。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--chunk-size", type=int, default=1024 * 1024)
    args = parser.parse_args()
    if args.iterations <= 0 or args.chunk_size <= 0:
        parser.error("iterations 和 chunk-size 必须大于 0")
    report = run_benchmark(
        output_path=args.output.resolve(),
        iterations=args.iterations,
        chunk_size=args.chunk_size,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
