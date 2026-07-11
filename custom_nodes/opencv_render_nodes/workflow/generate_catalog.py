"""OpenCV 渲染节点目录生成脚本。"""

from __future__ import annotations

from custom_nodes.opencv_render_nodes.workflow.catalog_builder import write_custom_node_catalog


def main() -> int:
    """执行 catalog 生成步骤。"""

    write_custom_node_catalog()
    return 0


if __name__ == "__main__":  # pragma: no cover - 脚本入口
    raise SystemExit(main())
