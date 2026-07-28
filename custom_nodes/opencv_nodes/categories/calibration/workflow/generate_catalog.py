"""生成 OpenCV 标定节点目录。"""

from __future__ import annotations

from custom_nodes.opencv_nodes.categories.calibration.workflow.catalog_builder import (
    write_custom_node_catalog,
)


if __name__ == "__main__":
    write_custom_node_catalog()
