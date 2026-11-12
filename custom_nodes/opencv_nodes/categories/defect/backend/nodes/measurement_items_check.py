"""显式选择一项测量并执行闭区间检查。"""

from .inspection_items import read_records, records, finite_number
from backend.service.application.errors import InvalidRequestError

NODE_TYPE_ID = "custom.opencv.measurement-items-check"


def handle_node(request):
    """未知测量返回 unavailable，不以零代替；每项保留数值、单位、上下限。"""
    p = request.parameters
    metric = p.get("metric")
    check_id = p.get("check_id")
    if (
        not isinstance(metric, str)
        or not metric.strip()
        or not isinstance(check_id, str)
        or not check_id.strip()
    ):
        raise InvalidRequestError("检查必须配置明确的 metric 和 check_id")
    low, high = p.get("minimum"), p.get("maximum")
    if (
        low is None
        and high is None
        or any(v is not None and not finite_number(v) for v in (low, high))
        or low is not None
        and high is not None
        and low > high
    ):
        raise InvalidRequestError("检查必须配置有效的数值上下限")
    items = []
    for key, item in read_records(request.input_values.get("metrics")).items():
        if metric not in item["result"]:
            raise InvalidRequestError("检查字段不存在", details={"metric": metric})
        value = item["result"][metric]
        available = finite_number(value)
        passed = (
            available
            and (low is None or value >= low)
            and (high is None or value <= high)
        )
        items.append(
            {
                "item_id": key,
                "source": item["source"],
                "result": {
                    "check_id": check_id,
                    "metric": metric,
                    "value": value if available else None,
                    "unit": p.get("unit", ""),
                    "minimum": low,
                    "maximum": high,
                    "passed": passed,
                    "state": "pass"
                    if passed
                    else "fail"
                    if available
                    else "unavailable",
                    "measurement": item["result"],
                },
            }
        )
    return {"checks": records(items, "amvision.inspection-check-items.v1")}
