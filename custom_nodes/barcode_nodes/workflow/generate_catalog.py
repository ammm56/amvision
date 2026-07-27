"""生成 Barcode 统一节点目录。"""

from custom_nodes.barcode_nodes.workflow.catalog_builder import (
    write_custom_node_catalog,
)


if __name__ == "__main__":
    print(write_custom_node_catalog())
