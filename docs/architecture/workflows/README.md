# Workflow 与节点架构

本目录说明 Workflow 图、Preview、不可变 App 版本、长期 Runtime、Trigger、节点执行和编辑器契约。

## Runtime 与版本

- [Workflow Runtime](runtime.md)
- [Workflow App 版本管理](app-versioning.md)
- [Workflow App 输入契约](app-inputs.md)
- [目录变化 Trigger](directory-watch-trigger.md)
- [本机共享内存 Trigger](local-shared-memory-trigger.md)
- [模型 Session Runtime](model-session-runtime.md)
- [Parallel 分支](parallel-branches.md)
- [视觉并行与模型批量节点设计](vision-parallel-and-model-batch.md)

## 图与编辑器

- [Workflow JSON](json-contracts.md)
- [Workflow 编辑器](editor.md)
- [Preview 实时执行方案](preview-streaming-design.md)：内存会话、逐节点 WebSocket 和正式运行边界，待实现。
- [Preview 实时执行代码实施清单](preview-streaming-implementation.md)：S00–S10 文件范围、固定合约、资源所有权及验收门禁，待实施。
- [参数输入](parameter-inputs.md)
- [说明节点](note-nodes.md)
- [Runtime 显示与 App Mode](runtime-display.md)：Runtime 完成后只读画布与 App Mode 已实现；自动呈现全部 App Entry 公开输入，不实现逐节点进度、强制终止终态、独立应用或页面设计器。
- [Visual Prompt](visual-prompt.md)

- [Preview 内存会话实现与验证记录](preview-streaming-verification.md)

## 节点

- [节点系统](node-system.md)
- [节点分类](node-taxonomy.md)
- [工业视觉与集成节点](industrial-nodes.md)
- [视频节点](video-nodes.md)
- [保存结果保留清理节点](storage-retention-cleanup.md)
- [YOLOE / SAM3 资产](yoloe-sam3-assets.md)

节点包开发规范见 [节点扩展](../../nodes/README.md)，生产操作见 [运维](../../operations/README.md)。
