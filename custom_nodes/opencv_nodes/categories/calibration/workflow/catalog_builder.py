"""OpenCV 标定节点目录生成器。"""

from __future__ import annotations

from pathlib import Path

from custom_nodes.opencv_nodes.categories.basic.workflow.catalog_builder import (
    build_custom_node_catalog_document as _build_document,
    build_custom_node_catalog_payload as _build_payload,
    write_custom_node_catalog as _write_catalog,
)


def get_workflow_dir() -> Path:
    """返回 OpenCV 标定节点 workflow 目录。"""

    return Path(__file__).resolve().parent


def build_custom_node_catalog_document(*, workflow_dir: Path | None = None):
    """构造 OpenCV 标定节点目录文档。"""

    return _build_document(workflow_dir=workflow_dir or get_workflow_dir())


def build_custom_node_catalog_payload(*, workflow_dir: Path | None = None) -> dict[str, object]:
    """构造 OpenCV 标定节点目录 JSON。"""

    return _build_payload(workflow_dir=workflow_dir or get_workflow_dir())


def write_custom_node_catalog(*, workflow_dir: Path | None = None) -> Path:
    """写入 OpenCV 标定节点目录 JSON。"""

    return _write_catalog(workflow_dir=workflow_dir or get_workflow_dir())
