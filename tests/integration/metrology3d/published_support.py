"""隔离真实发布系统；只配置依赖，不替换准入、worker、Broker 或节点 handler。"""

from contextlib import contextmanager
from pathlib import Path
import shutil

from fastapi.testclient import TestClient

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.service.api.app import create_app
from backend.service.application.local_memory import LocalMemorySettings
from backend.service.settings import (
    BackendServiceSettings,
    BackendServiceCustomNodesConfig,
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
    BackendServiceInferenceDaemonConfig,
    BackendServiceWorkflowRuntimeConfig,
)
from custom_nodes._metrology3d_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_document,
)
from tests.api_test_support import create_test_runtime, build_test_headers
from tests.metrology3d_transport_support import cloud_documents
from tests.integration.metrology3d.test_transport_full_sample import full_policy
from tests.integration.metrology3d.published_client import wait_for, broker_settings


def install_test_pack(root: Path):
    """正常生成测试 manifest/Catalog；复制正式源码，不注入测试 handler。"""
    source = Path(__file__).resolve().parents[3] / "custom_nodes/_metrology3d_nodes"
    target = root / "metrology3d_nodes"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    # 仅安装路径改名；测试包所有内部引用仍指向同一份正式实现。
    for path in target.rglob("*.py"):
        path.write_text(
            path.read_text("utf-8").replace(
                "custom_nodes._metrology3d_nodes", "cloud_test_nodes.metrology3d_nodes"
            ),
            encoding="utf-8",
        )
    manifest = NodePackManifest.model_validate(
        dict(
            id="metrology3d.nodes",
            version="0.1.8",
            displayName="3D Metrology test",
            category="vision",
            capabilities=["pipeline.node", "vision.metrology3d"],
            entrypoints={
                "backend": "cloud_test_nodes.metrology3d_nodes.backend.entry:register"
            },
            compatibility={"api": ">=0.1 <1.0", "runtime": ">=3.12"},
            timeout={"defaultSeconds": 180, "maxSeconds": 180, "killGraceSeconds": 2},
            enabledByDefault=True,
            customNodeCatalogPath="workflow/catalog.json",
        )
    )
    (target / "manifest.json").write_text(
        manifest.model_dump_json(by_alias=True), encoding="utf-8"
    )
    (target / "workflow/catalog.json").write_text(
        build_custom_node_catalog_document().model_dump_json(), encoding="utf-8"
    )


class PublishedCloudSystem:
    """通过正式 REST 创建、发布和控制；状态只读用于资源断言。"""

    def __init__(self, client, settings):
        self.client, self.settings = client, settings
        self.headers = build_test_headers(scopes="workflows:read,workflows:write")
        self.base = "/api/v1/workflows"
        self.runtime_id = None
        self.source_id = "cloud-published-source"

    def call(self, method, path, *, status=200, **kwargs):
        """必须校验每一步正式 API 响应，不绕过失败继续执行。"""
        response = self.client.request(
            method, self.base + path, headers=self.headers, **kwargs
        )
        assert response.status_code == status, (
            path,
            response.status_code,
            response.text,
        )
        return response.json() if response.content else None

    def publish(self, point_limit=1000, *, documents=None):
        """以实际草稿指纹发布不可变版本。"""
        template, app = cloud_documents() if documents is None else documents
        for node in template.nodes:
            if node.node_type_id == "custom.metrology3d.cloud-preview":
                node.parameters["point_limit"] = point_limit
        path = f"/projects/project-1/applications/{app.application_id}"
        self.call(
            "PUT",
            path,
            status=201,
            json={
                "application": app.model_dump(mode="json"),
                "template": template.model_dump(mode="json"),
            },
        )
        draft = self.call("GET", path)
        return self.call(
            "POST",
            path + "/versions",
            status=201,
            json={
                "expected_draft_fingerprint": draft["draft_fingerprint"],
                "release_notes": f"Explicit M1 acceptance, points={point_limit}",
            },
        )["workflow_app_version_id"]

    def start(self, version=None):
        """通过真实 worker manager 启动已发布版本。"""
        if self.runtime_id is None:
            self.runtime_id = self.call(
                "POST",
                "/app-runtimes",
                status=201,
                json={
                    "project_id": "project-1",
                    "workflow_app_version_id": version,
                    "display_name": "M1 published acceptance",
                    "request_timeout_seconds": 180,
                },
            )["workflow_runtime_id"]
        return self.call("POST", f"/app-runtimes/{self.runtime_id}/start")

    def enable_source(self, create=False):
        """正式校验输入类型、输出计划和 generation，不直接登记路由。"""
        if create:
            self.call(
                "POST",
                "/trigger-sources",
                status=201,
                json={
                    "trigger_source_id": self.source_id,
                    "project_id": "project-1",
                    "display_name": "M1 cloud source",
                    "trigger_kind": "local-shared-memory",
                    "workflow_runtime_id": self.runtime_id,
                    "submit_mode": "sync",
                    "reply_timeout_seconds": 120,
                    "input_binding_mapping": {
                        "cloud": {"source": "payload.cloud", "required": True}
                    },
                    "result_mapping": {"result_bindings": ["body"]},
                    "default_execution_metadata": {"workflow_run_record_mode": "full"},
                },
            )
        self.call("POST", f"/trigger-sources/{self.source_id}/enable")
        source = self.call("GET", f"/trigger-sources/{self.source_id}")
        return source["metadata"]["trigger_response_plan"]["plan_generation"]

    def idle(self):
        """读取真实 Broker 和 Trigger，确认所有输入所有权和准入已释放。"""
        trigger = (
            self.client.app.state.workflow_trigger_mailbox_supervisor.build_status()
        )
        broker = self.client.app.state.local_buffer_broker_supervisor.get_status()
        return trigger, broker

    def executing(self):
        """只读现有 node-started 记录，不以周期心跳或 REQUEST 推测节点执行。"""
        manager = self.client.app.state.workflow_runtime_worker_manager
        with manager._lock:
            handle = manager._handles[self.runtime_id]
        with handle.state_lock:
            invocation = next(iter(handle.active_node_invocations.values()), None)
            if invocation is not None:
                return {
                    "current_run_id": invocation.workflow_run_id,
                    "process_id": handle.process.pid,
                    "node_id": invocation.node_id,
                    "worker_instance_id": handle.worker_instance_id,
                }
        return None

    def assert_reclaimed(self):
        """ACK/异常退出后最终归零，不把异步回收的中间状态误报为完成。"""

        def reclaimed():
            trigger, broker = self.idle()
            return (
                (trigger, broker)
                if (
                    trigger["pending_request_count"] == 0
                    and trigger["active_task_count"] == 0
                    and trigger["routes"]["active_source_permit_count"] == 0
                    and broker["active_lease_count"] == 0
                    and broker["allocated_capacity_bytes"] == 0
                    and broker["revoking_capacity_bytes"] == 0
                    and broker["quarantined_capacity_bytes"] == 0
                    and broker["free_capacity_bytes"] == broker["arena_total_bytes"]
                )
                else None
            )

        try:
            return wait_for(reclaimed, timeout=15)
        except AssertionError as error:
            raise AssertionError(f"资源未回收: {self.idle()!r}") from error


@contextmanager
def published_system(root):
    """本轮数据库、节点包、共享内存和结果全部位于隔离目录。"""
    packs = root / "cloud_test_nodes"
    install_test_pack(packs)
    sessions, storage, queue = create_test_runtime(root, database_name="published.db")
    settings = BackendServiceSettings(
        database=BackendServiceDatabaseConfig(url=sessions.settings.url),
        dataset_storage=BackendServiceDatasetStorageConfig(
            root_dir=str(storage.root_dir)
        ),
        queue=BackendServiceQueueConfig(root_dir=str(queue.root_dir)),
        custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(packs)),
        local_memory=LocalMemorySettings(root_dir=str(root / "buffers")),
        inference_daemon=BackendServiceInferenceDaemonConfig(runtime_owner="embedded"),
        local_buffer_broker=broker_settings(),
        workflow_runtime=BackendServiceWorkflowRuntimeConfig(
            point_cloud=full_policy(),
            local_shared_trigger_response_ack_timeout_seconds=2,
        ),
    )
    app = create_app(
        settings=settings,
        session_factory=sessions,
        dataset_storage=storage,
        queue_backend=queue,
    )
    try:
        with TestClient(app) as client:
            system = PublishedCloudSystem(client, settings)
            try:
                yield system
            finally:
                if system.runtime_id is not None:
                    system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
    finally:
        sessions.engine.dispose()
