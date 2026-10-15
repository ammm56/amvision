"""验证稳定窗口资源观测不会把缺失设备或停止后的资源释放计为通过。"""
from tests.integration.acceptance_resource_observations import ResourceObservations


def test_storage_growth_keeps_peak_and_excludes_prepare(tmp_path):
    """准备阶段大文件不进入基线，测量超限随后删除仍失败。"""
    logs = tmp_path / "logs"
    logs.mkdir()
    file = logs / "worker.log"
    file.write_bytes(b"x" * 100)
    observer = ResourceObservations(tmp_path, None, limits={"storage.log_bytes": 20})
    observer.sample()
    assert observer.summary()["status"] == "incomplete"
    file.write_bytes(b"x" * 10)
    observer.previous_storage_at = -60
    observer.sample(measure=True)
    file.write_bytes(b"x" * 40)
    observer.previous_storage_at = -60
    observer.sample(measure=True)
    file.unlink()
    observer.previous_storage_at = -60
    observer.sample(measure=True)
    assert observer.summary()["status"] == "failed"
    assert observer.summary()["first"]["storage"]["log_bytes"] == 10
    assert observer.summary()["peak"]["storage"]["log_bytes"] == 40


def test_missing_gpu_is_not_zero_or_passed(tmp_path):
    """显式要求 GPU 时，采样不可用必须拒绝整体通过。"""
    observer = ResourceObservations(tmp_path, None)
    observer.gpu_index = 0
    observer.gpu_error = "device unavailable"
    sample = observer.sample(measure=True)
    assert sample["gpu"]["status"] == "unavailable"
    assert "used_bytes" not in sample["gpu"]
    assert observer.summary()["status"] == "failed"
