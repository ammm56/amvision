"""显示颜色与尺寸的白名单校验，不接收任意 CSS。"""

import re

from backend.service.application.runtime.io.jsonl import fail

COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
STATE_PRESETS = ("success", "danger", "warning", "neutral")
APPEARANCE_LIMITS = {
    "panel_width": (100, 1600, None),
    "panel_height": (80, 1200, None),
    "font_size": (10, 72, 13),
    "status_font_size": (10, 120, 20),
    "background_opacity": (0, 100, 78),
}
APPEARANCE_SCHEMA = {
    "type": "object", "title": "Appearance", "x-ui-widget": "display-appearance",
    "additionalProperties": False,
    "properties": {
        **{key: {"type": ["integer", "null"] if default is None else "integer",
                 "minimum": lo, "maximum": hi, "default": default}
           for key, (lo, hi, default) in APPEARANCE_LIMITS.items()},
        "background_color": {"type": ["string", "null"], "pattern": COLOR_PATTERN},
    },
}


def display_color(value: object, *, presets: bool = False) -> str | None:
    """返回规范色值；空值表示主题默认，状态允许沿用语义预设。"""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise fail("显示颜色必须为 #RRGGBB")
    if presets and value in STATE_PRESETS:
        return value
    if not re.fullmatch(COLOR_PATTERN, value):
        raise fail("显示颜色必须为 #RRGGBB")
    return value.upper()


def display_appearance(value: object) -> dict:
    """只输出显式配置；旧节点不产生额外默认参数。"""
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {*APPEARANCE_LIMITS, "background_color"}:
        raise fail("Appearance 配置无效")
    output = {}
    for key, raw in value.items():
        if key == "background_color":
            output[key] = display_color(raw)
            continue
        lo, hi, default = APPEARANCE_LIMITS[key]
        if raw is None and default is None:
            output[key] = None
        elif type(raw) is not int or not lo <= raw <= hi:
            raise fail(f"{key} 必须为 {lo}–{hi} 的整数")
        else:
            output[key] = raw
    return output
