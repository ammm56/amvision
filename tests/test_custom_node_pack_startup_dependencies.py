"""custom node pack 依赖与启动链测试。"""

from __future__ import annotations

from pathlib import Path

from tests.api_test_support import build_test_headers, create_api_test_context


def test_workflow_node_catalog_loads_barcode_display_pack_when_dependencies_are_available(
    tmp_path: Path,
) -> None:
    """验证 API 启动链会加载满足依赖的 barcode.display-nodes。

    参数：
    - tmp_path：pytest 提供的临时目录。
    """

    context = create_api_test_context(
        tmp_path,
        database_name="custom-node-pack-startup.db",
    )
    headers = build_test_headers(scopes="workflows:read")

    try:
        with context.client:
            response = context.client.get(
                "/api/v1/workflows/node-catalog",
                params={"node_pack_id": "barcode.display-nodes"},
                headers=headers,
            )
    finally:
        context.session_factory.engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["node_pack_manifests"]] == ["barcode.display-nodes"]
    assert any(item["node_type_id"] == "custom.barcode.display-response" for item in payload["node_definitions"])
    assert any(
        group["category"] == "barcode.display"
        and any(node_item["node_type_id"] == "custom.barcode.display-response" for node_item in group["node_definitions"])
        for group in payload["palette_groups"]
    )