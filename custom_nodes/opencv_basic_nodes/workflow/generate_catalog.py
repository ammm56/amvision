"""OpenCV 基础节点目录生成脚本。"""

from __future__ import annotations

from custom_nodes.opencv_basic_nodes.workflow.catalog_builder import write_custom_node_catalog


def main() -> int:
    """执行 catalog 生成步骤。

    返回：
    - int：进程退出码；成功时返回 0。
    """

    write_custom_node_catalog()
    return 0


if __name__ == "__main__":  # pragma: no cover - 脚本入口
    raise SystemExit(main())