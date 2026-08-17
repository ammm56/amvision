"""node pack manifest 强契约测试。"""

from __future__ import annotations

import platform

import pytest
from pydantic import ValidationError

from backend.contracts.nodes.node_pack_manifest import NodePackManifest


def _manifest_payload(**overrides: object) -> dict[str, object]:
    """构造通过强契约校验的最小 manifest。"""

    payload: dict[str, object] = {
        "format_id": "amvision.node-pack-manifest.v1",
        "id": "test.nodes",
        "version": "9.4.1",
        "displayName": "Test Nodes",
        "category": "test",
        "capabilities": ["test.compute"],
        "compatibility": {"api": ">=0.1,<1.0", "runtime": ">=3.12"},
        "timeout": {
            "defaultSeconds": 30,
            "maxSeconds": 60,
            "killGraceSeconds": 2,
        },
    }
    payload.update(overrides)
    return payload


def test_manifest_requires_typed_compatibility_and_timeout_contracts() -> None:
    """验证兼容性和 timeout 契约不能缺失或使用松散字典替代。"""

    for field_name in ("compatibility", "timeout"):
        payload = _manifest_payload()
        payload.pop(field_name)

        with pytest.raises(ValidationError):
            NodePackManifest.model_validate(payload)


def test_manifest_rejects_timeout_default_above_hard_limit() -> None:
    """验证默认 timeout 不得超过节点包硬上限。"""

    with pytest.raises(ValidationError, match="defaultSeconds"):
        NodePackManifest.model_validate(
            _manifest_payload(timeout={"defaultSeconds": 61, "maxSeconds": 60})
        )


def test_manifest_accepts_trusted_integration_capability_without_permission_policy() -> None:
    """验证可信节点包能力不再绑定权限策略字段。"""

    manifest = NodePackManifest.model_validate(
        _manifest_payload(capabilities=["integration.database.sql"])
    )

    assert manifest.capabilities == ("integration.database.sql",)


def test_manifest_reports_current_platform_incompatibilities() -> None:
    """验证 API、Python、OS 与架构不兼容项可供加载器稳定报告。"""

    incompatible_system = "linux" if platform.system().lower() != "linux" else "windows"
    manifest = NodePackManifest.model_validate(
        _manifest_payload(
            compatibility={
                "api": ">=99.0",
                "runtime": ">=99.0",
                "operatingSystems": [incompatible_system],
                "architectures": ["unsupported-architecture"],
            }
        )
    )

    issue_fields = {str(issue["field"]) for issue in manifest.compatibility.current_incompatibilities()}

    assert issue_fields == {"api", "runtime", "operatingSystems", "architectures"}


def test_manifest_version_is_independent_from_backend_version() -> None:
    """验证 node pack 使用自己的 SemVer 生命周期。"""

    manifest = NodePackManifest.model_validate(_manifest_payload(version="99.8.7"))

    assert manifest.version == "99.8.7"
