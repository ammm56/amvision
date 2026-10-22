"""完整样本读写验收；所有容量和路径显式输入，不作为生产默认。"""

from __future__ import annotations

import argparse
import gc
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import threading
import time

import numpy as np
import psutil
from pypcd4 import Encoding, MetaData, PointCloud
from trimesh.exchange import ply


def digest(path: Path) -> str:
    """流式核对原始文件，不加载整份文件字节。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    """验证全量源数组和各编码写后读取，最后记录实际资源观测。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-points", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-header-bytes", type=int, required=True)
    parser.add_argument("--max-decoded-bytes", type=int, required=True)
    parser.add_argument("--max-working-bytes", type=int, required=True)
    parser.add_argument("--chunk-rows", type=int, required=True)
    parser.add_argument("--chunk-bytes", type=int, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    process = psutil.Process()
    before = process.memory_info().rss
    peaks = [before]
    stopped = threading.Event()

    def monitor():
        """固定短采样只作观测，不宣称覆盖每次分配峰值。"""
        while not stopped.wait(0.02):
            peaks[0] = max(peaks[0], process.memory_info().rss)

    sampler = threading.Thread(target=monitor, name="sample-rss", daemon=False)
    sampler.start()
    records = []
    limits = dict(
        max_decoded_bytes=args.max_decoded_bytes,
        chunk_rows=args.chunk_rows,
        chunk_bytes=args.chunk_bytes,
    )
    try:
        actual_hash = digest(args.sample)
        if actual_hash != args.expected_sha256:
            raise ValueError("Sample SHA-256 mismatch")
        started = time.perf_counter()
        with args.sample.open("rb") as stream:
            header = ply.read_ply_header(stream, max_header_bytes=args.max_header_bytes)
            data = ply.read_ply_data(stream, header, **limits)
        assert len(data) == args.expected_points
        assert data.dtype == np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4")])
        array_hash = hashlib.sha256(memoryview(data)).hexdigest()
        records.append(
            {
                "operation": "read-original-ascii",
                "seconds": time.perf_counter() - started,
                "array_sha256": array_hash,
            }
        )
        for encoding in ("ascii", "binary_little_endian", "binary_big_endian"):
            path = args.output_dir / f"roundtrip-{encoding}.ply"
            started = time.perf_counter()
            with path.open("wb") as stream:
                ply.write_ply_points(
                    stream, data, encoding=encoding, chunk_rows=args.chunk_rows
                )
            with path.open("rb") as stream:
                other_header = ply.read_ply_header(
                    stream, max_header_bytes=args.max_header_bytes
                )
                other = ply.read_ply_data(stream, other_header, **limits)
            for start in range(0, len(data), args.chunk_rows):
                for name in data.dtype.names:
                    np.testing.assert_array_equal(
                        other[name][start : start + args.chunk_rows],
                        data[name][start : start + args.chunk_rows],
                    )
            records.append(
                {
                    "operation": f"PLY {encoding} write-read-compare",
                    "seconds": time.perf_counter() - started,
                    "bytes": path.stat().st_size,
                }
            )
            del other
            path.unlink()
        metadata = MetaData(
            fields=("x", "y", "z"),
            size=(4, 4, 4),
            type=("F", "F", "F"),
            count=(1, 1, 1),
            width=len(data),
            points=len(data),
        )
        cloud = PointCloud(metadata, data)
        for encoding in Encoding:
            path = args.output_dir / f"roundtrip-{encoding.value}.pcd"
            started = time.perf_counter()
            cloud.save(
                path,
                encoding,
                chunk_rows=args.chunk_rows,
                max_working_bytes=args.max_working_bytes,
            )
            other = PointCloud.from_path(
                path,
                max_header_bytes=args.max_header_bytes,
                max_working_bytes=args.max_working_bytes,
                **limits,
            )
            assert other.metadata == metadata.derive(data=encoding)
            for start in range(0, len(data), args.chunk_rows):
                np.testing.assert_array_equal(
                    other.pc_data[start : start + args.chunk_rows],
                    data[start : start + args.chunk_rows],
                )
            records.append(
                {
                    "operation": f"PCD {encoding.value} write-read-compare",
                    "seconds": time.perf_counter() - started,
                    "bytes": path.stat().st_size,
                }
            )
            del other
            path.unlink()
        del cloud, data
        gc.collect()
    finally:
        stopped.set()
        sampler.join()
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "versions": {
            name: version(name)
            for name in ("numpy", "trimesh", "pypcd4", "pydantic", "python-neo-lzf")
        },
        "sample_sha256": actual_hash,
        "sample_bytes": args.sample.stat().st_size,
        "points": args.expected_points,
        "records": records,
        "rss_before_bytes": before,
        "rss_sampled_peak_bytes": peaks[0],
        "rss_after_release_bytes": process.memory_info().rss,
        "threads_after_monitor_join": process.num_threads(),
        "result": "passed",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
