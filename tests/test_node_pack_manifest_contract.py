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


def test_manifest_accepts_trusted_integration_capability_without_permission_policy() -> (
    None
):
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

    issue_fields = {
        str(issue["field"])
        for issue in manifest.compatibility.current_incompatibilities()
    }

    assert issue_fields == {"api", "runtime", "operatingSystems", "architectures"}


def test_manifest_version_is_independent_from_backend_version() -> None:
    """验证 node pack 使用自己的 SemVer 生命周期。"""

    manifest = NodePackManifest.model_validate(_manifest_payload(version="99.8.7"))

    assert manifest.version == "99.8.7"


@pytest.mark.parametrize(
    "requirements",
    [
        ["numpy"],
        ["numpy @ https://example.invalid/a.whl"],
        ["numpy[extra]>=2"],
        ["numpy>=2; sys_platform == 'win32'"],
        ["python_neo_lzf==0.3.5", "python-neo-lzf>=0.3"],
        ["!invalid"],
    ],
)
def test_python_requirements_reject_ambiguous_sources(requirements):
    """声明只用于本地版本准入，不触发安装、不允许平台条件悄悄省略检查。"""
    with pytest.raises(ValidationError):
        NodePackManifest.model_validate(
            _manifest_payload(
                compatibility={
                    "api": ">=0.1,<1",
                    "runtime": ">=3.12",
                    "pythonDistributions": requirements,
                }
            )
        )


@pytest.mark.parametrize("actual", [None, "5.1.1", "5.1.1+amvision.2", "broken"])
def test_python_requirements_report_missing_or_uncontrolled_version(
    monkeypatch, actual
):
    """受控本地版本不能由同上游版本冒充；不导入重型数值库。"""
    from backend.contracts.nodes import node_pack_manifest as module

    def version(name):
        assert name == "trimesh"
        if actual is None:
            raise module.PackageNotFoundError(name)
        return actual

    monkeypatch.setattr(module, "distribution_version", version)
    manifest = NodePackManifest.model_validate(
        _manifest_payload(
            compatibility={
                "api": ">=0.1,<1",
                "runtime": ">=3.12",
                "pythonDistributions": ["trimesh==5.1.1+amvision.2"],
            }
        )
    )
    issues = manifest.compatibility.current_incompatibilities()
    assert issues == (
        ()
        if actual == "5.1.1+amvision.2"
        else (
            {
                "field": "pythonDistributions",
                "distribution": "trimesh",
                "required": "==5.1.1+amvision.2",
                "actual": actual,
            },
        )
    )
