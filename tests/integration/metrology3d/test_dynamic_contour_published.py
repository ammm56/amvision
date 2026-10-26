"""R5 C 正式发布、独立 Runtime、Trigger 和继承尺寸组合验收。"""

import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.published_client import invoke_cloud
from tests.metrology3d_transport_support import cloud_documents
from tests.test_metrology3d_dynamic_contour import fixture, inherited
from tests.test_metrology3d_boundary_contracts import line_parameters
from tests.test_metrology3d_dimension_contracts import extent_parameters
from tests.test_metrology3d_edge_pair import pair_parameters
from tests.test_metrology3d_measurement_contracts import step_parameters
from tests.test_metrology3d_pose_query import query
from tests.test_point_cloud_trigger import descriptor
from tests.integration.metrology3d.test_transport_full_sample import full_policy


def documents():
    """公开图连线复用真实参数；解析预期由测试中的独立数值给出。"""
    values, contour, _ = fixture(np.float32)
    scope, runtime, cloud, groups, _, frame, rotation, origin = values
    try:
        with runtime.borrow(cloud) as view:
            points = np.vstack(
                [
                    view.chunk(
                        i, min(i + runtime.policy.chunk_rows, cloud.point_count)
                    )["positions"].copy()
                    for i in range(0, cloud.point_count, runtime.policy.chunk_rows)
                ]
            )
        template, app = cloud_documents()
        raw = template.model_dump(mode="json")

        def node(name, kind, **parameters):
            raw["nodes"].append(
                dict(
                    node_id=name,
                    node_type_id="custom.metrology3d." + kind,
                    parameters=parameters,
                )
            )

        def link(a, b, c, d):
            raw["edges"].append(
                dict(
                    edge_id=f"c-{len(raw['edges'])}",
                    source_node_id=a,
                    source_port=b,
                    target_node_id=c,
                    target_port=d,
                )
            )

        for group, z in zip(groups, (0, 5)):
            plane = group.items[0]
            name = plane.feature_id
            roi = dict(
                roi_id=name,
                frame_id="fixture",
                length_unit="mm",
                kind="box",
                geometry=dict(
                    center=(origin + rotation @ [0, 0, z]).tolist(),
                    size=[6, 6, 2],
                    rotation=rotation.tolist(),
                ),
            )
            node(name + "-crop", "crop-roi", source=dict(kind="parameters", roi=roi))
            node(
                name,
                "fit-plane",
                settings={
                    **plane.method.parameters.model_dump(mode="json"),
                    "quality_policy": plane.method.quality_policy.model_dump(
                        mode="json"
                    ),
                },
            )
            link("filter", "cloud", name + "-crop", "cloud")
            link(name + "-crop", "cloud", name, "cloud")
            link(name, "features", "step", "features")
            link(name, "features", "extract", "features")
        node("frame", "build-frame", settings=frame.model_dump(mode="json"))
        link("reference", "features", "frame", "features")
        node(
            "step",
            "measure-step",
            settings=step_parameters(query=query()).model_dump(mode="json"),
        )
        node("extract", "extract-boundary", settings=contour.model_dump(mode="json"))
        link("frame", "pose", "step", "pose")
        link("frame", "pose", "extract", "pose")
        link("step", "evidence", "extract", "evidence")
        link("filter", "cloud", "extract", "cloud")
        link("extract", "features", "preview", "features")
        for name in ("left", "right"):
            node(
                name,
                "fit-line",
                settings=line_parameters(
                    feature_id=name,
                    selection=dict(feature_id="boundary", segment_ids=[name]),
                    evaluation=inherited(),
                    positive_direction=dict(kind="axis", axis="v"),
                ).model_dump(mode="json"),
            )
            link("extract", "features", name, "features")
            link(name, "features", "pair", "features")
            link(name, "features", "preview", "features")
        node(
            "pair",
            "measure-edge-pair",
            settings=pair_parameters(
                reference_feature_id="left",
                target_feature_id="right",
                evaluation=inherited(),
                query_position=dict(kind="plane-uv", uv=[0, 0]),
                direction=dict(kind="axis", axis="u"),
            ).model_dump(mode="json"),
        )
        node(
            "extent",
            "measure-extents",
            settings=extent_parameters(
                evaluation=inherited(),
                source=dict(
                    kind="boundary",
                    selection=dict(
                        feature_id="boundary", segment_ids=["left", "right"]
                    ),
                ),
            ).model_dump(mode="json"),
        )
        link("extract", "features", "extent", "features")
        for name in ("step", "pair", "extent"):
            link(name, "evidence", "preview", "evidence")
        desc = descriptor().model_dump(mode="json")
        desc.update(
            point_count=len(points),
            content_length=points.nbytes,
            spatial=cloud.spatial.model_dump(mode="json"),
        )
        desc["fields"][0].update(count=len(points), byte_length=points.nbytes)
        return (WorkflowGraphTemplate.model_validate(raw), app), desc, points
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_published_dynamic_source_inheritance_and_release(tmp_path):
    """每次均走发布版本和正式 Trigger；旧观测不得被第二次调用复用。"""
    definition, cloud, points = documents()
    observations = []
    configured = full_policy()
    configured = configured.model_copy(
        update={
            "preview": configured.preview.model_copy(
                update={
                    "max_body_bytes": 4 * 1024 * 1024,
                    "max_working_bytes": 16 * 1024 * 1024,
                }
            )
        }
    )
    with published_system(tmp_path, point_cloud_policy=configured) as system:
        version = system.publish(documents=definition)
        runtime = system.start(version)
        generation = system.enable_source(create=True)
        for _ in range(2):
            reply = invoke_cloud(
                system.settings.local_memory.root_dir,
                system.source_id,
                generation,
                cloud,
                points.tobytes(),
            )
            assert reply["state"] == "succeeded", reply
            body = reply["response_payload"]["results"]["body"]
            assert body["state"] == "ready", body
            contour = next(
                c for c in body["geometry"]["curves"] if c["kind"] == "boundary"
            )
            assert contour["valid"], contour
            assert contour["method"]["resolution"]["height"] == pytest.approx(
                2.525, abs=4e-6
            )
            assert (
                contour["method"]["resolution"]["observation_id"]
                == body["observation_id"]
            )
            items = body["measurements"]["items"]
            assert all(i["valid"] for i in items), items
            assert sorted(i["value"] for i in items) == pytest.approx(
                [4, 5.05, 10, 10], abs=4e-6
            )
            run = system.call(
                "GET", f"/runs/{reply['workflow_run_id']}?response_mode=run"
            )
            assert (
                run["workflow_app_version_id"] == version
                and run["worker_instance_id"] == runtime["worker_instance_id"]
            )
            observations.append(body["observation_id"])
            system.assert_reclaimed()
    assert len(set(observations)) == 2
