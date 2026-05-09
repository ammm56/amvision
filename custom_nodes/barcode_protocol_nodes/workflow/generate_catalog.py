"""生成 Barcode/QR 节点包 catalog.json。"""

from __future__ import annotations

from custom_nodes.barcode_protocol_nodes.workflow.catalog_builder import write_custom_node_catalog


def main() -> None:
    """把 workflow/catalog_sources 数据汇总写入 catalog.json。"""

    write_custom_node_catalog()


if __name__ == "__main__":
    main()
