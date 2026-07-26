"""生成 OpenCV 统一节点目录。"""

from custom_nodes.opencv_nodes.workflow.catalog_builder import (
    write_custom_node_catalog,
)


if __name__ == "__main__":
    write_custom_node_catalog()
