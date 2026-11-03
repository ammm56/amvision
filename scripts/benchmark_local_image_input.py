"""对照本地图片读取、OpenCV 解码和执行期注册；只读输入，不改工作流。"""

import argparse
import gc
import json
import mmap
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
import psutil

from backend.nodes import ExecutionImageRegistry
from custom_nodes.opencv_nodes.shared.backend.runtime.bmp import read_bgr24_bmp


def measure(path: Path, mode: str):
    """分开记录读取、解码、注册；通过注册内容摘要核对全部像素。"""
    registry = ExecutionImageRegistry(decoded_cache_max_bytes=1)
    started = perf_counter()
    read_ms = None
    encoded = None
    if mode == "read_bytes":
        encoded = path.read_bytes()
        read_ms = (perf_counter() - started) * 1000
        matrix = cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_UNCHANGED)
    elif mode == "mmap_imdecode":
        with (
            path.open("rb") as stream,
            mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapping,
        ):
            encoded_view = np.frombuffer(mapping, np.uint8)
            try:
                matrix = cv2.imdecode(encoded_view, cv2.IMREAD_UNCHANGED)
            finally:
                del encoded_view
    elif mode == "bmp_mmap":
        matrix = read_bgr24_bmp(path)
    else:
        raise ValueError("未知的测量方式")
    loaded = perf_counter()
    if matrix is None:
        raise RuntimeError("测试图片无法解码")
    del encoded
    entry = registry.register_typed_image_matrix(
        matrix=matrix, width=matrix.shape[1], height=matrix.shape[0]
    )
    finished = perf_counter()
    result = {
        "mode": mode,
        "read_ms": read_ms,
        "read_decode_ms": (loaded - started) * 1000,
        "register_ms": (finished - loaded) * 1000,
        "total_ms": (finished - started) * 1000,
        "shape": list(matrix.shape),
        "dtype": str(matrix.dtype),
        "content_sha256": entry.content_sha256,
    }
    registry.clear()
    del matrix, entry
    gc.collect()
    process = psutil.Process()
    result["private_after_bytes"] = process.memory_info().private
    result["handles_after"] = process.num_handles()
    return result


def main():
    """交替执行候选方式，避免把顺序预热差异直接当作优化收益。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["read_bytes", "mmap_imdecode", "bmp_mmap"],
        default=["read_bytes", "mmap_imdecode", "bmp_mmap"],
    )
    args = parser.parse_args()
    rows = []
    for iteration in range(args.runs):
        modes = args.modes
        modes = modes[iteration % len(modes) :] + modes[: iteration % len(modes)]
        for mode in modes:
            result = measure(args.image, mode)
            result["iteration"] = iteration + 1
            rows.append(result)
            assert result["content_sha256"] == rows[0]["content_sha256"]
            print(json.dumps(result, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"image": str(args.image), "runs": rows}, ensure_ascii=False, indent=2
        ),
        "utf-8",
    )


if __name__ == "__main__":
    main()
