# Workflow 节点组

节点组是 Workflow 编辑器中的布局和批量状态工具。它保存在 `amvision.workflow-graph-template.v1` 的 `groups` 字段中，不改变边的连接关系，也不引入新的 Runtime 调度层。

## 数据结构

每个组包含：

- `group_id`
- `name`
- `enabled`
- `rect`
- `member_node_ids`
- `membership_policy = full-containment`
- `color`
- `collapsed`
- `locked`
- `metadata`

类型定义位于 `frontend/web-ui/src/workflows/workflow-editor/types.ts`。

## 当前行为

- 在画布拖出矩形创建组。
- 节点完全位于组矩形内时成为成员。
- 移动组会批量移动成员节点。
- 锁定组后禁止拖动和 resize。
- 启用/禁用组会批量更新成员节点状态。
- 组名称和颜色可编辑，删除组不删除节点。
- 文档加载、保存和 preflight 会校验组 id、尺寸、成员存在性和重复成员。

主要代码：

- `frontend/web-ui/src/workflows/workflow-editor/components/WorkflowGraphGroupLayer.vue`
- `frontend/web-ui/src/workflows/workflow-editor/graph/useWorkflowGraphGroups.ts`
- `frontend/web-ui/src/workflows/workflow-editor/validation/useWorkflowPreflight.ts`
- `frontend/web-ui/src/workflows/workflow-editor/documents/useWorkflowDocumentBuilder.ts`

## Runtime 边界

Runtime 只执行节点的最终 `enabled` 状态。组的矩形、颜色、折叠和锁定属于编辑器元数据，不创建子图、线程池、事务或隔离进程。Parallel/For Each 的执行语义仍由对应节点定义。

## 验收

- 创建、移动、resize、锁定、改名、改色和删除保持文档可往返。
- 移动组时成员相对位置不变，非成员不移动。
- 禁用组后 Runtime 跳过成员节点；重新启用后恢复。
- 删除组不删除节点、边或节点参数。
- 重叠组和不存在的成员在 preflight 中给出明确错误或按规范化规则处理。
