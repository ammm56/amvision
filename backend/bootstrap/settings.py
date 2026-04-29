"""通用 JSON 配置源辅助。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, JsonConfigSettingsSource, PydanticBaseSettingsSource


def build_json_config_sources(
    settings_cls: type[BaseSettings],
    config_files: tuple[Path, ...],
) -> tuple[PydanticBaseSettingsSource, ...]:
    """按给定顺序构建现有 JSON 配置源。

    参数：
    - settings_cls：当前 Settings 类型。
    - config_files：要检查的 JSON 配置文件路径元组；越靠前优先级越高。

    返回：
    - 所有存在的 JSON 配置源元组。
    """

    json_sources: list[PydanticBaseSettingsSource] = []
    for config_file in config_files:
        if not config_file.is_file():
            continue
        json_sources.append(
            JsonConfigSettingsSource(
                settings_cls,
                json_file=config_file,
                json_file_encoding="utf-8",
            )
        )

    return tuple(json_sources)