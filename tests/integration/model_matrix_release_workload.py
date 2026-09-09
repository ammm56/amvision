"""真实发行包的模型导入、部署、Workflow、SDK 与持续调用验收。

仅连接显式指定的隔离验收服务；通过公开 API 创建本次资源，退出时停止本次会话。
配合 test_release_full_stack_acceptance 的进程资源监控和完整服务停止验证使用。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import httpx
import numpy as np

from backend.service.domain.deployments.deployment_runtime_configuration import (
    build_default_runtime_configuration,
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


def create_model_workflow(client: SmokeApiClient, *, task: str, deployment: str) -> str:
    """创建固定模型引用的最小真实图，所有输出依赖模型节点完成。"""
    suffix = uuid4().hex
    app_id = f"workflow-app-model-repair-{suffix}"
    template_id = f"workflow-template-model-repair-{suffix}"
    port, payload = {
        "detection": ("detections", "detections.v1"),
        "segmentation": ("segments", "segments.v1"),
        "pose": ("poses", "poses.v1"),
        "obb": ("obbs", "obbs.v1"),
    }[task]
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
                    "score_threshold": 0.4,
                    "save_result_image": False,
                    "return_preview_image_base64": False,
                },
            }
        ],
        "edges": [],
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
                "source_node_id": "model",
                "source_port": port,
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


def run(config: dict) -> dict:
    """导入真实包并逐层验收，只有本次资源进入停止流程。"""
    output = Path(config["output"])
    output.mkdir(parents=True, exist_ok=True)
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
        wait_transfer(client, prefix, operation, {"ready", "needs_attention"})
        options = {
            "create_copy": True,
            "device_name": config["device"],
            "runtime_configuration": serialize_deployment_runtime_configuration(
                build_default_runtime_configuration(
                    runtime_backend=config["runtime"], device_name=config["device"]
                )
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
            client, task=config["task"], deployment=deployment
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
        common = _source_common(runtime_id=runtime, ordinal=1)
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
            "rounds": 1,
            "concurrency": [1],
            "warmup_iterations": 3,
            "iterations_per_round": 20,
            "soak_iterations": 0,
            "image_cases": [
                {
                    "name": "model",
                    "path": str(image),
                    "size_class": "small",
                    "baseline_mode": "encoded-bytes",
                    "candidate_mode": "encoded-bytes",
                    "media_type": "image/jpeg",
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
        samples: list[float] = []
        duration = float(config.get("duration_seconds", 0))
        start = time.monotonic()
        image_bytes = image.read_bytes()
        with httpx.Client(
            base_url=base_url + "/api/v1",
            headers={"Authorization": "Bearer amvision-default-user-token"},
            timeout=120,
        ) as http:
            while time.monotonic() - start < duration:
                before = time.perf_counter()
                response = http.post(
                    f"/workflows/app-runtimes/{runtime}/invoke/upload",
                    params={"response_mode": "run"},
                    files={
                        "request_image_ref": (image.name, image_bytes, "image/jpeg")
                    },
                    data={
                        "execution_metadata_json": json.dumps(
                            common["default_execution_metadata"]
                        )
                    },
                )
                response.raise_for_status()
                assert response.json()["state"] == "succeeded", response.text[:1000]
                samples.append((time.perf_counter() - before) * 1000)
                if len(samples) % 100 == 0:
                    (output / "progress.json").write_text(
                        json.dumps(
                            {
                                "elapsed_seconds": time.monotonic() - start,
                                "success_count": len(samples),
                            }
                        ),
                        encoding="utf-8",
                    )
                time.sleep(0.05)
        result["soak"] = {
            "duration_seconds": time.monotonic() - start,
            "success_count": len(samples),
            "error_count": 0,
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
        cleanup_errors: list[str] = []
        for source in sources:
            try:
                client.post(f"/workflows/trigger-sources/{source}/disable")
            except Exception as error:
                cleanup_errors.append(f"trigger {source}: {error}")
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
        client.close()
        result["cleanup_errors"] = cleanup_errors
        if cleanup_errors:
            result["passed"] = False
        (output / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if cleanup_errors and "error" not in result:
            raise RuntimeError("; ".join(cleanup_errors))


def main() -> None:
    """从明确配置启动验收，不默认连接现场服务。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    run(json.loads(args.config.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
