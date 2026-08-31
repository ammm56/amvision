"""开发期 Workflow baseline 重建脚本测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.rebuild_development_workflows import build_rebuild_plans


def test_build_rebuild_plans_rewrites_ids_and_limits_trigger_inputs(
    tmp_path: Path,
) -> None:
    """验证 App/Graph 同时间命名，并且高性能 Trigger 不包含 HTTP 文件输入。"""

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    _write_json(
        source_dir / "application.json",
        {
            "format_id": "amvision.flow-application.v1",
            "application_id": "workflow-app-20260101000000",
            "display_name": "old",
            "template_ref": {
                "template_id": "workflow-graph-20260101000000",
                "template_version": "1.0.0",
                "source_kind": "json-file",
                "source_uri": "workflow-graph-20260101000000/template.json",
            },
            "bindings": [
                _binding("request_image_ref", "input", "image-ref.v1"),
                _binding("request_json", "input", "value.v1"),
                _binding("request_text", "input", "text.v1"),
                _binding("request_file", "input", "file-ref.v1"),
                _binding("response", "output", "workflow-result.v1"),
            ],
        },
    )
    _write_json(
        source_dir / "template.json",
        {
            "format_id": "amvision.workflow-graph-template.v1",
            "template_id": "workflow-graph-20260101000000",
            "template_version": "1.0.0",
            "display_name": "old",
            "nodes": [],
            "edges": [],
        },
    )
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "format_id": "amvision.workflow-development-baseline.v1",
        "project_id": "project-1",
        "applications": [
            {
                "source_dir": "source",
                "display_name": "正式应用",
                "zeromq_port": 5555,
            }
        ],
    }
    _write_json(manifest_path, manifest)

    plans = build_rebuild_plans(
        manifest=manifest,
        manifest_path=manifest_path,
        start_timestamp="20260831123456",
    )

    assert len(plans) == 1
    plan = plans[0]
    assert plan["application_id"] == "workflow-app-20260831123456"
    assert plan["template_id"] == "workflow-graph-20260831123456"
    assert plan["application"]["template_ref"]["template_id"] == (
        "workflow-graph-20260831123456"
    )
    assert plan["application"]["template_ref"]["source_uri"].endswith(
        "/workflow-graph-20260831123456/versions/1.0.0/template.json"
    )
    input_ids = [
        item["binding_id"]
        for item in plan["application"]["bindings"]
        if item["direction"] == "input"
        and item["binding_id"] in {"request_image_ref", "request_json", "request_text"}
    ]
    assert input_ids == ["request_image_ref", "request_json", "request_text"]


def test_build_rebuild_plans_rejects_source_outside_manifest_root(
    tmp_path: Path,
) -> None:
    """验证 baseline source_dir 不能越过 manifest 所在目录。"""

    manifest_path = tmp_path / "baseline" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest = {
        "format_id": "amvision.workflow-development-baseline.v1",
        "project_id": "project-1",
        "applications": [
            {
                "source_dir": "../outside",
                "display_name": "invalid",
                "zeromq_port": 5555,
            }
        ],
    }

    with pytest.raises(ValueError, match="越过 manifest 目录"):
        build_rebuild_plans(
            manifest=manifest,
            manifest_path=manifest_path,
            start_timestamp="20260831123456",
        )


def _binding(binding_id: str, direction: str, payload_type_id: str) -> dict[str, object]:
    """构造最小 Application binding。"""

    return {
        "binding_id": binding_id,
        "direction": direction,
        "template_port_id": binding_id,
        "binding_kind": "api-request" if direction == "input" else "http-response",
        "required": False,
        "config": {"payload_type_id": payload_type_id},
        "metadata": {},
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    """写入测试 JSON。"""

    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
