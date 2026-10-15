"""业务精度报告按语义类别计分，不能隐式猜测类别索引。"""

import pytest

from tests.integration.classification_acceptance import classification_metrics


def test_classification_metrics_include_missing_class_and_uncertainty() -> None:
    """缺少样本的类别不能显示为满分；小样本须有可信区间下界。"""
    report = classification_metrics([
        {"expected":"ok", "predicted":"ok"}, {"expected":"ng", "predicted":"ok"},
    ], ["ng", "ok", "empty"])
    assert report["accuracy"] == .5
    assert report["per_class"]["ng"]["recall"] == 0
    assert report["per_class"]["empty"]["recall"] is None
    assert 0 < report["accuracy_wilson_95_lower"] < .5


@pytest.mark.parametrize("records", [[], [{"expected":"unknown", "predicted":"ok"}],
                                      [{"expected":"ok", "predicted":"unknown"}]])
def test_classification_metrics_reject_invalid_inputs(records) -> None:
    """空样本或未声明类别必须拒绝，不能当成零错误率。"""
    with pytest.raises(ValueError):
        classification_metrics(records, ["ok"])
