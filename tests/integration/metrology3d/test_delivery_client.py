"""搬移后的正式同机入口连接真实发布 Runtime，不替换 Trigger 准入。"""

import json

import numpy as np

from tests.integration.metrology3d.published_support import published_system
from tests.test_point_cloud_delivery import delivered_tools, invoke_tools
from tests.test_point_cloud_trigger import descriptor

__all__ = ["delivered_tools"]


def test_packaged_cli_uses_target_config_and_reclaims(delivered_tools, tmp_path):
    """发行客户端使用目标配置，成功/过期路由/坏长度均无残留。"""
    with published_system(tmp_path / "service") as system:
        system.start(system.publish())
        generation = system.enable_source(create=True)
        config = delivered_tools / "config/backend-service.json"
        config.write_text(system.settings.model_dump_json(), encoding="utf-8")
        try:
            cloud = tmp_path / "cloud.json"
            array = tmp_path / "cloud.bin"
            cloud.write_text(descriptor().model_dump_json(), encoding="utf-8")
            array.write_bytes(np.arange(9, dtype="<f4").tobytes())
            args = [
                "--descriptor",
                str(cloud),
                "--array",
                str(array),
                "--source",
                system.source_id,
                "--generation",
                str(generation),
                "--timeout-ms",
                "30000",
            ]
            result = invoke_tools(delivered_tools, "invoke", args, cwd=tmp_path)
            assert result.returncode == 0, (result.stdout, result.stderr)
            assert json.loads(result.stdout)["state"] == "succeeded"
            system.assert_reclaimed()
            stale = args.copy()
            stale[stale.index("--generation") + 1] = str(generation + 1)
            result = invoke_tools(delivered_tools, "invoke", stale, cwd=tmp_path)
            assert result.returncode != 0 and "PointCloudCallError" in result.stderr
            system.assert_reclaimed()
            array.write_bytes(b"short")
            result = invoke_tools(delivered_tools, "invoke", args, cwd=tmp_path)
            assert result.returncode != 0 and "载荷长度" in result.stderr
            system.assert_reclaimed()
        finally:
            config.unlink()
