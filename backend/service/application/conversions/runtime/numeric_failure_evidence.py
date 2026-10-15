"""保存构建失败证据；只在转换失败路径执行，不参与推理热路径。"""

from __future__ import annotations

import hashlib
import io
import json
import platform
from pathlib import Path
from typing import Any
from uuid import uuid4


def preserve_conversion_failure(
    *, source_path: Path, output_path: Path, engine_bytes: Any,
    observations: dict[str, Any], error: Exception, precision: str,
    runtime_version: str, maximum_bytes: int = 512 * 1024 * 1024,
    stage: str = "validate-tensorrt",
) -> dict[str, Any]:
    """保存有界独立诊断目录；失败 engine 使用 .bin，不能登记为正常转换输出。

    source_path/output_path 标识本次构建；observations 是验证器实际执行的数组。
    maximum_bytes 限制单次二进制证据总量；超限资产只登记摘要，不删除其他证据。
    """
    import numpy as np

    # 正式转换在 attempt/staging/artifacts/builds 下执行；证据属于 attempt，
    # 必须位于 staging 外，才能在 aborted 清理后保留且不参与 builds 发布。
    parent = output_path.parent
    if (parent.name, parent.parent.name, parent.parent.parent.name) == ("builds", "artifacts", "staging"):
        parent = parent.parent.parent.parent
    directory = parent / "diagnostics" / f"rejected-{uuid4().hex}"
    result: dict[str, Any] = {
        "schema_version": 1, "published": False, "precision": precision,
        "runtime_version": runtime_version, "platform": platform.platform(), "stage": stage,
        "input_seed": 0, "maximum_bytes": maximum_bytes, "files": [],
        "error": {"type": type(error).__name__, "message": str(error),
                  "details": getattr(error, "details", None)},
    }
    used = 0
    try:
        directory.mkdir(parents=True, exist_ok=False)
        # 逐个写入，不在内存中再打包整个 ONNX、engine 和输出集合。
        def save(name: str, size: int, writer: Any) -> None:
            """在预算内写入资产并记录校验和，拒绝超预算资产。"""
            nonlocal used
            entry: dict[str, Any] = {"name": name, "bytes": size, "saved": False}
            result["files"].append(entry)
            if size > maximum_bytes - used:
                entry["reason"] = "binary_budget_exceeded"
                return
            path = directory / name
            writer(path)
            used += path.stat().st_size
            with path.open("rb") as handle:
                entry.update(saved=True, bytes=path.stat().st_size,
                             sha256=hashlib.file_digest(handle, "sha256").hexdigest())

        with source_path.open("rb") as handle:
            result["source_sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
        result["source_path"] = str(source_path)
        # 优先保留不可重建的失败 engine；ONNX 可由记录的来源和 sha256 追溯。
        if engine_bytes is not None:
            # TensorRT IHostMemory 只保证 buffer 协议，不保证支持 len()。
            # nbytes 是真实字节数；直接写 view，不复制完整 engine 才计算预算。
            with memoryview(engine_bytes) as engine_view:
                save("rejected-engine.bin", engine_view.nbytes, lambda path: path.write_bytes(engine_view))
        for index, (name, value) in enumerate(observations.items()):
            if isinstance(value, np.ndarray):
                filename = f"array-{index:03d}.npy"
                # npy 的实际 header 长度随 dtype/shape 变化，不能使用固定估算绕过预算。
                header = io.BytesIO()
                np.lib.format.write_array_header_2_0(header, np.lib.format.header_data_from_array_1_0(value))
                def write_array(path: Path, array: Any = value) -> None:
                    """固定使用 npy v2 header，令预算计算和实际写入严格一致。"""
                    with path.open("wb") as handle:
                        np.lib.format.write_array(handle, array, version=(2, 0), allow_pickle=False)
                save(filename, int(value.nbytes) + header.tell(),
                     write_array)
                result["files"][-1].update(tensor=name, dtype=str(value.dtype), shape=list(value.shape))
            elif isinstance(value, bytes) or name == "observed_engine":
                with memoryview(value) as observed_view:
                    save(f"observed-{index:03d}.bin", observed_view.nbytes,
                         lambda path, data=observed_view: path.write_bytes(data))
                result["files"][-1]["tensor"] = name
        import shutil
        save("source.onnx", source_path.stat().st_size, lambda path: shutil.copyfile(source_path, path))
        result["saved_bytes"] = used
        (directory / "manifest.json").write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
        return {"directory": str(directory), "manifest": str(directory / "manifest.json"),
                "saved_bytes": used, "source_sha256": result["source_sha256"]}
    except Exception as evidence_error:  # noqa: BLE001 - 保存失败不能替换原始数值错误。
        return {"directory": str(directory), "capture_error": str(evidence_error), "saved_bytes": used}
