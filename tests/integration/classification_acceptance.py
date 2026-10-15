"""使用标注 ZIP 和公开推理 API 验收分类部署，按类别名称计分并保存逐图片证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from tests.integration.acceptance_evidence import write_evidence
from tests.integration.yolo_model_full_chain_smoke import SmokeApiClient, summarize_inference_payload


def classification_metrics(records: list[dict[str, Any]], labels: list[str]) -> dict[str, Any]:
    """计算完整混淆矩阵、各类别召回及准确率，未知类别和空输入直接拒绝。"""
    if not records or not labels or len(set(labels)) != len(labels):
        raise ValueError("分类验收需要非空样本和不重复的类别")
    matrix = {label: {other: 0 for other in labels} for label in labels}
    for record in records:
        expected, predicted = record["expected"], record["predicted"]
        if expected not in matrix or predicted not in matrix:
            raise ValueError(f"未知类别：{expected} / {predicted}")
        matrix[expected][predicted] += 1
    count = len(records)
    correct = sum(matrix[label][label] for label in labels)
    accuracy = correct / count
    z = 1.959963984540054
    lower = (accuracy + z*z/(2*count) - z*math.sqrt(accuracy*(1-accuracy)/count + z*z/(4*count*count))) / (1+z*z/count)
    return {"sample_count": count, "correct_count": correct, "accuracy": accuracy,
            "accuracy_wilson_95_lower": lower, "confusion_matrix": matrix,
            "per_class": {label: {"count": sum(matrix[label].values()),
                                   "recall": matrix[label][label]/sum(matrix[label].values()) if sum(matrix[label].values()) else None}
                          for label in labels}}


def evaluate_archive(*, client: SmokeApiClient, deployment_id: str, archive_path: Path,
                     output_dir: Path, split: str, minimum_accuracy: float | None = None) -> dict[str, Any]:
    """以正式部署预处理和类别契约计分；不启动、停止或修改已有部署。"""
    output_dir.mkdir(parents=True, exist_ok=False)
    deployment = client.get(f"/models/classification/deployment-instances/{deployment_id}")
    labels = list(deployment["labels"])
    records: list[dict[str, Any]] = []
    fingerprints: dict[str, set[str]] = defaultdict(set)
    samples: list[tuple[str, str, str]] = []
    with archive_path.open("rb") as handle:
        archive_hash = hashlib.file_digest(handle, "sha256").hexdigest()
    result: dict[str, Any] = {"schema_version": 1, "status": "running", "deployment": deployment,
                            "archive_sha256": archive_hash, "split": split, "minimum_accuracy": minimum_accuracy}
    write_evidence(output_dir / "result.json", result)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                path = PurePosixPath(info.filename)
                if len(path.parts) < 3 or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
                    continue
                # 直接读取 ZIP 成员，不解压到来源路径，也不接受无限解压单图。
                if info.file_size > 64 * 1024 * 1024:
                    raise ValueError(f"图片超过验收单图上限：{info.filename}")
                digest = hashlib.sha256(archive.read(info)).hexdigest()
                sample_split, expected = path.parts[-3:-1]
                fingerprints[digest].add(sample_split)
                if sample_split == split:
                    if expected not in labels:
                        raise ValueError(f"数据类别未登记到部署：{expected}")
                    samples.append((info.filename, expected, digest))
            if not samples:
                raise ValueError(f"ZIP 中没有 {split} 分类样本")
            split_fingerprint = hashlib.sha256(json.dumps(sorted(samples), ensure_ascii=True).encode()).hexdigest()
            result["split_sha256"] = split_fingerprint
            result["overlapping_image_hashes"] = {digest: sorted(parts) for digest, parts in fingerprints.items()
                                                   if split in parts and len(parts) > 1}
            with (output_dir / "predictions.jsonl").open("x", encoding="utf-8") as stream:
                for name, expected, digest in sorted(samples):
                    started = time.perf_counter()
                    payload = client.post(
                        f"/models/classification/deployment-instances/{deployment_id}/infer",
                        data={"top_k": str(len(labels)),
                              "input_transport_mode": "storage", "save_result_image": "false",
                              "return_preview_image_base64": "false", "extra_options": "{}"},
                        files={"input_image": (PurePosixPath(name).name, archive.read(name), "application/octet-stream")},
                    )
                    prediction = summarize_inference_payload(payload)
                    top = prediction["top_category"]
                    if not math.isfinite(float(top["probability"])) or not 0 <= float(top["probability"]) <= 1:
                        raise ValueError("分类概率不是有限的 0..1 数值")
                    record = {"file": name, "sha256": digest, "expected": expected,
                              "predicted": top["class_name"], "probability": top["probability"],
                              "elapsed_ms": (time.perf_counter()-started)*1000,
                              "runtime_latency_ms": prediction.get("latency_ms")}
                    records.append(record)
                    stream.write(json.dumps(record, ensure_ascii=True) + "\n")
                    stream.flush()
            result.update(classification_metrics(records, labels), status="measured")
            result["prediction_counts"] = dict(Counter(record["predicted"] for record in records))
            result["accuracy_gate"] = ("not_configured" if minimum_accuracy is None else
                                       "passed" if result["accuracy"] >= minimum_accuracy else "failed")
            result["independent_split"] = not result["overlapping_image_hashes"]
            result["data_gate"] = "passed" if result["independent_split"] else "failed"
    except Exception as error:
        result.update(status="failed", error=str(error), completed_count=len(records))
    write_evidence(output_dir / "result.json", result)
    return result


def main() -> int:
    """要求显式服务、模型和数据，不能隐式连接现场部署。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("test", "valid", "val"), default="test")
    parser.add_argument("--minimum-accuracy", type=float)
    args = parser.parse_args()
    if args.minimum_accuracy is not None and not 0 <= args.minimum_accuracy <= 1:
        parser.error("minimum-accuracy 必须在 0 和 1 之间")
    client = SmokeApiClient(base_url=args.base_url, token="amvision-default-user-token", timeout_seconds=120)
    try:
        result = evaluate_archive(client=client, deployment_id=args.deployment_id, archive_path=args.archive,
                                  output_dir=args.output, split=args.split, minimum_accuracy=args.minimum_accuracy)
    finally:
        client.close()
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if result["status"] == "failed" or result.get("accuracy_gate") == "failed" or result.get("data_gate") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
