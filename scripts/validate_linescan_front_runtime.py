"""复制当前正面草稿并用临时 Runtime 验证 CPU 整链；结束后物理删除验证资源。"""

import argparse
import copy
from datetime import datetime
import json
from itertools import count
from pathlib import Path
from time import perf_counter, sleep

import httpx
import psutil

from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
)
from scripts.configure_linescan_3913_workflow import APP_ID, DATA


def main():
    """使用正式发布和 Runtime API；原应用、原 Runtime 和 Trigger 保持原配置。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=0,
        help="连续串行调用至指定时长；仅用于验收，不改变 Runtime 调度",
    )
    parser.add_argument("--bundle", type=Path, help="可选固定工作流快照，用于交替对照")
    parser.add_argument("--decode-method", choices=["opencv", "bmp-bgr24"])
    parser.add_argument("--report", default="runtime-openvino")
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument(
        "--timings", action="store_true", help="返回已有节点计时，不新增诊断节点"
    )
    parser.add_argument(
        "--baseline-report", help="逐槽比较已有 Runtime 报告中的检测数值"
    )
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--image", default="3913正面大图.bmp")
    parser.add_argument("--barcode-bbox", type=int, nargs=4)
    parser.add_argument("--reject-all", action="store_true")
    args = parser.parse_args()
    baseline_checks = None
    if args.baseline_report:
        baseline = json.loads(Path(args.baseline_report).read_text("utf-8"))
        previous = baseline["runs"][0]["response"]
        previous = (previous.get("outputs") or previous.get("results"))["report"][
            "value"
        ]
        baseline_checks = checks_by_id(previous)
    root = (DATA / "validation/front-performance").resolve()
    out = (root / args.report).resolve()
    if not out.is_relative_to(root) or out == root:
        raise ValueError("报告必须在 front-performance 的独立子目录中")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    aid, tid = "workflow-app-" + stamp, "workflow-graph-" + stamp
    prefix = "/api/v1/workflows"
    app_url = prefix + "/projects/project-1/applications/" + aid
    runtime_url = None
    created = False
    image_path = (DATA / args.image).resolve()
    if not image_path.is_relative_to(DATA.resolve()) or not image_path.is_file():
        raise ValueError("验证图片必须是当前线扫数据目录中的已有文件")
    result = {
        "application_id": aid,
        "runs": [],
        "cleanup": {},
        "options": {
            k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()
        },
    }
    with httpx.Client(
        base_url="http://127.0.0.1:5600",
        timeout=240,
        headers={"Authorization": "Bearer " + DEFAULT_LOCAL_AUTH_TOKEN},
    ) as client:

        def call(method, path, **kw):
            """错误保留状态码和正文，不能把失败测量当作成功耗时。"""
            response = client.request(method, path, **kw)
            if response.is_error:
                raise RuntimeError(
                    f"{method} {path}: {response.status_code} {response.text[:2500]}"
                )
            return response.json() if response.content else None

        def save():
            """每次调用及清理后写入审计结果。"""
            (out / "report.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), "utf-8"
            )

        def memory():
            """记录 Python 进程 Private/句柄，区分 Worker 与模型常驻基线。"""
            rows = []
            for process in psutil.process_iter(["name"]):
                try:
                    if (process.info["name"] or "").lower().startswith("python"):
                        mem = process.memory_info()
                        rows.append(
                            {
                                "pid": process.pid,
                                "private": mem.private,
                                "rss": mem.rss,
                                "handles": process.num_handles(),
                            }
                        )
                except psutil.Error:
                    pass
            return rows

        def environment():
            """记录相邻采样之间整机 CPU 负载和可用内存，不启动采样线程。"""
            return {
                "cpu_percent_since_previous_sample": psutil.cpu_percent(),
                "available_memory_bytes": psutil.virtual_memory().available,
            }

        try:
            source = call("GET", prefix + "/projects/project-1/applications/" + APP_ID)
            app = copy.deepcopy(source["application"])
            ref = app["template_ref"]
            template = call(
                "GET",
                prefix
                + f"/projects/project-1/templates/{ref['template_id']}/versions/{ref['template_version']}",
            )["template"]
            if args.bundle:
                bundle = json.loads(args.bundle.read_text("utf-8"))
                app, template = bundle["application"], bundle["template"]
            app.update(
                application_id=aid, display_name="3913 CPU 性能临时验证 " + stamp
            )
            app["template_ref"]["template_id"] = tid
            template["template_id"] = tid
            evidence_ids = {
                node_id
                for group in template.get("groups", [])
                if group["group_id"] == "inspection-evidence"
                for node_id in group["member_node_ids"]
            }
            result["disabled_evidence_nodes"] = sorted(evidence_ids)
            for node in template["nodes"]:
                if node["node_id"] in evidence_ids or node["node_type_id"] in {
                    "core.io.image-preview",
                    "core.io.value-preview",
                    "custom.opencv.gallery-preview",
                }:
                    node["enabled"] = False
                for key in ("debug_image_panel_enabled", "emit_comparison_images"):
                    if key in node.get("parameters", {}):
                        node["parameters"][key] = False
                if node["node_type_id"] in {
                    "core.model.detection",
                    "core.model.detection-batch",
                }:
                    node["parameters"]["deployment_instance_id"] = args.deployment_id
                if node["node_id"] == "barcode_roi" and args.barcode_bbox:
                    node["parameters"]["bbox_xyxy"] = args.barcode_bbox
                if node["node_id"] == "decoded_source" and args.decode_method:
                    node["parameters"]["decode_method"] = args.decode_method
                if (
                    node["node_id"] == "compare_foreground"
                    and args.reject_all
                    and node["node_type_id"] == "custom.opencv.roi-foreground-compare"
                ):
                    node["parameters"]["max_centroid_shift_pixels"] = 0
                if node["node_id"] == "check_reference_area" and args.reject_all:
                    node["parameters"]["minimum"] = 1_000_000_000
            if args.batch and not any(
                node["node_id"] == "batch_detect" for node in template["nodes"]
            ):
                from scripts.linescan_batch_variant import build

                payload = build(app, template)
                app, template = payload["application"], payload["template"]
            if args.diagnostics:
                # 仅验证副本公开原有模型诊断，避免为审计改动节点的正式输出契约。
                for name, kind, parameters in [
                    ("audit_detection", "core.logic.payload-to-value", {}),
                    (
                        "audit_field",
                        "core.logic.object-field",
                        {"key": "inference_diagnostics"},
                    ),
                ]:
                    template["nodes"].append(
                        {
                            "node_id": name,
                            "node_type_id": kind,
                            "parameters": parameters,
                            "enabled": True,
                        }
                    )
                for index, (source, port, target, target_port) in enumerate(
                    [
                        ("detect_code", "detections", "audit_detection", "detections"),
                        ("audit_detection", "value", "audit_field", "value"),
                        ("audit_field", "field", "code_item", "entries"),
                    ]
                ):
                    template["edges"].append(
                        {
                            "edge_id": f"audit-{index}",
                            "source_node_id": source,
                            "source_port": port,
                            "target_node_id": target,
                            "target_port": target_port,
                        }
                    )
            if any(node["node_id"] == "final_report" for node in template["nodes"]):
                # 验证副本额外公开已有诊断，核对新 JSON 汇总没有改变原检测数值。
                diagnostic = copy.deepcopy(
                    next(b for b in app["bindings"] if b["binding_id"] == "report")
                )
                diagnostic.update(
                    binding_id="audit_report", template_port_id="audit_report"
                )
                app["bindings"].append(diagnostic)
                template["template_outputs"].append(
                    {
                        "output_id": "audit_report",
                        "display_name": "审计原始检测",
                        "payload_type_id": "value.v1",
                        "source_node_id": "report",
                        "source_port": "value",
                    }
                )
            (out / "workflow-bundle.json").write_text(
                json.dumps(
                    {"application": app, "template": template},
                    ensure_ascii=False,
                    indent=2,
                ),
                "utf-8",
            )
            saved = call(
                "PUT", app_url, json={"application": app, "template": template}
            )
            created = True
            version = call(
                "POST",
                app_url + "/versions",
                json={
                    "expected_draft_fingerprint": saved["draft_fingerprint"],
                    "release_notes": "禁用预览的 CPU 整链验证，结束即删除",
                },
            )
            runtime = call(
                "POST",
                prefix + "/app-runtimes",
                json={
                    "project_id": "project-1",
                    "workflow_app_version_id": version["workflow_app_version_id"],
                    "display_name": "3913 CPU 性能临时验证",
                    "request_timeout_seconds": 120,
                    "metadata": {"workflow_run_record_mode": "none"},
                },
            )
            rid = runtime["workflow_runtime_id"]
            result["workflow_runtime_id"] = rid
            runtime_url = prefix + "/app-runtimes/" + rid
            save()
            result["started"] = call("POST", runtime_url + "/start")
            result["memory_before"] = memory()
            result["environment_before"] = environment()
            save()
            repeated_start = perf_counter()
            for index in count():
                if (
                    index >= args.runs
                    and perf_counter() - repeated_start >= args.duration_seconds
                ):
                    break
                start = perf_counter()
                response = call(
                    "POST",
                    runtime_url
                    + "/invoke"
                    + (
                        "?response_mode=debug"
                        if args.diagnostics or args.timings
                        else ""
                    ),
                    json={
                        "input_bindings": {
                            "request_image_ref": {
                                "transport_kind": "local-path",
                                "local_path": str(image_path),
                                "media_type": "image/bmp",
                                "width": 20000,
                                "height": 16384,
                            }
                        },
                        "timeout_seconds": 120,
                        "execution_metadata": {
                            "workflow_run_record_mode": "none",
                            "retain_node_records_enabled": args.diagnostics
                            or args.timings,
                            "return_timing_metadata_enabled": args.diagnostics
                            or args.timings,
                            "return_node_timings_enabled": args.diagnostics
                            or args.timings,
                        },
                    },
                )
                elapsed = (perf_counter() - start) * 1000
                result["runs"].append(
                    {
                        "index": index + 1,
                        "elapsed_ms": elapsed,
                        "response": response,
                        "memory": memory(),
                        "environment": environment(),
                    }
                )
                result["repeated_elapsed_seconds"] = perf_counter() - repeated_start
                save()
                print(
                    "run", index + 1, round(elapsed, 2), str(response)[:160], flush=True
                )
                if response.get("state", response.get("workflow_state")) != "succeeded":
                    raise RuntimeError(f"运行失败: {response.get('error')}")
                from scripts.validate_linescan_front_cases import (
                    code_texts,
                    result_value,
                )

                _, reference = result_value(
                    DATA / "validation/front-array/stage2-original"
                )
                outputs = response.get("outputs") or response.get("results")
                value = outputs.get("audit_report", outputs["report"])["value"]
                expected = code_texts(reference)
                # ROI Grid 已显式统一 ID 命名，按键转换旧基准，不按位置关联。
                expected = {
                    key.replace("slot-r", "slot-").replace("-c", "-"): value
                    for key, value in expected.items()
                }
                if args.reject_all:
                    expected = {}
                    assert all(
                        not item["result"]["passed"]
                        for item in value["placement_2d"]["items"]
                    )
                elif image_path.name == "full-missing.bmp":
                    expected.pop("slot-02-03")
                    assert [
                        item["item_id"]
                        for item in value["placement_2d"]["items"]
                        if not item["result"]["passed"]
                    ] == ["slot-02-03"]
                else:
                    assert value["placement_2d"]["passed"] is True
                assert code_texts(value) == expected, (
                    "条码文本或槽位 ID 与优化前基准不一致"
                )
                result["runs"][-1]["correctness"] = {
                    "codes_equal_by_id": True,
                    "decoded_slot_count": len(expected),
                }
                if "audit_report" in outputs:
                    validate_final_result(outputs["report"]["value"], value, expected)
                    result["runs"][-1]["correctness"]["final_result_matches"] = True
                if baseline_checks is not None:
                    assert checks_by_id(value) == baseline_checks, (
                        "检测逐项数值或判定与基准不一致"
                    )
                    result["runs"][-1]["correctness"]["measurements_equal_by_id"] = True
                save()
                sleep(1)
        finally:
            if runtime_url:
                try:
                    result["cleanup"]["stop"] = call("POST", runtime_url + "/stop")
                    result["cleanup"]["runtime_deleted"] = (
                        call("DELETE", runtime_url) is None
                    )
                except Exception as error:
                    result["cleanup"]["runtime_error"] = str(error)
            if created:
                try:
                    result["cleanup"]["application_deleted"] = (
                        call("DELETE", app_url) is None
                    )
                except Exception as error:
                    result["cleanup"]["application_error"] = str(error)
            result["memory_after"] = memory()
            save()


def checks_by_id(summary):
    """按槽位 ID 比较全部业务测量，排除图片句柄并拒绝重复 ID。"""
    items = summary["placement_2d"]["items"]
    result = {item["item_id"]: item["result"] for item in items}
    assert len(result) == len(items), "检测结果中存在重复槽位 ID"
    return result


def validate_final_result(result, diagnostics, expected):
    """按 ID 对照原始检测和码值，验证统一坐标及完整 NG 记录。"""
    assert result["image_size"] == [2500, 2048]
    assert result["coordinate_space"] == "resized-source-image-pixels"
    assert result["count"] == result["expected_count"] == 18
    by_id = {item["item_id"]: item for item in result["items"]}
    assert len(by_id) == 18
    for original in diagnostics["placement_2d"]["items"]:
        item = by_id[original["item_id"]]
        assert item["placement"]["result"] == (
            "OK" if original["result"]["passed"] else "NG"
        )
        assert item["barcode"]["values"] == expected.get(original["item_id"], [])
        assert item["placement"]["roi"]["polygon_xy"]
        for geometry in [item["placement"]["roi"], *item["barcode"]["detections"]]:
            x1, y1, x2, y2 = geometry["bbox_xyxy"]
            assert 0 <= x1 < x2 <= 2500 and 0 <= y1 < y2 <= 2048
        assert (item["result"] == "OK") == (
            item["placement"]["result"] == "OK" and item["barcode"]["result"] == "OK"
        )
    assert (result["result"] == "OK") == all(
        item["result"] == "OK" for item in result["items"]
    )


if __name__ == "__main__":
    main()
