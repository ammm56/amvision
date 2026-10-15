"""真实发行包的模型导入、部署、Workflow、SDK 与持续调用验收。

仅连接显式指定的隔离验收服务；通过公开 API 创建本次资源，退出时停止本次会话。
配合 test_release_full_stack_acceptance 的进程资源监控和完整服务停止验证使用。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import time
import sys
from uuid import uuid4
from collections import deque

import httpx
import numpy as np

from tests.integration.acceptance_contract import AcceptancePhases, acceptance_result, cleanup_all, positive_seconds
from tests.integration.acceptance_evidence import write_evidence

from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
    deserialize_deployment_runtime_configuration,
    serialize_deployment_runtime_configuration,
)
from tests.integration.yolo_model_full_chain_smoke import (
    SmokeApiClient,
    build_default_task_cases,
    poll_inference_task,
    submit_async_inference,
    submit_direct_inference,
    summarize_inference_payload,
)
from tests.integration.workflow_trigger_transport_assets import (
    _source_common,
    _wait_ready,
)
from tests.integration.workflow_trigger_transport_benchmark import (
    DOTNET_PROBE,
    evaluate_health_recovery,
    load_settings,
    run_benchmark,
)


def wait_transfer(
    client: SmokeApiClient, prefix: str, operation: str, states: set[str]
) -> dict:
    """等待有界的上传分析或导入提交，拒绝失败终态。"""
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        value = client.get(f"{prefix}/{operation}")
        if value["state"] in states:
            return value
        if value["state"] in {"failed", "cancelled", "needs_attention"}:
            raise RuntimeError(json.dumps(value, ensure_ascii=False))
        time.sleep(0.3)
    raise TimeoutError(operation)


def create_model_workflow(client: SmokeApiClient, *, task: str, deployment: str, diagnostics: bool = False) -> str:
    """创建固定模型引用的最小真实图，所有输出依赖模型节点完成。"""
    suffix = uuid4().hex
    app_id = f"workflow-app-model-repair-{suffix}"
    template_id = f"workflow-template-model-repair-{suffix}"
    port, _payload = {
        "detection": ("detections", "detections.v1"),
        "classification": ("categories", "categories.v1"),
        "segmentation": ("segments", "segments.v1"),
        "pose": ("poses", "poses.v1"),
        "obb": ("obbs", "obbs.v1"),
    }[task]
    payload = "value.v1"
    template = {
        "format_id": "amvision.workflow-graph-template.v1",
        "template_id": template_id,
        "template_version": "1.0.0",
        "display_name": "模型修复发行验收",
        "nodes": [
            {
                "node_id": "model",
                "node_type_id": f"core.model.{task}",
                "parameters": {
                    "deployment_instance_id": deployment,
                    "auto_start_process": False,
                    **({"top_k": 5} if task == "classification" else {"score_threshold": 0.4}),
                    "save_result_image": False,
                    "return_preview_image_base64": False,
                },
            },
            {
                "node_id": "as_value",
                "node_type_id": "core.logic.payload-to-value",
                "parameters": {},
            },
            {
                "node_id": "public_result",
                "node_type_id": "core.logic.object-pick",
                "parameters": {"paths": ["items", "metadata", "latency_ms", "runtime_session_info"] if diagnostics else ["items"]},
            },
        ],
        # 模型 payload 带执行期 source_image，仅把推理条目作为普通 JSON 交付。
        "edges": [
            {"edge_id": "model-value", "source_node_id": "model", "source_port": port,
             "target_node_id": "as_value", "target_port": port},
            {"edge_id": "value-result", "source_node_id": "as_value", "source_port": "value",
             "target_node_id": "public_result", "target_port": "object"},
        ],
        "template_inputs": [
            {
                "input_id": "request_image_ref",
                "display_name": "Image",
                "payload_type_id": "image-ref.v1",
                "target_node_id": "model",
                "target_port": "image",
                "required": True,
            }
        ],
        "template_outputs": [
            {
                "output_id": "benchmark_result",
                "display_name": "Model result",
                "payload_type_id": payload,
                "source_node_id": "public_result",
                "source_port": "value",
            }
        ],
        "metadata": {"test_asset": True, "asset_kind": "model-matrix-repair"},
    }
    app = {
        "format_id": "amvision.flow-application.v1",
        "application_id": app_id,
        "display_name": "模型修复发行验收",
        "runtime_mode": "python-json-workflow",
        "template_ref": {
            "template_id": template_id,
            "template_version": "1.0.0",
            "source_kind": "json-file",
            "source_uri": __file__,
        },
        "bindings": [
            {
                "binding_id": "request_image_ref",
                "direction": "input",
                "template_port_id": "request_image_ref",
                "binding_kind": "trigger-source-input",
                "required": True,
                "config": {"payload_type_id": "image-ref.v1"},
            },
            {
                "binding_id": "benchmark_result",
                "direction": "output",
                "template_port_id": "benchmark_result",
                "binding_kind": "http-response",
                "required": True,
                "config": {"payload_type_id": payload},
            },
        ],
        "metadata": {"test_asset": True, "asset_kind": "model-matrix-repair"},
    }
    client.put(
        f"/workflows/projects/project-1/applications/{app_id}",
        json={"application": app, "template": template},
    )
    runtime = client.post(
        "/workflows/app-runtimes",
        json={
            "project_id": "project-1",
            "application_id": app_id,
            "display_name": "模型修复发行验收",
            "request_timeout_seconds": 120,
        },
    )
    runtime_id = runtime["workflow_runtime_id"]
    client.post(f"/workflows/app-runtimes/{runtime_id}/start")
    return runtime_id


def read_import_runtime_configuration(uploaded: dict, *, runtime_backend: str) -> DeploymentRuntimeConfiguration:
    """使用公开导入摘要中的完整部署配置，不以默认值覆盖现场实例或生命周期。"""
    package_deployment = uploaded["summary"]["deployment"]
    if package_deployment["runtime_backend"] != runtime_backend:
        raise ValueError("验收 runtime 必须与部署包一致")
    return deserialize_deployment_runtime_configuration(package_deployment["runtime_configuration"])


def run(config: dict) -> dict:
    """导入真实包并逐层验收，只有本次资源进入停止流程。"""
    if "profile" in config:
        raise ValueError("验收模式字段为 acceptance_profile，不能使用发行 profile 名称字段")
    if config.get("model_diagnostics", False) and not config.get("enable_timings", False):
        raise ValueError("model_diagnostics 要求显式 enable_timings")
    output = Path(config["output"])
    duration = positive_seconds(config.get("duration_seconds", 120), "duration_seconds")
    warmup_seconds = positive_seconds(config.get("warmup_seconds", 20), "warmup_seconds", allow_zero=True)
    profile = config.get("acceptance_profile", "short")
    if profile not in {"short", "performance", "soak"}:
        raise ValueError("acceptance_profile 必须是 short/performance/soak")
    output.mkdir(parents=True, exist_ok=False)
    phases = AcceptancePhases(Path(os.environ.get("AMVISION_ACCEPTANCE_PHASE_FILE", str(output / "phases.json"))),
                              minimum_measure_seconds=duration)
    phases.enter("prepare")
    base_url = os.environ.get(
        "AMVISION_RELEASE_FULL_BASE_URL", config.get("base_url", "")
    )
    client = SmokeApiClient(
        base_url=base_url, token="amvision-default-user-token", timeout_seconds=180
    )
    package, image = Path(config["package"]), Path(config["image"])
    prefix = "/projects/project-1/model-deployment-transfers"
    deployment = runtime = None
    sources: list[str] = []
    result: dict = {"passed": False, "profile": Path(config["release_root"]).name}
    try:
        with package.open("rb") as handle:
            operation = client.post(
                prefix + "/imports",
                files={"file": (package.name, handle, "application/zip")},
            )["operation_id"]
        uploaded = wait_transfer(client, prefix, operation, {"ready", "needs_attention"})
        runtime_configuration = read_import_runtime_configuration(uploaded, runtime_backend=config["runtime"])
        result["runtime_configuration"] = serialize_deployment_runtime_configuration(runtime_configuration)
        options = {
            "create_copy": True,
            "device_name": config["device"],
            "runtime_configuration": serialize_deployment_runtime_configuration(
                runtime_configuration
            ),
        }
        client.post(f"{prefix}/imports/{operation}/analyze", json=options)
        analyzed = wait_transfer(client, prefix, operation, {"ready"})
        client.post(
            f"{prefix}/imports/{operation}/commit",
            json={
                **options,
                "analysis_revision": analyzed["analysis_revision"],
                "idempotency_key": uuid4().hex,
            },
        )
        imported = wait_transfer(client, prefix, operation, {"completed"})
        deployment = imported["deployment_id"]
        result["import"] = {
            "operation_id": operation,
            "mapping": imported["mapping"],
            "deployment_id": deployment,
        }
        case = build_default_task_cases()[config["task"]]
        route = f"{case.deployment_route}/{deployment}"
        client.post(route + "/sync/start")
        sync = submit_direct_inference(
            client=client,
            case=case,
            deployment_id=deployment,
            model_type=config["model"],
            sample_image_path=image,
        )
        result["sync"] = summarize_inference_payload(sync)
        if config.get("verify_deployment_recovery", False):
            phases.enter("fault")
            from tests.integration.release_deployment_recovery import verify_owned_deployment_recovery
            result["recovery"] = verify_owned_deployment_recovery(
                client, route=route, release_root=Path(config["release_root"]),
            )
            result["recovery"]["inference"] = summarize_inference_payload(submit_direct_inference(
                client=client, case=case, deployment_id=deployment,
                model_type=config["model"], sample_image_path=image,
            ))
            phases.enter("recovery")
        client.post(route + "/sync/reset")
        client.post(route + "/sync/stop")
        client.post(route + "/async/start")
        task = submit_async_inference(
            client=client,
            case=case,
            project_id="project-1",
            deployment_id=deployment,
            model_type=config["model"],
            sample_image_path=image,
        )
        finished = poll_inference_task(
            client=client,
            case=case,
            task_id=task["task_id"],
            label="release async",
            timeout_seconds=120,
        )
        assert finished["state"] == "succeeded", finished
        result["async"] = {"task_id": task["task_id"], "state": finished["state"]}
        client.post(route + "/async/reset")
        client.post(route + "/async/stop")
        client.post(route + "/sync/start")
        runtime = create_model_workflow(
            client, task=config["task"], deployment=deployment,
            diagnostics=bool(config.get("model_diagnostics", False)),
        )
        result["workflow_runtime_id"] = runtime
        env = {**os.environ, "AMVISION_ACCEPTANCE_INPUT_MODE": "upload"}
        subprocess.run(
            [
                str(DOTNET_PROBE),
                "--user-access-smoke",
                base_url,
                runtime,
                str(image),
                str(output / "sdk-http.json"),
            ],
            env=env,
            check=True,
            timeout=180,
        )
        common = _source_common(runtime_id=runtime, ordinal=1, enable_timings=bool(config.get("enable_timings", False)))
        # 模型验收与独立传输矩阵分别拥有测试资产，不能互相清理或误报残留。
        common["metadata"] = {"test_asset": True, "asset_kind": "model-matrix-repair"}
        for kind in ("zeromq-topic", "local-shared-memory"):
            source_id = f"model-repair-{kind}-{uuid4().hex}"
            transport = (
                {
                    "bind_endpoint": f"tcp://127.0.0.1:{config['trigger_port']}",
                    "default_input_binding": "request_image_ref",
                    "content_transport": "local-buffer",
                }
                if kind == "zeromq-topic"
                else {}
            )
            client.post(
                "/workflows/trigger-sources",
                json={
                    **common,
                    "trigger_source_id": source_id,
                    "display_name": "模型修复发行验收",
                    "trigger_kind": kind,
                    "transport_config": transport,
                },
            )
            sources.append(source_id)
        with httpx.Client(
            base_url=base_url + "/api/v1",
            headers={"Authorization": "Bearer amvision-default-user-token"},
            timeout=120,
        ) as http:
            _wait_ready(
                http, runtime_ids=[runtime], source_ids=sources, timeout_seconds=60
            )
        settings = {
            "base_url": base_url,
            "buffers_root": str(Path(config["release_root"]) / "data/buffers"),
            "workflow_runtime_ids": [runtime],
            "zeromq_trigger_source_ids": sources[:1],
            "shared_memory_trigger_source_ids": sources[1:],
            "rounds": config.get("benchmark_rounds", 5 if profile == "performance" else 1),
            "concurrency": [1],
            "warmup_iterations": config.get("benchmark_warmup", 20 if profile == "performance" else 3),
            "iterations_per_round": config.get("benchmark_iterations", 1000 if profile == "performance" else 20),
            "enable_timings": config.get("enable_timings", False),
            "shared_poll_interval_ms": config.get("shared_poll_interval_ms"),
            "soak_iterations": 0,
            "image_cases": [
                {
                    "name": "model",
                    "path": str(image),
                    "size_class": "small",
                    "baseline_mode": "encoded-bytes",
                    "candidate_mode": "encoded-bytes",
                    "media_type": mimetypes.guess_type(str(image))[0] or "application/octet-stream",
                }
            ],
        }
        settings_path = output / "sdk-config.json"
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
        run_benchmark(
            load_settings(settings_path, output / "sdk-trigger"), build_dotnet=False
        )
        # 传输性能阈值与数值修复分开记录；任何实际调用错误都拒绝验收。
        benchmark = json.loads(
            (output / "sdk-trigger/result.json").read_text(encoding="utf-8")
        )

        def check_errors(value: object) -> None:
            """递归核对 SDK 报告中的实际失败调用。"""
            if isinstance(value, dict):
                assert not value.get("error_count", 0), value
                for child in value.values():
                    check_errors(child)
            elif isinstance(value, list):
                for child in value:
                    check_errors(child)

        check_errors(benchmark)
        assert not evaluate_health_recovery(
            benchmark["before_health"], benchmark["after_health"]
        ), benchmark["failures"]
        result["sdk_trigger_performance_failures"] = benchmark["failures"]
        result["performance_gate"] = "failed" if benchmark["failures"] else "passed"
        result["acceptance_profile"] = profile
        if matrix_config := config.get("transport_matrix"):
            from tests.integration.workflow_trigger_transport_assets import create_assets, delete_assets
            with httpx.Client(base_url=base_url + "/api/v1", headers={"Authorization": "Bearer amvision-default-user-token"}, timeout=120) as http:
                assets = create_assets(http, pair_count=max(matrix_config["concurrency"]),
                                       first_zeromq_port=config["trigger_port"] + 1, timeout_seconds=120,
                                       enable_timings=bool(matrix_config.get("enable_timings", settings["enable_timings"])))
                try:
                    matrix_settings = {**settings, **matrix_config, **assets}
                    matrix_path = output / "transport-matrix-config.json"
                    write_evidence(matrix_path, matrix_settings)
                    run_benchmark(load_settings(matrix_path, output / "transport-matrix"), build_dotnet=False)
                    matrix_report = json.loads((output / "transport-matrix/result.json").read_text(encoding="utf-8"))
                    check_errors(matrix_report)
                    result["transport_matrix_failures"] = matrix_report["failures"]
                    if matrix_report["failures"]:
                        result["performance_gate"] = "failed"
                finally:
                    delete_assets(http)
        if config.get("mixed_load", False):
            from tests.integration.release_mixed_load import run_mixed_load
            result["soak"] = run_mixed_load(
                client=client, config=config, runtime=runtime, deployment=deployment,
                source=sources[0], metadata=common["default_execution_metadata"], phases=phases,
                duration=duration, warmup=warmup_seconds,
            )
            if result["soak"]["failures"]:
                raise AssertionError(result["soak"]["failures"])
            result["passed"] = True
            return result
        # 完整请求计数独立于最近延迟窗口，72 小时负载也不累积无界列表。
        samples: deque[float] = deque(maxlen=100_000)
        success_count = 0
        phases.enter("warmup")
        warmup_start = time.monotonic()
        start = None
        image_bytes = image.read_bytes()
        with httpx.Client(
            base_url=base_url + "/api/v1",
            headers={"Authorization": "Bearer amvision-default-user-token"},
            timeout=120,
        ) as http:
            while start is None or time.monotonic() - start < duration:
                if start is None and time.monotonic() - warmup_start >= warmup_seconds:
                    phases.enter("measure")
                    start = phases.events[-1]["monotonic"]
                before = time.perf_counter()
                response = http.post(
                    f"/workflows/app-runtimes/{runtime}/invoke/upload",
                    params={"response_mode": "run"},
                    files={
                        "request_image_ref": (image.name, image_bytes, mimetypes.guess_type(str(image))[0] or "application/octet-stream")
                    },
                    data={
                        "execution_metadata_json": json.dumps(
                            common["default_execution_metadata"]
                        )
                    },
                )
                response.raise_for_status()
                assert response.json()["state"] == "succeeded", response.text[:1000]
                if start is None:
                    time.sleep(.05)
                    continue
                samples.append((time.perf_counter() - before) * 1000)
                success_count += 1
                if success_count % 100 == 0:
                    (output / "progress.json").write_text(
                        json.dumps(
                            {
                                "elapsed_seconds": time.monotonic() - start,
                                "success_count": success_count,
                            }
                        ),
                        encoding="utf-8",
                    )
                time.sleep(0.05)
        phases.enter("drain")
        result["soak"] = {
            "duration_seconds": time.monotonic() - start,
            "success_count": success_count,
            "error_count": 0,
            "latency_sample_scope": "recent-completed-requests",
            "latency_sample_count": len(samples),
            "latency_ms": dict(
                zip(
                    ("p50", "p95", "p99"), np.percentile(samples, [50, 95, 99]).tolist()
                )
            )
            if samples
            else {},
        }
        result["passed"] = True
        return result
    except Exception as error:
        result["error"] = repr(error)
        raise
    finally:
        cleanup_errors = cleanup_all([("phase-cleanup", lambda: phases.enter("cleanup"))])
        for source in sources:
            cleanup_errors.extend(cleanup_all([
                (f"disable trigger {source}", lambda source=source: client.post(f"/workflows/trigger-sources/{source}/disable")),
                (f"delete trigger {source}", lambda source=source: client.client.delete(f"/workflows/trigger-sources/{source}").raise_for_status()),
            ]))
        if runtime:
            try:
                client.post(f"/workflows/app-runtimes/{runtime}/stop")
            except Exception as error:
                cleanup_errors.append(f"runtime {runtime}: {error}")
        if deployment:
            for mode in ("sync", "async"):
                try:
                    client.post(
                        f"/models/{config['task']}/deployment-instances/{deployment}/{mode}/stop"
                    )
                except Exception as error:
                    cleanup_errors.append(f"deployment {deployment}/{mode}: {error}")
        cleanup_errors.extend(cleanup_all([("client-close", client.close)]))
        result["cleanup_errors"] = cleanup_errors
        if cleanup_errors:
            result["passed"] = False
        gates = {"functional": "passed" if result["passed"] else "failed",
                 "performance": result.get("performance_gate", "incomplete") if profile == "performance" else "observed",
                 "recovery": "passed" if "recovery" in result else "not_requested",
                 "cleanup": "failed" if cleanup_errors else "passed",
                 "coverage": "passed" if result.get("soak", {}).get("duration_seconds", 0) >= duration
                 and result.get("soak", {}).get("success_count", 0) > 0 else "incomplete"}
        required = ("functional", "cleanup", "coverage") + (("performance",) if profile == "performance" else ())
        if config.get("verify_deployment_recovery", False):
            required += ("recovery",)
        result.update(acceptance_result(gates, required))
        phases.enter("completed" if result["passed"] else "failed")
        write_evidence(output / "result.json", result)
        if outer_result := os.environ.get("AMVISION_ACCEPTANCE_RESULT_FILE"):
            write_evidence(Path(outer_result), result)
        if cleanup_errors and "error" not in result:
            raise RuntimeError("; ".join(cleanup_errors))


def main() -> None:
    """从明确配置启动验收，不默认连接现场服务。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    result = run(json.loads(args.config.read_text(encoding="utf-8")))
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
