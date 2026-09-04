"""创建独立验证 App/Runtime/目录 Trigger，使用真实保存结果副本验证本地读取。

默认仅操作新建的 data/validation/local-file-reading-<时间>，不改已有业务资源。
测试结束停止新建 Trigger 和 Runtime，保留可继续使用的 App 与少量测试输入。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import statistics
import time
from uuid import uuid4

import httpx


def node(identifier, kind, parameters=None, x=0, y=0):
    """创建有明确画布位置的通用节点。"""
    return {
        "node_id": identifier,
        "node_type_id": kind,
        "parameters": parameters or {},
        "ui_state": {"x": x, "y": y},
    }


def edge(source, source_port, target, target_port):
    """创建具名端口连线。"""
    return {
        "edge_id": f"{source}-{source_port}-{target}-{target_port}",
        "source_node_id": source,
        "source_port": source_port,
        "target_node_id": target,
        "target_port": target_port,
    }


def output(name, source, port, payload="value.v1"):
    """声明公开输出。"""
    return {
        "output_id": name,
        "display_name": name,
        "source_node_id": source,
        "source_port": port,
        "payload_type_id": payload,
    }


def build_latest(root: Path):
    """分别演示最新图片/JSON/文本，不把三个文件推断成同一业务记录。"""
    nodes, edges, outputs = [], [], []
    for row, (kind, folder, extensions) in enumerate(
        (
            ("image", "images", ["jpg", "png"]),
            ("json", "json", ["json"]),
            ("text", "text", ["txt"]),
        )
    ):
        latest, load = f"latest_{kind}", f"load_{kind}"
        nodes.extend(
            (
                node(
                    latest,
                    "core.io.directory-latest-file",
                    {
                        "directory_path": str(root / folder),
                        "extensions": extensions,
                    },
                    0,
                    row * 600,
                ),
                node(load, f"core.io.{kind}-load-local", x=420, y=row * 600),
            )
        )
        edges.append(edge(latest, "file", load, "file"))
        outputs.append(output(f"{kind}_source", load, "summary"))
        if kind != "image":
            outputs.append(
                output(
                    kind,
                    load,
                    "value" if kind == "json" else "text",
                    "value.v1" if kind == "json" else "text.v1",
                )
            )
    nodes.append(
        node(
            "save_result",
            "core.output.json-save-local",
            {
                "save_directory": str(root / "out"),
                "file_name": "latest-result.json",
                "overwrite": True,
            },
            840,
            600,
        )
    )
    edges.append(edge("load_json", "value", "save_result", "value"))
    outputs.append(output("saved", "save_result", "summary"))
    return nodes, edges, [], outputs


def build_event(root: Path):
    """可选 request_json → 取样本 → 排除删除 → ForEach 显式 Path 读取。"""
    nodes = [
        node(
            "optional_event",
            "core.logic.coalesce",
            {"fallback_value": {"samples": []}},
            0,
            0,
        ),
        node("samples", "core.logic.value-field-extract", {"path": "samples"}, 340, 0),
        node(
            "readable_samples",
            "core.logic.list-filter",
            {
                "condition": {
                    "operator": "not",
                    "condition": {
                        "operator": "contains",
                        "path": "observed_change_types",
                        "right": "deleted",
                    },
                }
            },
            680,
            0,
        ),
        node("each_start", "core.logic.for-each-start", x=1020),
        node(
            "sample_path", "core.logic.value-field-extract", {"path": "path"}, 1360, 0
        ),
        node("read_json", "core.io.json-load-local", x=1700),
        node("each_end", "core.logic.for-each-end", x=2040),
        node(
            "save_result",
            "core.output.json-save-local",
            {
                "save_directory": str(root / "out"),
                "file_name": "event-result.json",
                "overwrite": True,
            },
            2380,
            0,
        ),
    ]
    edges = [
        edge("optional_event", "value", "samples", "value"),
        edge("samples", "value", "readable_samples", "items"),
        edge("readable_samples", "value", "each_start", "items"),
        edge("each_start", "item", "sample_path", "value"),
        edge("sample_path", "value", "read_json", "path"),
        edge("read_json", "value", "each_end", "result"),
        edge("each_end", "results", "save_result", "value"),
    ]
    inputs = [
        {
            "input_id": "request_json",
            "display_name": "Request JSON",
            "payload_type_id": "value.v1",
            "target_node_id": "optional_event",
            "target_port": "primary",
            "required": False,
        }
    ]
    outputs = [
        output("event", "optional_event", "value"),
        output("results", "each_end", "results"),
        output("saved", "save_result", "summary"),
    ]
    return nodes, edges, inputs, outputs


class LiveValidation:
    """仅持有本次新建资源，退出时停止测试的执行器。"""

    def __init__(self, client, root):
        self.client, self.root = client, root
        self.resources = []

    def api(self, method, path, body=None):
        response = self.client.request(method, path, json=body)
        if response.is_error:
            raise RuntimeError(
                f"{method} {path}: {response.status_code} {response.text[:2000]}"
            )
        return response.json() if response.content else None

    def create(self, stamp, name, graph_parts, folder, mapping):
        """保存草稿、发布 v1、创建并启动独立 Runtime/Trigger。"""
        app_id, graph_id = f"workflow-app-{stamp}", f"workflow-graph-{stamp}"
        nodes, edges, inputs, outputs = graph_parts
        metadata = {"test_asset": True, "asset_kind": "local-file-reading-validation"}
        template = {
            "template_id": graph_id,
            "template_version": "1.0.0",
            "display_name": name,
            "nodes": nodes,
            "edges": edges,
            "template_inputs": inputs,
            "template_outputs": outputs,
            "metadata": metadata,
        }
        bindings = [
            {
                "binding_id": item["input_id"],
                "template_port_id": item["input_id"],
                "direction": "input",
                "binding_kind": "trigger-source-input",
                "required": False,
                "config": {"payload_type_id": item["payload_type_id"]},
            }
            for item in inputs
        ]
        bindings += [
            {
                "binding_id": item["output_id"],
                "template_port_id": item["output_id"],
                "direction": "output",
                "binding_kind": "http-response",
                "required": True,
                "config": {"payload_type_id": item["payload_type_id"]},
            }
            for item in outputs
        ]
        application = {
            "application_id": app_id,
            "display_name": name,
            "template_ref": {
                "template_id": graph_id,
                "template_version": "1.0.0",
                "source_kind": "json-file",
                "source_uri": "tests/integration/local_file_reading_live.py",
            },
            "bindings": bindings,
            "metadata": metadata,
        }
        document = self.api(
            "PUT",
            f"/workflows/projects/project-1/applications/{app_id}",
            {"application": application, "template": template},
        )
        version = self.api(
            "POST",
            f"/workflows/projects/project-1/applications/{app_id}/versions",
            {
                "expected_draft_fingerprint": document["draft_fingerprint"],
                "release_notes": "本地文件读取验证",
                "display_version": "v1",
            },
        )
        runtime = self.api(
            "POST",
            "/workflows/app-runtimes",
            {
                "project_id": "project-1",
                "workflow_app_version_id": version["workflow_app_version_id"],
                "display_name": name + " runtime",
                "metadata": metadata,
            },
        )
        rid = runtime["workflow_runtime_id"]
        resource = {"application_id": app_id, "workflow_runtime_id": rid, "name": name}
        self.resources.append(resource)
        self.api("POST", f"/workflows/app-runtimes/{rid}/start")
        self.wait(
            lambda: (
                self.api("GET", f"/workflows/app-runtimes/{rid}/health").get(
                    "observed_state"
                )
                == "running"
            )
        )
        source = f"directory-watch-{rid}-{uuid4().hex[:8]}"
        self.api(
            "POST",
            "/workflows/trigger-sources",
            {
                "project_id": "project-1",
                "trigger_source_id": source,
                "display_name": name + " directory trigger",
                "trigger_kind": "directory-watch",
                "workflow_runtime_id": rid,
                "submit_mode": "async",
                "enabled": True,
                "transport_config": {
                    "directory_path": str(self.root / folder),
                    "extensions": [".json"],
                    "min_trigger_interval_seconds": 3.0,
                    "event_sample_limit": 10,
                },
                "input_binding_mapping": mapping,
                "result_mapping": {"result_bindings": []},
                "default_execution_metadata": {"workflow_run_record_mode": "none"},
                "ack_policy": "ack-after-run-created",
                "result_mode": "event-only",
                "idempotency_key_path": "payload.directory_event_value.value.event_id",
                "metadata": metadata,
            },
        )
        resource["trigger_source_id"] = source
        self.wait(
            lambda: (
                self.api("GET", f"/workflows/trigger-sources/{source}/health")[
                    "observed_state"
                ]
                == "running"
            )
        )
        return resource

    def invoke(self, resource, inputs=None):
        """显式低开销调用，不保存 WorkflowRun 记录。"""
        result = self.api(
            "POST",
            f"/workflows/app-runtimes/{resource['workflow_runtime_id']}/invoke?response_mode=run",
            {
                "input_bindings": inputs or {},
                "execution_metadata": {"workflow_run_record_mode": "none"},
            },
        )
        assert result["state"] == "succeeded", result
        return result

    def wait(self, predicate, timeout=40):
        """测试程序有限等待真实状态变化；不是产品节点的重试逻辑。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.3)
        raise TimeoutError("验证等待超时")

    def stop(self):
        """只停止本次新建资源，不删除业务文件。"""
        for resource in self.resources:
            if source := resource.get("trigger_source_id"):
                self.api("POST", f"/workflows/trigger-sources/{source}/disable")
            self.api(
                "POST",
                f"/workflows/app-runtimes/{resource['workflow_runtime_id']}/stop",
            )


def main():
    """从指定真实生产结果创建副本并执行端到端验证。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now()
    root = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "validation"
        / f"local-file-reading-{now:%Y%m%d%H%M%S}"
    )
    for name in ("images", "json", "text", "events", "out"):
        (root / name).mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.image, root / "images" / args.image.name)
    shutil.copy2(args.json, root / "json" / args.json.name)
    (root / "text" / "note.txt").write_text("真实目录读取验证 abc123", encoding="utf-8")
    with httpx.Client(
        base_url="http://127.0.0.1:5600/api/v1",
        timeout=45,
        trust_env=False,
        headers={"Authorization": "Bearer amvision-default-user-token"},
    ) as client:
        validation = LiveValidation(client, root)
        report = {"fixture_root": str(root), "resources": validation.resources}
        try:
            latest = validation.create(
                now.strftime("%Y%m%d%H%M%S"),
                "目录最新图片 JSON 文本读取验证",
                build_latest(root),
                "json",
                {},
            )
            event = validation.create(
                (now + timedelta(seconds=1)).strftime("%Y%m%d%H%M%S"),
                "目录变化文件读取验证",
                build_event(root),
                "events",
                {
                    "request_json": {
                        "source": "payload.directory_event_value",
                        "required": False,
                        "payload_type_id": "value.v1",
                    },
                },
            )
            for resource in (latest, event):
                preview = validation.api(
                    "POST",
                    "/workflows/preview-runs",
                    {
                        "project_id": "project-1",
                        "application_ref": {
                            "application_id": resource["application_id"]
                        },
                        "input_bindings": {},
                    },
                )
                assert preview["state"] == "succeeded", preview
                validation.invoke(resource)
            timings = []
            for _ in range(60):
                started = time.perf_counter()
                result = validation.invoke(latest)
                assert result["outputs"]["json"]["value"] == json.loads(
                    args.json.read_text(encoding="utf-8")
                )
                timings.append((time.perf_counter() - started) * 1000)
            report["runtime_calls"] = {
                "count": 60,
                "median_ms": statistics.median(timings),
                "p95_ms": sorted(timings)[56],
            }
            print(json.dumps(report), flush=True)

            # 发布新 JSON 触发无参数 App；副本目录完全独立于生产数据。
            marker = {"validation": "latest-trigger", "batch_id": "abc123"}
            (root / "json" / "latest.json").write_text(
                json.dumps(marker), encoding="utf-8"
            )
            latest_result = root / "out" / "latest-result.json"
            validation.wait(
                lambda: (
                    latest_result.exists()
                    and json.loads(latest_result.read_text(encoding="utf-8")) == marker
                )
            )
            event_result = root / "out" / "event-result.json"
            baseline = event_result.stat().st_mtime_ns
            for index in range(20):
                (root / "events" / f"{index:02d}.json").write_text(
                    json.dumps({"index": index}), encoding="utf-8"
                )
            validation.wait(lambda: event_result.stat().st_mtime_ns > baseline)
            values = json.loads(event_result.read_text(encoding="utf-8"))
            assert 1 <= len(values) <= 10 and all(
                0 <= value["index"] < 20 for value in values
            ), values
            report["created_sample_count"] = len(values)
            baseline = event_result.stat().st_mtime_ns
            for path in sorted((root / "events").glob("*.json"))[:3]:
                path.unlink()
            validation.wait(lambda: event_result.stat().st_mtime_ns > baseline)
            assert json.loads(event_result.read_text(encoding="utf-8")) == []
            report["deleted_samples_skipped"] = True
            report["health"] = [
                validation.api(
                    "GET",
                    f"/workflows/trigger-sources/{resource['trigger_source_id']}/health",
                )["health_summary"]
                for resource in validation.resources
            ]
        finally:
            validation.stop()
            (root / "validation-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
