"""公开 Python 客户端走真实发布系统，测试目录不参与客户端执行。"""

from concurrent.futures import CancelledError

import numpy as np
import pytest

from runtimes.clients.point_cloud import PointCloudClient, PointCloudCallError
from tests.integration.metrology3d.published_support import published_system
from tests.test_point_cloud_trigger import descriptor


def test_python_client_array_file_rejection_and_release(tmp_path):
    """数组/文件、过期 generation、预取消和错误长度均归还所有权。"""
    with published_system(tmp_path) as system:
        system.start(system.publish())
        generation = system.enable_source(create=True)
        client = PointCloudClient(
            buffers_root=system.settings.local_memory.root_dir,
            broker_settings=system.settings.local_buffer_broker,
        )
        kwargs = dict(
            source_id=system.source_id,
            generation=generation,
            cloud=descriptor(),
            timeout_ms=30000,
        )
        data = np.arange(9, dtype="<f4")
        path = tmp_path / "array.bin"
        path.write_bytes(data.tobytes())
        for content in (memoryview(data), path):
            reply = client.invoke(**kwargs, content=content)
            assert reply["state"] == "succeeded", reply
            system.assert_reclaimed()
        with pytest.raises(ValueError, match="载荷长度"):
            client.invoke(**kwargs, content=b"short")
        with pytest.raises(CancelledError):
            client.invoke(**kwargs, content=data, cancelled=lambda: True)
        calls = 0

        def after_claim():
            """第一次准入前不取消，持有槽位后的第一次等待触发取消。"""
            nonlocal calls
            calls += 1
            return calls >= 2

        with pytest.raises(CancelledError):
            client.invoke(**kwargs, content=data, cancelled=after_claim)
        system.assert_reclaimed()
        with pytest.raises(PointCloudCallError):
            client.invoke(**{**kwargs, "generation": generation + 1}, content=data)
        system.assert_reclaimed()
