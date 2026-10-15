"""固定 ONNX 的串行重建与同一 engine 重复执行；保留每轮结果，不用成功重试覆盖失败。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.integration.acceptance_evidence import write_evidence


def replay(source: Path, engine_path: Path, count: int, precision: str) -> dict:
    """固定多组输入与 ONNX 对照，并重复执行同一 engine；沿用正式数值容差。"""
    from backend.service.application.runtime.support.tensorrt_runtime import prepare_tensorrt_python_runtime
    prepare_tensorrt_python_runtime()
    import numpy as np
    import onnxruntime as ort
    import tensorrt as trt
    from backend.service.application.models.model_artifact_runtime_smoke import (
        _resolve_numpy_input_dtype, _resolve_runtime_input_shape, summarize_runtime_output_consistency,
    )
    from backend.service.application.models.tensorrt_artifact_validation import execute_validation_engine
    session = ort.InferenceSession(str(source), providers=["CPUExecutionProvider"])
    info = session.get_inputs()[0]
    shape = _resolve_runtime_input_shape(info.shape)
    dtype = _resolve_numpy_input_dtype(info.type, np_module=np)
    images = {f"normal-seed-{seed}": np.random.default_rng(seed).standard_normal(shape).astype(dtype)
              for seed in (0, 1, 7)}
    images.update(zeros=np.zeros(shape, dtype=dtype), ones=np.ones(shape, dtype=dtype),
                  gradient=np.linspace(0, 1, int(np.prod(shape)), dtype=dtype).reshape(shape))
    logger = trt.Logger(trt.Logger.WARNING)
    runtime = trt.Runtime(logger)
    engine = runtime.deserialize_cuda_engine(engine_path.read_bytes())
    if engine is None:
        raise RuntimeError("固定 engine 反序列化失败")
    # YOLO26 的并列分数允许 TopK 行顺序变化；必须复用正式候选选择校验，
    # 不能把通用逐行 allclose 当作这类模型的数值门禁。
    import onnx
    from backend.service.application.models.yolo26_core.export.validation_graph import read_topk_contract, instrument_topk_graph
    from backend.service.application.models.yolo26_core.export.topk_validation import validate_topk_outputs
    graph = onnx.load(str(source))
    contract = read_topk_contract(graph)
    observed_engine = None
    observed_source = None
    if contract is not None:
        instrumented = instrument_topk_graph(graph, contract).SerializeToString()
        observed_source = ort.InferenceSession(instrumented, providers=["CPUExecutionProvider"])
        builder = trt.Builder(logger)
        network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
        parser = trt.OnnxParser(network, logger)
        if not parser.parse(instrumented):
            raise RuntimeError("候选观测图解析失败")
        config = builder.create_builder_config()
        config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 1 << 30)
        if precision == "fp16":
            config.set_flag(trt.BuilderFlag.FP16)
        else:
            config.clear_flag(trt.BuilderFlag.TF32)
        if any(int(dimension) < 0 for dimension in network.get_input(0).shape):
            profile = builder.create_optimization_profile()
            profile.set_shape(info.name, shape, shape, shape)
            config.add_optimization_profile(profile)
        observed_bytes = builder.build_serialized_network(network, config)
        if observed_bytes is None:
            raise RuntimeError("候选观测 engine 构建失败")
        observed_engine = runtime.deserialize_cuda_engine(observed_bytes)
        engine_path.with_suffix(".observation.bin").write_bytes(bytes(observed_bytes))
    checks = []
    for input_name, image in images.items():
        source_outputs = session.run(None, {info.name: image})
        output_names = [item.name for item in session.get_outputs()]
        baseline = execute_validation_engine(engine=engine, trt=trt, image=image)
        if contract is None:
            reference_check = summarize_runtime_output_consistency(
                source_outputs=source_outputs, target_outputs=[baseline[name] for name in output_names],
                build_precision=precision, np_module=np,
            )
        else:
            observed = execute_validation_engine(engine=observed_engine, trt=trt, image=image)
            source_observed = observed_source.run([*output_names, contract.candidates_name], {info.name: image})
            reference_check = validate_topk_outputs(
                source_candidates=source_observed[-1], target_candidates=observed[contract.candidates_name],
                source_outputs=source_outputs, target_outputs=[baseline[name] for name in output_names],
                source_observed_outputs=source_observed[:-1], target_observed_outputs=[observed[name] for name in output_names],
                class_count=contract.class_count, build_precision=precision, np_module=np,
            )
        repeated = []
        for _ in range(count):
            current = execute_validation_engine(engine=engine, trt=trt, image=image)
            repeated.append(summarize_runtime_output_consistency(
                source_outputs=list(baseline.values()), target_outputs=[current[name] for name in baseline],
                build_precision=precision, np_module=np,
            ))
        checks.append({"input": input_name, "input_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                       "onnx_comparison": reference_check, "repeat_checks": repeated,
                       "passed": reference_check["passed"] and all(item["passed"] for item in repeated)})
        if not checks[-1]["passed"]:
            # 固定失败输入与输出，后续成功不能覆盖该证据。
            np.savez_compressed(engine_path.with_name(engine_path.stem + f"-{input_name}-failure.npz"),
                                input=image, **{f"onnx_{i}": v for i, v in enumerate(source_outputs)},
                                **{f"trt_{i}": v for i, v in enumerate(baseline.values())})
    result = {"replay_count_per_input": count, "input_count": len(images), "input_shape": list(shape),
              "input_dtype": str(dtype), "precision": precision,
              "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "engine_sha256": hashlib.sha256(engine_path.read_bytes()).hexdigest(), "checks": checks,
              "passed": all(item["passed"] for item in checks)}
    write_evidence(engine_path.with_suffix(".replay.json"), result)
    return result


def run(*, source: Path, output: Path, expected_sha256: str, precision: str, builds: int, replays: int) -> dict:
    """持有主机级独占 GPU 租约，再逐轮调用正式 builder 和重复执行子进程。"""
    from backend.workers.settings import BackendWorkerSettings
    from backend.service.application.runtime.device_leases import DeviceLeaseMode, DeviceLeaseProvider
    from backend.service.application.runtime.support.tensorrt_runtime import build_tensorrt_process_environment
    with source.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != expected_sha256.lower():
        raise ValueError("ONNX sha256 与固定基线不一致")
    output.mkdir(parents=True, exist_ok=False)
    fixed = output / "source.onnx"
    shutil.copyfile(source, fixed)
    with fixed.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
            raise ValueError("ONNX 在复制期间发生变更")
    result = {"source_sha256": digest, "precision": precision, "status": "running", "builds": []}
    write_evidence(output / "result.json", result)
    config = BackendWorkerSettings().device_leases
    provider = DeviceLeaseProvider.from_config(config)
    try:
        with provider.acquire_cuda(config.conversion_cuda_device, mode=DeviceLeaseMode.EXCLUSIVE,
                                   purpose="tensorrt-repeatability", owner_id=output.name, timeout_seconds=0) as lease:
            environment = build_tensorrt_process_environment()
            environment["CUDA_VISIBLE_DEVICES"] = lease.info.resource_key
            result["device_lease"] = lease.info.to_dict()
            for index in range(builds):
                engine = output / f"build-{index:02d}.engine"
                entry: dict = {"index": index, "stages": []}
                result["builds"].append(entry)
                write_evidence(output / "result.json", result)
                commands = [
                    [sys.executable, "-m", "backend.service.application.conversions.runtime.scripts.build_tensorrt_engine",
                     str(fixed.resolve()), str(engine.resolve()), precision],
                    [sys.executable, "-m", __spec__.name, "--replay", str(engine.resolve()),
                     "--source", str(fixed.resolve()), "--replays", str(replays), "--precision", precision],
                ]
                for stage, command in zip(("build", "replay"), commands, strict=True):
                    entry["current_stage"] = stage
                    write_evidence(output / "result.json", result)
                    log = output / f"build-{index:02d}-{stage}.log"
                    try:
                        with log.open("w", encoding="utf-8") as stream:
                            completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                                       env=environment, timeout=1800, check=False)
                        entry["stages"].append({"stage": stage, "exit_code": completed.returncode, "log": log.name})
                    except subprocess.TimeoutExpired:
                        entry["stages"].append({"stage": stage, "exit_code": None, "error": "timeout", "log": log.name})
                    if entry["stages"][-1]["exit_code"] != 0:
                        break
                entry["passed"] = len(entry["stages"]) == 2 and all(item["exit_code"] == 0 for item in entry["stages"])
                write_evidence(output / "result.json", result)
        result["status"] = "succeeded" if all(item["passed"] for item in result["builds"]) else "failed"
    except Exception as error:
        result.update(status="failed", error=str(error))
    write_evidence(output / "result.json", result)
    return result


def main() -> int:
    """解析固定资产、重复次数和子进程模式。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--precision", choices=("fp32", "fp16"), default="fp32")
    parser.add_argument("--builds", type=int, default=3)
    parser.add_argument("--replays", type=int, default=10)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    if not 1 <= args.builds <= 20 or not 1 <= args.replays <= 1000:
        parser.error("builds 必须在 1..20，replays 必须在 1..1000")
    if args.replay:
        result = replay(args.source, args.replay, args.replays, args.precision)
        print(json.dumps(result, ensure_ascii=True), flush=True)
        return 0 if result["passed"] else 1
    if args.output is None or args.expected_sha256 is None:
        parser.error("必须指定 --output 和 --expected-sha256")
    result = run(source=args.source, output=args.output, expected_sha256=args.expected_sha256,
                 precision=args.precision, builds=args.builds, replays=args.replays)
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
