"""由共享契约生成正式目录，与其他节点包使用相同生成方式。"""

from pathlib import Path

from custom_nodes.metrology3d_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_document,
)


def write_custom_node_catalog():
    """固定生成本包 Catalog，不写 manifest、用户配置或运行数据。"""
    path = Path(__file__).with_name("catalog.json")
    path.write_text(
        build_custom_node_catalog_document().model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_custom_node_catalog()
