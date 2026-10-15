"""TensorRT 多输出 pinned 资源统计的跨平台契约验证，不调用 CUDA。"""

from types import SimpleNamespace
import importlib

import pytest

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.runtime.deployment.deployment_runtime_pool import DeploymentRuntimePool
from backend.service.application.runtime.predictors.yolo11.segmentation.tensorrt import TensorRTYolo11SegmentationRuntimeSession
from backend.service.application.runtime.predictors.yolo26.segmentation.tensorrt import TensorRTYolo26SegmentationRuntimeSession
from backend.service.application.runtime.predictors.yolov8.segmentation.tensorrt import TensorRTYoloV8SegmentationRuntimeSession


@pytest.mark.parametrize("session_type", [TensorRTYoloV8SegmentationRuntimeSession,
                                         TensorRTYolo11SegmentationRuntimeSession,
                                         TensorRTYolo26SegmentationRuntimeSession])
@pytest.mark.parametrize("prediction_pinned,proto_pinned", [(True, True), (True, False), (False, True), (False, False)])
def test_segmentation_memory_reports_all_live_output_capacities(session_type, prediction_pinned, proto_pinned):
    """总 pinned 容量包含两个输出，不能以 tensor 当前大小或单一 memory kind 代替。"""
    session = object.__new__(session_type)
    session._closed = True
    session.pinned_output_buffer_enabled = True
    session.pinned_output_buffer_max_bytes = 4096
    session.prediction_host_array = SimpleNamespace(nbytes=100)
    session.prediction_host_memory_kind = "pinned" if prediction_pinned else "pageable"
    session.prediction_host_ptr = 1 if prediction_pinned else None
    session.prediction_host_capacity_bytes = 256
    session.proto_host_array = SimpleNamespace(nbytes=200)
    session.proto_host_memory_kind = "pinned" if proto_pinned else "pageable"
    session.proto_host_ptr = 2 if proto_pinned else None
    session.proto_host_capacity_bytes = 512
    expected = (256 if prediction_pinned else 0) + (512 if proto_pinned else 0)
    snapshot = session.describe_memory_usage()
    assert snapshot["output_host_buffer_bytes"] == 300
    assert snapshot["output_host_pinned_bytes"] == expected
    assert snapshot["prediction_host_pinned_bytes"] + snapshot["proto_host_pinned_bytes"] == expected
    assert DeploymentRuntimePool._read_session_pinned_output_bytes(session) == expected
    session.prediction_host_array = session.proto_host_array = None
    session.prediction_host_ptr = session.proto_host_ptr = None
    # 指针已经释放时，即使旧 capacity 尚未归零，也不能计入当前持有资源。
    assert session.describe_memory_usage()["output_host_pinned_bytes"] == 0
    assert session.describe_memory_usage()["output_host_buffer_bytes"] == 0


@pytest.mark.parametrize("kind", ["pinned", "pageable", "mixed"])
def test_pool_uses_explicit_total_not_single_output_memory_kind(kind):
    """汇总字段是权威总量，多输出混合内存不能被筛选为零。"""
    session = SimpleNamespace(describe_memory_usage=lambda: {
        "output_host_memory_kind": kind, "output_host_pinned_bytes": 512})
    assert DeploymentRuntimePool._read_session_pinned_output_bytes(session) == 512


@pytest.mark.parametrize("snapshot", [None, [], {}, {"output_host_pinned_bytes": -1},
                                     {"output_host_pinned_bytes": True}, {"output_host_pinned_bytes": 1.5},
                                     {"output_host_pinned_bytes": "1024"}])
def test_invalid_memory_snapshot_is_not_reported_as_zero(snapshot):
    """明确提供资源观测的 session 必须满足计数契约，不能静默报告为零。"""
    session = SimpleNamespace(describe_memory_usage=lambda: snapshot)
    with pytest.raises(ServiceConfigurationError):
        DeploymentRuntimePool._read_session_pinned_output_bytes(session)


def test_memory_observer_failure_is_not_reported_as_zero():
    """资源读取失败应保留失败状态，而不是伪造健康的空资源。"""
    def broken():
        raise OSError("controlled observation failure")
    with pytest.raises(ServiceConfigurationError) as captured:
        DeploymentRuntimePool._read_session_pinned_output_bytes(SimpleNamespace(describe_memory_usage=broken))
    assert isinstance(captured.value.__cause__, OSError)


def test_session_without_managed_host_outputs_has_no_pinned_output():
    """未加载或不提供常驻 host output 的 runtime 保持零占用语义。"""
    assert DeploymentRuntimePool._read_session_pinned_output_bytes(None) == 0
    assert DeploymentRuntimePool._read_session_pinned_output_bytes(object()) == 0


@pytest.mark.parametrize("model_task", ["yolox", *(
    f"{family}.{task}" for family in ("yolov8", "yolo11", "yolo26")
    for task in ("detection", "classification", "segmentation", "pose", "obb"))])
@pytest.mark.parametrize("pinned", [True, False])
def test_all_managed_tensorrt_output_reporters_share_the_total_contract(model_task, pinned):
    """全部 16 种常驻输出 session 使用同一总量契约，释放后归零。"""
    module = importlib.import_module(f"backend.service.application.runtime.predictors.{model_task}.tensorrt")
    classes = [value for value in vars(module).values() if isinstance(value, type)
               and value.__module__ == module.__name__ and "describe_memory_usage" in vars(value)]
    assert len(classes) == 1
    session = object.__new__(classes[0])
    session._closed = True
    session.pinned_output_buffer_enabled = True
    session.pinned_output_buffer_max_bytes = 4096
    names = ("prediction", "proto") if model_task.endswith(".segmentation") else ("output",)
    for name in names:
        setattr(session, f"{name}_host_array", SimpleNamespace(nbytes=100))
        setattr(session, f"{name}_host_memory_kind", "pinned" if pinned else "pageable")
        setattr(session, f"{name}_host_ptr", 1 if pinned else None)
        setattr(session, f"{name}_host_capacity_bytes", 256)
    assert DeploymentRuntimePool._read_session_pinned_output_bytes(session) == (256 * len(names) if pinned else 0)
    for name in names:
        setattr(session, f"{name}_host_ptr", None)
        setattr(session, f"{name}_host_array", None)
    assert DeploymentRuntimePool._read_session_pinned_output_bytes(session) == 0
