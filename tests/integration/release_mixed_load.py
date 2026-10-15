"""隔离发行包的顺序混合负载，覆盖四条真实协议调用并保留请求守恒。"""
from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4
from tests.integration.acceptance_contract import AcceptancePhases, positive_seconds
from tests.integration.acceptance_evidence import write_evidence
from tests.integration.deployment_workflow_trigger_soak import LaneMetrics, ZeroMqSoakClient, _reject_failed_payload
from tests.integration.yolo_model_full_chain_smoke import (
    build_default_task_cases, build_inference_form_payload,
)


def run_mixed_load(*, client, config: dict, runtime: str, deployment: str, source: str,
                   metadata: dict, phases: AcceptancePhases, duration: float, warmup: float) -> dict:
    """同一 Runtime 顺序调用以遵守 single-instance 容量；各通道独立统计。"""
    image = Path(config["image"])
    image_bytes = image.read_bytes()
    case = build_default_task_cases()[config["task"]]
    route = f"{case.deployment_route}/{deployment}"
    client.post(route + "/async/start")
    limit = positive_seconds(config.get("maximum_p99_latency_ms", 2000), "maximum_p99_latency_ms")
    lanes = {name: LaneMetrics(name, latency_limit_ms=limit) for name in
             ("deployment-sync", "deployment-async", "workflow-http", "trigger-zeromq")}
    trigger = ZeroMqSoakClient(endpoint=f"tcp://127.0.0.1:{config['trigger_port']}", timeout_seconds=120)
    started = None
    warmup_started = time.monotonic()
    last_progress_at = warmup_started
    phases.enter("warmup")
    try:
        while started is None or time.monotonic() - started < duration:
            if started is None and time.monotonic() - warmup_started >= warmup:
                phases.enter("measure")
                started = phases.events[-1]["monotonic"]
            for name, metrics in lanes.items():
                if started is not None and time.monotonic() - started >= duration:
                    break
                measured = started is not None
                if measured:
                    metrics.begin()
                before = time.perf_counter()
                error = None
                try:
                    files = {"input_image": (image.name, image_bytes, "image/png")}
                    if name.startswith("deployment"):
                        form = build_inference_form_payload(case=case, model_type=config["model"], async_request=name.endswith("async"))
                        form["save_result_image"] = "false"
                        if name.endswith("sync") and not name.endswith("async"):
                            _reject_failed_payload(client.post(route + "/infer", data=form, files=files), name)
                        else:
                            submission = client.post(f"{case.inference_route}/inference-tasks", data={
                                **form, "project_id": "project-1", "deployment_instance_id": deployment}, files=files)
                            deadline = time.monotonic() + 120
                            while True:
                                task = client.get(f"{case.inference_route}/inference-tasks/{submission['task_id']}")
                                if task["state"] == "succeeded":
                                    _reject_failed_payload(client.get(f"{case.inference_route}/inference-tasks/{submission['task_id']}/result"), name)
                                    break
                                if task["state"] in {"failed", "cancelled", "timeout"}:
                                    raise RuntimeError(str(task))
                                if time.monotonic() >= deadline:
                                    raise TimeoutError(submission["task_id"])
                                time.sleep(.05)
                    elif name == "workflow-http":
                        response = client.post(f"/workflows/app-runtimes/{runtime}/invoke/upload", params={"response_mode": "run"},
                                               files={"request_image_ref": (image.name, image_bytes, "image/png")},
                                               data={"execution_metadata_json": json.dumps(metadata)})
                        if response["state"] != "succeeded":
                            raise RuntimeError(str(response))
                    else:
                        trigger.send([json.dumps({"trigger_source_id": source, "event_id": uuid4().hex,
                                                  "input_binding": "request_image_ref", "media_type": "image/png"}).encode(), image_bytes])
                except Exception as caught:
                    error = caught
                if measured:
                    metrics.finish(latency_ms=(time.perf_counter() - before) * 1000, error=error)
                elif error is not None:
                    raise error
            if started is not None and time.monotonic() - last_progress_at >= 10:
                write_evidence(Path(config["output"]) / "progress.json", {
                    "elapsed_seconds": time.monotonic() - started,
                    "lanes": {name: metrics.snapshot() for name, metrics in lanes.items()},
                })
                last_progress_at = time.monotonic()
            time.sleep(.05)
        phases.enter("drain")
    finally:
        trigger.close()
    summaries = {name: metrics.snapshot() for name, metrics in lanes.items()}
    failures = mixed_load_failures(summaries, limit=limit)
    return {"duration_seconds": time.monotonic() - started, "lanes": summaries,
            "success_count": sum(v["success_count"] for v in summaries.values()),
            "error_count": sum(v["error_count"] for v in summaries.values()),
            "maximum_p99_latency_ms": limit, "failures": failures}


def mixed_load_failures(summaries: dict, *, limit: float) -> list[str]:
    """同时检查完整计数和有界延迟窗口，窗口滚动不能抹掉早期的超限。"""
    failures = []
    for name, value in summaries.items():
        if value["success_count"] < 10 or value["error_count"] or value["started_count"] != value["success_count"] or value["inflight_count"]:
            failures.append(f"{name}: 请求失败、数量不足或请求不守恒")
        if value["latency_ms"]["p99"] is None or value["latency_ms"]["p99"] > limit:
            failures.append(f"{name}: P99 超过 {limit}ms")
        if value["over_latency_limit_count"] * 100 > value["success_count"] + value["error_count"]:
            failures.append(f"{name}: 全程超过 {limit}ms 的请求多于 1%")
    return failures
