"""生成 HTTP 统一节点目录。"""

from custom_nodes.http_nodes.workflow.catalog_builder import (
    write_custom_node_catalog,
)


if __name__ == "__main__":
    print(write_custom_node_catalog())
