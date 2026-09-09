"""真实图片的编辑态显示验收；隔离应用与文件输出，最长等待三分钟。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from statistics import median
from time import monotonic, perf_counter, sleep

import httpx


def main():
    """prepare 保存隔离副本；run 提交快照；observe 观察由浏览器提交的运行。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "run", "observe"))
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--delay", type=int, default=0)
    parser.add_argument("--workspace", type=Path, default=Path(".tmp/display-fix-live"))
    args = parser.parse_args()
    if not 0 <= args.delay <= 150:
        raise ValueError("延时必须在 0 至 150 秒之间")
    from backend.service.application.auth.default_local_auth_seeder import DEFAULT_LOCAL_AUTH_USERNAME, DEFAULT_LOCAL_AUTH_PASSWORD
    args.workspace.mkdir(parents=True, exist_ok=True)
    fixture_file = args.workspace / "fixture.json"
    with httpx.Client(base_url="http://127.0.0.1:5600/api/v1", timeout=90) as client:
        auth = client.post("/auth/login", json={"username": DEFAULT_LOCAL_AUTH_USERNAME, "password": DEFAULT_LOCAL_AUTH_PASSWORD})
        auth.raise_for_status()
        client.headers["Authorization"] = "Bearer " + auth.json()["access_token"]
        if args.mode == "prepare":
            template = json.loads(args.snapshot.read_text(encoding="utf8"))
            application = json.loads(args.snapshot.with_name("application.snapshot.json").read_text(encoding="utf8"))
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            app_id, graph_id = f"workflow-app-display-validation-{stamp}", f"workflow-graph-display-validation-{stamp}"
            application.update(application_id=app_id, display_name=f"Preview 显示验证 {stamp}")
            application["template_ref"].update(template_id=graph_id, source_uri=f"workflows/projects/project-1/templates/{graph_id}/versions/1.0.0/template.json")
            template.update(template_id=graph_id, display_name=application["display_name"])
            debug_enabled = False
            for node in template["nodes"]:
                params = node.get("parameters", {})
                if node["node_type_id"] == "core.logic.value-field-extract" and params.get("path") == "savepath":
                    params["default_value"] = str(args.workspace.resolve())
                if node["node_type_id"] == "core.io.image-load-local":
                    params["local_path"] = str(args.image.resolve())
                if node["node_type_id"] == "custom.opencv.hough-circles" and node.get("enabled", True) and not debug_enabled:
                    params["debug_image_panel_enabled"] = True
                    debug_enabled = True
            response = client.put(f"/workflows/projects/project-1/applications/{app_id}", json={"application": application, "template": template})
            response.raise_for_status()
            fixture = {"application": application, "template": template, "image": str(args.image.resolve()),
                       "input_bindings": {"request_json": {"value": {"savepath": str(args.workspace.resolve()), "barqrcode": "preview-display-validation"}}}}
            fixture_file.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf8")
            print(json.dumps({"application_id": app_id, "debug_enabled": debug_enabled, "image": fixture["image"]}), flush=True)
            return
        fixture = json.loads(fixture_file.read_text(encoding="utf8"))
        app_id = fixture["application"]["application_id"]
        started = monotonic()
        if args.mode == "run":
            template = fixture["template"]
            if args.delay:
                output = template["template_outputs"][0]
                template["nodes"].append({"node_id": "validation_delay", "node_type_id": "core.logic.delay", "parameters": {"seconds": args.delay}})
                template["edges"].append({"edge_id": "validation_wait", "source_node_id": output["source_node_id"], "source_port": output["source_port"], "target_node_id": "validation_delay", "target_port": "value"})
                template["template_outputs"][0] = {**output, "source_node_id": "validation_delay", "source_port": "value"}
            body = {"project_id": "project-1", "application": fixture["application"], "template": template,
                    "wait_mode": "async", "timeout_seconds": 240, "input_bindings": fixture["input_bindings"],
                    "execution_metadata": {"retain_node_records_enabled": True, "debug_image_panels_enabled": True}}
            image = Path(fixture["image"])
            with image.open("rb") as stream:
                response = client.post("/workflows/preview-runs/multipart", data={"request": json.dumps(body)}, files=[("request_image_ref", (image.name, stream, "image/bmp"))])
            response.raise_for_status()
            run_id = response.json()["preview_run_id"]
        else:
            response = client.get("/workflows/preview-runs", params={"project_id": "project-1", "limit": 100})
            response.raise_for_status()
            run_id = next(r["preview_run_id"] for r in response.json() if r["application_id"] == app_id)
        latencies, failures, identities = [], 0, set()
        last_progress = monotonic()
        print(json.dumps({"run_id": run_id, "phase": "observing"}), flush=True)
        while monotonic() - started < 180:
            tick = perf_counter()
            try:
                health = client.get("/system/liveness", timeout=2)
                health.raise_for_status()
                identities.add(health.json()["instance_id"])
                latencies.append((perf_counter() - tick) * 1000)
            except httpx.HTTPError:
                failures += 1
            response = client.get(f"/workflows/preview-runs/{run_id}")
            response.raise_for_status()
            record = response.json()
            if record["state"] not in {"running", "created"}:
                break
            if monotonic() - last_progress > 40:
                print(json.dumps({"elapsed": round(monotonic()-started), "http_failures": failures}), flush=True)
                last_progress = monotonic()
            sleep(.5)
        manifest = client.get(f"/workflows/preview-runs/{run_id}/displays").json()
        displays = []
        for item in manifest["displays"]:
            payload = client.get(f"/workflows/preview-runs/{run_id}/displays/{item['display_id']}")
            payload.raise_for_status()
            displays.append({**item, "payload_bytes": len(payload.content), "type": payload.json()["type"]})
        ordered = sorted(latencies)
        summary = {"run_id": run_id, "application_id": app_id, "state": record["state"], "elapsed": round(monotonic()-started, 3),
                   "http_failures": failures, "http_samples": len(ordered), "http_instance_count": len(identities),
                   "http_p50_ms": median(ordered), "http_p99_ms": ordered[min(len(ordered)-1, int(len(ordered)*.99))],
                   "outputs": record["outputs"], "displays": displays, "display_error": manifest.get("error")}
        (args.workspace / f"{run_id}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        assert record["state"] == "succeeded", record
        assert not failures and len(identities) == 1 and not manifest.get("error")
        assert sum(d["type"] == "value-preview" for d in displays) >= 3
        assert any(d["type"] == "image-preview" for d in displays)


if __name__ == "__main__":
    main()
