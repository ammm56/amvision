"""完整工件的真实发布显示验收；不替换节点、准入、Trigger 或运行进程。"""

import json
import platform
from pathlib import Path
from urllib.parse import urlencode

import pytest

from backend.contracts.workflows.workflow_graph import WorkflowGraphEdge
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.test_published_runtime import (
    sample_array,
    invoke_cloud,
)
from tests.integration.metrology3d.workpiece_workflow import (
    workpiece_documents,
    check_workpiece_body,
)
from tests.point_cloud_support import spatial


def test_complete_cloud_published_measurements_and_datum_display(tmp_path, request):
    """50项数值与完整平面/圆弧显示同次交付，支持数组不走通用小JSON门限。"""
    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("通过 --cloud-sample 显式提供完整样本")
    binary = tmp_path / "cloud.bin"
    cloud = sample_array(Path(sample), binary).model_copy(update={"spatial": spatial()})
    template, application = workpiece_documents(visible=True, inspection="S2")
    template = template.model_copy(
        update={
            "edges": (
                *template.edges,
                *(
                    WorkflowGraphEdge(
                        edge_id="ui-" + node,
                        source_node_id=node,
                        source_port=port,
                        target_node_id="preview",
                        target_port=port,
                    )
                    for node, port in (("D", "features"), ("frame", "pose"))
                ),
            )
        }
    )
    with published_system(
        tmp_path, point_cloud_policy=representative_policy()
    ) as system:
        version = system.publish(point_limit=500_000, documents=(template, application))
        system.start(version)
        generation = system.enable_source(create=True)
        snapshot = system.call(
            "GET", f"/app-runtimes/{system.runtime_id}/preview-snapshot"
        )
        query = urlencode(
            {
                key: snapshot[key]
                for key in (
                    "workflow_runtime_id",
                    "workflow_runtime_revision_id",
                    "runtime_generation",
                    "worker_instance_id",
                )
            }
        )
        with system.client.websocket_connect(
            "/ws/v1/workflows/app-runtimes/preview?" + query, headers=system.headers
        ) as ws:
            assert ws.receive_json()["state"] == "connected"
            reply = invoke_cloud(system, generation, cloud, binary)
            assert reply["state"] == "succeeded", reply
            body = reply["response_payload"]["results"]["body"]
            check_workpiece_body(
                body,
                matrix=Path(__file__).parents[3]
                / "docs/development/assets/r5-f4/workpiece-windows.json",
            )
            frame = ws.receive_json()
            ws.send_text("ready")
            assert frame["state"] == "succeeded" and not frame.get("error"), frame.get(
                "error"
            )
            assert frame["workflow_run_id"] == reply["workflow_run_id"]
            display = next(
                d["payload"]
                for d in frame["displays"]
                if d["payload"]["type"] == "point-cloud-preview"
            )
            assert (
                display["state"] == "ready"
                and display["display_point_count"] == 500_000
            )
            planes = display["geometry"]["planes"]
            assert len(planes) == 1 and len(planes[0]["samples"]["classes"]) == 500_000
            circle = next(
                c for c in display["geometry"]["curves"] if c["kind"] == "circle"
            )
            assert (
                circle["valid"]
                and len(circle["angular_weights"]) == circle["support_point_count"]
            )
        system.assert_reclaimed()
        stopped = system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        assert stopped["observed_state"] == "stopped"
        system.assert_reclaimed()
        report = {
            "platform": platform.platform(),
            "points": cloud.point_count,
            "version_id": version,
            "run_id": reply["workflow_run_id"],
            "display_points": display["display_point_count"],
            "plane_samples": len(planes[0]["samples"]["classes"]),
            "circle_samples": len(circle["angular_weights"]),
            "measurements_match_f4": True,
            "stopped": True,
            "resources_reclaimed": True,
        }
        output = request.config.getoption("--cloud-report-dir")
        if output:
            destination = Path(output)
            destination.mkdir(parents=True, exist_ok=True)
            (
                destination / ("ui-display-" + platform.system().lower() + ".json")
            ).write_text(json.dumps(report, indent=2), encoding="utf-8")


def test_complete_cloud_published_debug_capture(tmp_path, request):
    """三对象同次捕获，正式发布/Trigger/显示传输；数值对照冻结 F4，不改质量。"""
    from backend.contracts.workflows.boundary3d_debug import BoundaryDebugDisplay
    from tests.test_metrology3d_debug_capture import arrays

    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("通过 --cloud-sample 显式提供完整样本")
    binary = tmp_path / "cloud.bin"
    cloud = sample_array(Path(sample), binary).model_copy(update={"spatial": spatial()})
    documents = workpiece_documents(
        visible=True, inspection="S2", debug=("A_top_L", "S1", "S2")
    )
    with published_system(
        tmp_path, point_cloud_policy=representative_policy()
    ) as system:
        version = system.publish(point_limit=500_000, documents=documents)
        system.start(version)
        generation = system.enable_source(create=True)
        snapshot = system.call(
            "GET", f"/app-runtimes/{system.runtime_id}/preview-snapshot"
        )
        query = urlencode(
            {
                key: snapshot[key]
                for key in (
                    "workflow_runtime_id",
                    "workflow_runtime_revision_id",
                    "runtime_generation",
                    "worker_instance_id",
                )
            }
        )
        with system.client.websocket_connect(
            "/ws/v1/workflows/app-runtimes/preview?" + query, headers=system.headers
        ) as ws:
            assert ws.receive_json()["state"] == "connected"
            reply = invoke_cloud(system, generation, cloud, binary)
            assert reply["state"] == "succeeded", reply
            check_workpiece_body(
                reply["response_payload"]["results"]["body"],
                matrix=Path(__file__).parents[3]
                / "docs/development/assets/r5-f4/workpiece-windows.json",
            )
            frame = ws.receive_json()
            ws.send_text("ready")
            assert frame["state"] == "succeeded" and not frame.get("error"), frame
            assert frame["workflow_run_id"] == reply["workflow_run_id"]
            display = next(
                d["payload"]
                for d in frame["displays"]
                if d["payload"]["type"] == "point-cloud-preview"
            )
            assert (
                display["state"] == "ready"
                and display["display_point_count"] == 500_000
            )
            captures = [
                BoundaryDebugDisplay.model_validate(raw)
                for raw in display["boundary_debug"]
            ]
            (tmp_path / "capture-status.json").write_text(
                json.dumps(
                    [c.model_dump(mode="json", exclude={"data"}) for c in captures],
                    indent=2,
                ),
                encoding="utf-8",
            )
            assert {c.identity.node_id for c in captures} == {
                "A_top_L.boundary",
                "S1.boundary",
                "S2.boundary",
            }
            summary = []
            for capture in captures:
                assert capture.state == "ready" and capture.selection_complete, (
                    capture.identity.node_id,
                    capture.state,
                    capture.reason,
                    capture.grid,
                )
                assert capture.identity.run_id == reply["workflow_run_id"]
                fields = arrays(capture)
                if capture.grid:
                    assert (
                        len(fields["counts"])
                        == capture.grid.shape[0] * capture.grid.shape[1]
                    )
                    assert len(fields["bin_rows"]) == len(
                        fields["input_source_indices"]
                    )
                    assert len(fields["profile_offsets"]) == 5
                else:
                    assert (
                        len(fields["candidate_offsets"])
                        == len(fields["candidate_closed"]) + 1
                    )
                summary.append(
                    dict(
                        node=capture.identity.node_id,
                        bytes=capture.data.content_length,
                        fields={
                            key: list(value.shape) for key, value in fields.items()
                        },
                    )
                )
        system.assert_reclaimed()
        assert (
            system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")[
                "observed_state"
            ]
            == "stopped"
        )
        system.assert_reclaimed()
        output = request.config.getoption("--cloud-report-dir")
        if output:
            destination = Path(output)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / ("debug-" + platform.system().lower() + ".json")).write_text(
                json.dumps(
                    dict(
                        platform=platform.platform(),
                        version=version,
                        run=reply["workflow_run_id"],
                        points=cloud.point_count,
                        captures=summary,
                        measurements_match_f4=True,
                        resources_reclaimed=True,
                    ),
                    indent=2,
                ),
                encoding="utf-8",
            )
            # 验收中间正文仅写临时目录，前端解码和历史重开对照后清理。
            (tmp_path / "captured-display.json").write_text(
                json.dumps(display), encoding="utf-8"
            )
