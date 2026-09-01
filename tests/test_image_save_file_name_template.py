"""Image Save 文件名模板测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.nodes.image_file_name_template import (
    image_media_type_for_file_name,
    render_image_file_name_template,
)
from backend.service.application.errors import InvalidRequestError


def test_render_image_file_name_template_supports_fixed_and_time_text() -> None:
    """验证固定前后缀、自定义分隔和毫秒时间格式。"""

    current_time = datetime(
        2026,
        9,
        1,
        15,
        4,
        5,
        123_999,
        tzinfo=timezone.utc,
    )

    assert (
        render_image_file_name_template(
            "tray_{YYYY-MM-DD_hh-mm-ss-SSS}_OK.png",
            current_time=current_time,
        )
        == "tray_2026-09-01_15-04-05-123_OK.png"
    )
    assert (
        render_image_file_name_template("fixed.jpg", current_time=current_time)
        == "fixed.jpg"
    )


def test_render_image_file_name_template_uses_one_time_for_all_blocks() -> None:
    """验证多个时间块使用同一个已捕获时间点。"""

    current_time = datetime(2026, 9, 1, 15, 4, 5, 7_000, tzinfo=timezone.utc)

    assert (
        render_image_file_name_template(
            "{YYYYMMDD}_{hhmmssSSS}_{node_id}.bmp",
            current_time=current_time,
            context={"node_id": "save-image"},
        )
        == "20260901_150405007_save-image.bmp"
    )


@pytest.mark.parametrize(
    "template",
    [
        "tray_{YYYYMMDD.png",
        "tray_{}.png",
        "tray_{yyyyMMdd}.png",
        "tray_{YYYY/MM/DD}.png",
        "../tray_{YYYYMMDD}.png",
        "CON.png",
        "CON.backup.jpg",
        "tray_{YYYYMMDD}.txt",
    ],
)
def test_render_image_file_name_template_rejects_invalid_values(
    template: str,
) -> None:
    """验证错误时间标记、目录层级和非法文件名都会明确失败。"""

    with pytest.raises(InvalidRequestError):
        render_image_file_name_template(template)


@pytest.mark.parametrize(
    ("file_name", "media_type"),
    [
        ("image.jpg", "image/jpeg"),
        ("image.jpeg", "image/jpeg"),
        ("image.png", "image/png"),
        ("image.bmp", "image/bmp"),
        ("image.webp", "image/webp"),
        ("image.tiff", "image/tiff"),
    ],
)
def test_image_media_type_for_file_name_is_explicit(
    file_name: str,
    media_type: str,
) -> None:
    """验证目标扩展名和媒体类型映射稳定。"""

    assert image_media_type_for_file_name(file_name) == media_type
