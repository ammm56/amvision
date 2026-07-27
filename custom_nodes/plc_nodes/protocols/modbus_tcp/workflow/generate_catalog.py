"""生成 PLC Modbus TCP checked-in catalog.json。"""

from __future__ import annotations

from custom_nodes.plc_nodes.protocols.modbus_tcp.workflow.catalog_builder import (
    write_custom_node_catalog,
)


def main() -> None:
    """生成并写回 catalog.json。"""

    catalog_path = write_custom_node_catalog()
    print(f"wrote {catalog_path}")


if __name__ == "__main__":
    main()
