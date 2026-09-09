"""真实 Workflow 快照与图片的长预览验证；只创建隔离 App，输出限定在 .tmp。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from statistics import median
from time import monotonic, sleep

import httpx


def main():
    """显式选择源快照和图片，验证长执行期间 HTTP 响应与最终业务输出。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--seconds", type=float, nargs="+", default=[30, 300, 1800])
    parser.add_argument("--base-url", default="http://127.0.0.1:5600/api/v1")
    args = parser.parse_args()
    from backend.service.application.auth.default_local_auth_seeder import (
        DEFAULT_LOCAL_AUTH_USERNAME, DEFAULT_LOCAL_AUTH_PASSWORD)
    source = json.loads(args.snapshot.read_text(encoding="utf8"))
    application = json.loads(args.snapshot.with_name("application.snapshot.json").read_text(encoding="utf8"))
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    app_id = f"workflow-app-preview-validation-{stamp}"
    graph_id = f"workflow-graph-preview-validation-{stamp}"
    output = Path(".tmp/preview-real-validation") / stamp
    output.mkdir(parents=True, exist_ok=True)
    application.update(application_id=app_id, display_name=f"Preview 长执行验证 {stamp}")
    application["template_ref"].update(template_id=graph_id, source_uri=
        f"workflows/projects/project-1/templates/{graph_id}/versions/1.0.0/template.json")
    template = deepcopy(source)
    template.update(template_id=graph_id, display_name=f"Preview 长执行验证 {stamp}")
    for node in template["nodes"]:
        params = node.get("parameters", {})
        if node["node_type_id"] == "core.logic.value-field-extract" and params.get("path") == "savepath":
            params["default_value"] = str(output.resolve())
        if node["node_type_id"] == "core.io.image-load-local":
            params["local_path"] = str(args.image.resolve())
    original_output = template["template_outputs"][0]
    template["nodes"].append({"node_id": "validation_delay", "node_type_id": "core.logic.delay",
                              "parameters": {"seconds": 0}, "ui_state": {"x": 0, "y": 0}})
    template["edges"].append({"edge_id": "validation_delay_input", "source_node_id": original_output["source_node_id"],
                              "source_port": original_output["source_port"], "target_node_id": "validation_delay", "target_port": "value"})
    template["template_outputs"][0] = {**original_output, "source_node_id": "validation_delay", "source_port": "value"}
    records = []
    with httpx.Client(base_url=args.base_url, timeout=120) as client:
        auth = client.post("/auth/login", json={"username": DEFAULT_LOCAL_AUTH_USERNAME, "password": DEFAULT_LOCAL_AUTH_PASSWORD})
        auth.raise_for_status()
        client.headers["Authorization"] = "Bearer " + auth.json()["access_token"]
        response = client.put(f"/workflows/projects/project-1/applications/{app_id}", json={"application": application, "template": template})
        response.raise_for_status()
        print(json.dumps({"application_id": app_id, "output": str(output), "phase": "created"}), flush=True)
        for seconds in args.seconds:
            template["nodes"][-1]["parameters"]["seconds"] = seconds
            body = {"project_id": "project-1", "application": application, "template": template,
                    "wait_mode": "async", "timeout_seconds": int(seconds + 600),
                    "input_bindings": {"request_json": {"value": {"savepath": str(output.resolve()), "barqrcode": "preview-validation"}}},
                    "execution_metadata": {"retain_node_records_enabled": True, "source": "long-preview-validation"}}
            started = monotonic()
            with args.image.open("rb") as image:
                response = client.post("/workflows/preview-runs/multipart", data={"request": json.dumps(body)},
                                       files=[("request_image_ref", (args.image.name, image, "image/bmp"))])
            response.raise_for_status()
            run_id = response.json()["preview_run_id"]
            latencies, failures, identities = [], 0, set()
            last_progress = monotonic()
            while monotonic() - started < seconds + 650:
                tick = monotonic()
                try:
                    health = client.get("/system/liveness", timeout=1)
                    health.raise_for_status()
                    identities.add(health.json()["instance_id"])
                    latencies.append((monotonic() - tick) * 1000)
                except httpx.HTTPError:
                    failures += 1
                response = client.get(f"/workflows/preview-runs/{run_id}")
                response.raise_for_status()
                record = response.json()
                if record["state"] not in {"created", "running"}:
                    break
                if monotonic() - last_progress >= 45:
                    print(json.dumps({"run_id": run_id, "elapsed": round(monotonic()-started), "liveness_failures": failures}), flush=True)
                    last_progress = monotonic()
                sleep(.5)
            ordered = sorted(latencies)
            summary = {"run_id": run_id, "delay_seconds": seconds, "elapsed": round(monotonic()-started, 3),
                       "state": record["state"], "error": record.get("error"), "outputs": record.get("outputs"),
                       "liveness_failures": failures, "identity_count": len(identities), "samples": len(ordered),
                       "liveness_p50_ms": median(ordered) if ordered else None,
                       "liveness_p99_ms": ordered[min(len(ordered)-1, int(len(ordered)*.99))] if ordered else None}
            records.append(summary)
            (output / "results.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf8")
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            if record["state"] != "succeeded" or failures or len(identities) != 1:
                raise RuntimeError("真实长预览验证未通过")


if __name__ == "__main__":
    main()
