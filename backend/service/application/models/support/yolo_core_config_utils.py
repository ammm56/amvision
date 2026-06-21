"""YOLO core 配置辅助函数。"""

from __future__ import annotations

from copy import deepcopy

from backend.service.application.errors import InvalidRequestError


def clone_detection_variant(
    base_config: dict[str, object],
    *,
    head_module_name: str,
    head_args: tuple[object, ...],
    top_level_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """基于 detection 配置克隆一个仅替换任务头的变体。"""

    config = deepcopy(base_config)
    if top_level_overrides:
        config.update(top_level_overrides)
    head_layers = list(config.get("head") or [])
    if not head_layers:
        raise InvalidRequestError("YOLO core 配置缺少 head")
    raw_last_layer = head_layers[-1]
    if not isinstance(raw_last_layer, tuple | list) or len(raw_last_layer) != 4:
        raise InvalidRequestError("YOLO core 配置的末层定义不合法")
    head_layers[-1] = (raw_last_layer[0], raw_last_layer[1], head_module_name, head_args)
    config["head"] = head_layers
    return config
