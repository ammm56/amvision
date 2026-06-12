"""生成 USB / UVC 相机节点包 checked-in catalog.json。"""

from __future__ import annotations

from custom_nodes.camera_usb_uvc_nodes.workflow.catalog_builder import write_custom_node_catalog


def main() -> None:
    """生成并写回 catalog.json。"""

    catalog_path = write_custom_node_catalog()
    print(f"wrote {catalog_path}")


if __name__ == "__main__":
    main()

