"""验证 INT8 失败时记录所有超限校验，并保留最大与平均误差的区分。"""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import onnxruntime as ort
import pytest

from backend.service.application.conversions.runtime.scripts import tensorrt_int8
from backend.service.application.errors import ServiceConfigurationError


def test_int8_reports_all_out_of_tolerance_cases(monkeypatch):
    """两类超限均记录，成功的端点校验也要执行。"""
    profile = ((1, 3, 32, 64), (1, 3, 64, 96), (1, 3, 96, 128))
    expected = np.zeros((1, 5, 20), dtype=np.float32)
    session = SimpleNamespace(
        get_inputs=lambda: [SimpleNamespace(name="images")],
        get_outputs=lambda: [SimpleNamespace(name="predictions")],
        run=lambda *_: [expected],
    )
    monkeypatch.setattr(ort, "InferenceSession", lambda *_, **__: session)
    monkeypatch.setattr(
        tensorrt_int8, "_load_image",
        lambda path, shape: (np.zeros(shape, dtype=np.float32), Path(path).stem),
    )
    original_loader = tensorrt_int8._load_image
    names = []

    def load(path, shape):
        """记录图片名称，返回真实形状的输入张量。"""
        image, name = original_loader(path, shape)
        names.append(name)
        return image

    def execute(*, engine, trt, image):
        """在 opt 注入两种不同的偏差，端点及另一张图保持一致。"""
        actual = expected.copy()
        if image.shape == profile[1] and names[-1] == "maximum":
            actual[0, 0, 3] = 0.3 * profile[1][3]
        if image.shape == profile[1] and names[-1] == "mean":
            actual[:, 4, :] = 0.15
        return {"predictions": actual}

    monkeypatch.setattr(tensorrt_int8, "_load_image", load)
    monkeypatch.setattr(tensorrt_int8, "execute_validation_engine", execute)
    with pytest.raises(ServiceConfigurationError) as raised:
        tensorrt_int8.validate_int8_engine(
            engine=SimpleNamespace(get_tensor_profile_shape=lambda *_: profile),
            trt=object(), source_path=Path("model.onnx"), profile=profile,
            paths=["local/maximum.jpg", "local/mean.jpg", "local/passing.jpg"],
        )
    evidence = raised.value.details["numeric_validation"]
    assert names == ["maximum", "mean", "passing", "maximum", "maximum"]
    assert evidence["sample_count"] == 3
    assert evidence["check_count"] == 5
    maximum, mean = evidence["failures"]
    assert maximum["sample_name"] == "maximum.jpg"
    assert maximum["index"] == [0, 0, 3]
    assert maximum["target_value"] == pytest.approx(0.3)
    assert maximum["mean_error"] == pytest.approx(0.003)
    assert mean["sample_name"] == "mean.jpg"
    assert mean["max_error"] == pytest.approx(0.15)
    assert mean["mean_error"] == pytest.approx(0.03)
