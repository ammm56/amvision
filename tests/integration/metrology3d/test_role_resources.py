"""角色统计不得跨 PID 复用合并，或把不完整采样冒充有效峰值。"""

import json

import pytest

from tests.integration.metrology3d.role_resources import summarize_roles


def test_role_identity_and_incomplete_samples(tmp_path):
    """不同创建时间归属其他进程，丢弃行不污染角色峰值。"""
    path = tmp_path / "resources.jsonl"

    def row(created, rss, wall_time=100):
        return dict(
            pid=1,
            create_time=wall_time,
            birth_identity=f"test:{created}",
            rss_bytes=rss,
            private_bytes=rss,
            handles=2,
            threads=3,
        )

    samples = [
        dict(processes=[row(10, 20)]),
        dict(discarded="child-exited", processes=[row(10, 999)]),
        dict(processes=[row(11, 200)]),
        dict(processes=[row(10, 15, wall_time=99)]),
    ]
    path.write_text("\n".join(json.dumps(s) for s in samples), encoding="utf-8")
    report = summarize_roles(path, {"caller": dict(pid=1, birth_identity="test:10")})
    assert report["roles"]["caller"]["peak"]["rss_bytes"] == 20
    assert report["roles"]["caller"]["last"]["rss_bytes"] == 15
    assert report["roles"]["caller"]["samples"] == 2
    assert len(report["service_support"]) == 1
    with pytest.raises(AssertionError, match="实际采样"):
        summarize_roles(path, {"unseen": dict(pid=2, birth_identity="test:10")})
