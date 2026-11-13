"""B13 真实发布、跨进程 A/B 保存恢复及 Trigger 回收。"""

import pytest

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_dimension_nodes import dimension_documents
from tests.integration.metrology3d.test_published_runtime import invoke_cloud
from tests.test_metrology3d_relations import parameters
from tests.test_point_cloud_trigger import descriptor


def documents(resource=None):
    """复用真实截面及拟线图；关系消费模型，保存节点消费同次完整支持。"""
    (template, app), desc, points = dimension_documents("edge-pair")
    graph = template.model_dump(mode="json")
    node = next(n for n in graph["nodes"] if n["node_id"] == "dimension")
    node["node_type_id"] = "custom.metrology3d.measure-relation"
    node["parameters"] = {
        "settings": parameters("line-line", support_mode="finite").model_dump(
            mode="json"
        )
    }

    def link(a, b, c, d):
        graph["edges"].append(
            dict(
                edge_id=f"relation-{len(graph['edges'])}",
                source_node_id=a,
                source_port=b,
                target_node_id=c,
                target_port=d,
            )
        )

    if resource is None:
        link("filter", "cloud", "dimension", "cloud")
        graph["nodes"].append(
            dict(
                node_id="save",
                node_type_id="custom.metrology3d.save-cloud",
                parameters=dict(
                    mode="derived", target=dict(kind="new", name="Relation support")
                ),
            )
        )
        for port in ("cloud", "features", "evidence"):
            link("dimension", port, "save", port)
    else:
        graph["nodes"] = [
            n for n in graph["nodes"] if n["node_id"] not in {"a", "b", "extract"}
        ]
        graph["edges"] = [
            e
            for e in graph["edges"]
            if e["source_node_id"] not in {"a", "b", "extract"}
            and e["target_node_id"] != "extract"
            and e["edge_id"] != "display"
        ]
        graph["nodes"].append(
            dict(
                node_id="read",
                node_type_id="custom.metrology3d.read-cloud",
                parameters=dict(
                    source=dict(
                        kind="asset", reference=resource.model_dump(mode="json")
                    )
                ),
            )
        )
        for target in ("dimension", "preview"):
            for port in ("cloud", "features"):
                link("read", port, target, port)
    return (
        (WorkflowGraphTemplate.model_validate(graph), app),
        type(descriptor()).model_validate(desc),
        points,
    )


def test_published_relation_saves_generated_support_and_restores_after_stop(tmp_path):
    """原 worker 退出后，新版从持久成员恢复，未复用旧运行权限或拟合节点。"""
    from backend.service.application.workflows.documents.measurement_resources import (
        MeasurementResourceService,
    )
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        LocalDatasetStorage,
        DatasetStorageSettings,
    )

    with published_system(tmp_path) as system:
        doc, desc, points = documents()
        version = system.publish(documents=doc)
        system.start(version)
        generation = system.enable_source(create=True)
        reply = invoke_cloud(system, generation, desc, points.tobytes())
        assert reply["state"] == "succeeded", reply
        item = reply["response_payload"]["results"]["body"]["measurements"]["items"][0]
        assert item["valid"] and item["value"] == pytest.approx(4)
        system.assert_reclaimed()
        service = MeasurementResourceService(
            LocalDatasetStorage(
                DatasetStorageSettings(
                    root_dir=system.settings.dataset_storage.root_dir
                )
            )
        )
        versions = service.list_versions(project_id="project-1")
        assert len(versions) == 1
        resource = versions[0].reference
        saved = service.read(
            resource, project_id="project-1"
        ).content.point_cloud.relation
        assert any(s.kind == "generated" for s in saved.steps)
        stopped = system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        assert stopped["observed_state"] == "stopped"
        system.call("POST", f"/trigger-sources/{system.source_id}/disable")
        next_doc, _, _ = documents(resource)
        next_version = system.publish(documents=next_doc)
        system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/select-version",
            json={"workflow_app_version_id": next_version, "expected_generation": 1},
        )
        system.start()
        generation = system.enable_source(create=False)
        restored = invoke_cloud(system, generation, desc, points.tobytes())
        assert restored["state"] == "succeeded", restored
        item2 = restored["response_payload"]["results"]["body"]["measurements"][
            "items"
        ][0]
        assert item2["valid"] and item2["value"] == pytest.approx(4)
        assert (
            item2["quality"]["metrics"]["observation_id"]
            != item["quality"]["metrics"]["observation_id"]
        )
        system.assert_reclaimed()
