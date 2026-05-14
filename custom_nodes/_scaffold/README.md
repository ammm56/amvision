# custom_nodes 初始化模板

本目录提供两个可直接复制的 node pack 初始骨架：

- `simple_node_pack`：没有 pack 间依赖的简单节点包模板。
- `dependent_node_pack`：需要声明 `dependencies` 的复杂节点包模板。

使用方式：

1. 复制某个模板目录并重命名为新的 pack 目录。
2. 把 `manifest.template.json` 改名为 `manifest.json`。
3. 把 `workflow/catalog.template.json` 改名为 `workflow/catalog.json`。
4. 根据实际 pack 名称、entrypoint、node_type_id 和依赖项替换模板中的占位符。

本目录故意不放 `manifest.json`，避免被 LocalNodePackLoader 当成真实 node pack 扫描。