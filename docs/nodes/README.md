# 节点扩展

本目录保存 Node Pack、Custom Node、runtime hook 和节点示例。系统分层见 [节点系统](../architecture/workflows/node-system.md)，Node Catalog 与 Workflow JSON 见 [Workflow JSON](../architecture/workflows/json-contracts.md)。

## 文档

- [Node Pack manifest](node-pack-manifest.md)：manifest、版本、依赖、capability、timeout、启用和兼容范围。
- [Runtime hook 与回调](runtime-hooks-callbacks.md)：Trigger、hook、结果上报和外部调用边界。
- [OpenCV 圆节点](opencv-circle-nodes.md)：Hough Circles、Circle Measure 与四圆角点组合。
- [节点分类](../architecture/workflows/node-taxonomy.md)：Core/Custom 分类、命名和职责。

## 示例

- `examples/example.simple-node-pack.manifest.json`
- `examples/barcode.nodes.manifest.dependency-example.json`
- `custom_nodes/_scaffold/`
- `custom_nodes/hello_world_nodes/`
- `custom_nodes/barcode_nodes/`

## 当前执行模型

- 安装或启用 Node Pack 表示使用者信任其代码。
- Core Node、内置 Node Pack 和第三方 Node Pack 使用同一套进程内直接调用路径。
- 正常节点执行不创建 per-node 隔离进程，也不经过跨进程 RPC。
- manifest 声明版本、依赖、capability、config schema、timeout 与启用状态，不维护 permission scope。
- Workflow Runtime worker、Deployment 常驻进程和后台 Worker 属于服务生命周期边界，不是节点权限沙箱。

外部 HTTP、数据库、PLC、相机和模型调用由对应节点实现连接、超时、取消和错误映射。未经信任的代码需要操作系统级进程或 container 隔离，不通过隐藏的 per-node 兼容路径接入。

## 维护规则

- 节点输入输出与参数由 NodeDefinition 和 Catalog 定义，前端不维护第二套 Python 节点规则。
- `node_type_id`、payload type 和公开字段变化必须同步示例、测试与 Workflow 迁移。
- 场景化协议、硬件桥接和行业规则优先进入 Node Pack，不膨胀核心平台。
- 当前实现不保留已删除节点、旧 schema 或隐藏转发别名。
