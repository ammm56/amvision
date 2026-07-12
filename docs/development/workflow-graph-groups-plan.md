# Workflow 节点组规划

本文档固定 workflow editor 中节点组的目标、边界、数据结构和实现顺序。节点组用于提升 workflow node app 编辑和调试效率，尤其适合 `workflow-app-20260710212239` 这类包含多个验证分支的图。节点组不属于 workflow runtime 节点，不进入生产执行链路。

## 目标

- 在画布中创建可调整大小的组框，用于管理一批节点。
- 组框左上角显示名称、状态和成员数量。
- 可以直接拖动节点进入或移出组框。
- 节点必须完整位于组框中才算加入组。
- 拖动组框时，组内节点跟随整体移动。
- 启用或禁用组时，批量启用或禁用组内节点。
- 支持调试分支快速切换，减少逐个节点点击启用或禁用的操作。

## 硬边界

节点组是 workflow editor artifact，不是 workflow runtime node。

节点组不应：

- 注册为 `NodeDefinition`。
- 出现在 node catalog 或节点面板中。
- 拥有输入端口、输出端口或 payload。
- 参与 DAG 拓扑排序。
- 参与 `graph_executor` 的节点执行。
- 产生 node record。
- 影响 BGR24、BufferRef、FrameRef、image-ref 等生产高性能数据链路。
- 增加 WorkflowAppRuntime、TriggerSource 或高帧率调用的固定开销。

节点组可以：

- 保存到 `WorkflowGraphTemplate.groups`。
- 在前端画布中显示、选择、拖动、调整大小和改名。
- 作为编辑器批量操作入口，统一写入成员节点已有的 `enabled` 字段。
- 在后端模板校验中被校验结构和成员引用，但不被当作运行节点执行。

## 三层职责

### 编辑器层

编辑器层负责节点组的全部交互：

- 创建组。
- 调整组框尺寸。
- 拖动节点加入或移出组。
- 拖动组并同步移动成员节点。
- 修改组名称、颜色、锁定状态和启用状态。
- 显示全部启用、全部禁用、部分启用三态。

### 模板归一层

保存或 Preview Run 前，前端应把组启用状态归一到成员节点：

- 组禁用时，成员节点写为 `enabled=false`。
- 组启用时，成员节点写为 `enabled=true`。
- 组内节点状态不一致时，前端显示部分启用，不把部分状态作为 runtime 状态。

后端可以在模板校验或执行 snapshot 固定前做防御性检查，避免 `groups` 与节点 `enabled` 状态明显漂移。但执行器最终仍只依赖节点自身的 `enabled`。

### Runtime 执行层

Runtime 执行层只读取普通节点、连线、公开输入输出和节点 `enabled` 状态。Runtime 不解析节点组，不为节点组创建任何执行对象。

## 数据结构

建议在 `WorkflowGraphTemplate` 中新增 `groups`：

```json
{
  "groups": [
    {
      "group_id": "group-contour-branch",
      "name": "Contour 验证分支",
      "enabled": true,
      "rect": {
        "x": 100,
        "y": 120,
        "width": 900,
        "height": 520
      },
      "member_node_ids": [
        "contour_detect",
        "contour_filter",
        "min_area_rect"
      ],
      "membership_policy": "full-containment",
      "color": "#22b8cf",
      "collapsed": false,
      "locked": false,
      "metadata": {}
    }
  ]
}
```

字段说明：

- `group_id`：模板内唯一的组 id。
- `name`：组显示名称。
- `enabled`：组的目标批量启用状态。
- `rect`：组框在画布世界坐标中的位置和尺寸。
- `member_node_ids`：组成员节点 id 列表，是保存后的权威成员关系。
- `membership_policy`：当前固定为 `full-containment`，表示节点完整位于组框中才算加入。
- `color`：组框颜色。
- `collapsed`：后续可用于折叠显示。
- `locked`：锁定后禁止移动和调整大小。
- `metadata`：保留扩展字段。

## 成员判定

成员判定必须和用户看到的节点框一致：

- 使用节点视觉矩形判断，包含 `x`、`y`、`width` 和真实节点高度。
- 真实节点高度需要包含参数区域、端口行和节点底部 preview display。
- 节点矩形完全被组框包含时，才加入组。
- 节点只压到一部分或只和组框重叠时，不加入组。
- 拖动节点时可以实时高亮候选组，但只在松开鼠标后更新 `member_node_ids`。
- 调整组框大小后重新计算成员关系。
- 节点从组框中移出后自动从组中移除。

第一阶段规定一个节点只能属于一个主组。节点完整落入多个组时按下面规则处理：

1. 优先加入当前选中的组。
2. 没有选中组时，加入面积最小且层级最高的组。
3. 无法明确判断时提示用户选择目标组。

## 组拖动

拖动组时应整体移动组内节点：

1. 在组标题栏或组背景按下鼠标。
2. 记录组初始 `rect` 和所有成员节点初始 `x/y`。
3. 拖动过程中同步更新组框位置和成员节点位置。
4. 同步写入成员节点 `ui_state.x` 和 `ui_state.y`。
5. 松开鼠标后提交一次最终状态。

连线不需要单独保存位置，因为连线由节点端口位置实时计算。

调整组框大小时只改变组尺寸，不移动节点；调整完成后按完整包含规则重算成员。

## 启用和禁用

组启用或禁用是对成员节点 `enabled` 的批量写入：

- 启用组：成员节点全部 `enabled=true`。
- 禁用组：成员节点全部 `enabled=false`。
- 成员节点状态不一致：组显示为部分启用。
- 删除组只删除组，不删除组内节点。

防呆规则：

- App Entry、App Result、公开输入输出边界等关键节点默认不允许被组批量禁用。
- 如果组操作跳过了受保护节点，前端应给出提示。
- 禁用组后，组框和成员节点都应有清楚的禁用视觉状态。

## 前端实现位置

建议新增或扩展以下文件：

- `frontend/web-ui/src/workflows/workflow-editor/types.ts`：新增 `WorkflowGraphGroup`、`WorkflowGraphGroupRect` 和 `WorkflowGraphTemplate.groups`。
- `frontend/web-ui/src/workflows/workflow-editor/components/WorkflowGraphGroupLayer.vue`：渲染组框、标题、状态、成员数量和 resize handles。
- `frontend/web-ui/src/workflows/workflow-editor/canvas/useWorkflowGroupDrag.ts`：处理组拖动和成员节点同步移动。
- `frontend/web-ui/src/workflows/workflow-editor/canvas/useWorkflowGroupResize.ts`：处理组框大小调整。
- `frontend/web-ui/src/workflows/workflow-editor/graph/useWorkflowGroupMembership.ts`：处理完整包含判断、成员同步和重叠组冲突。
- `frontend/web-ui/src/workflows/workflow-editor/components/WorkflowGroupDetailPanel.vue`：显示组名称、颜色、启用状态、成员列表、锁定和删除组。
- `frontend/web-ui/src/workflows/workflow-editor/documents/useWorkflowDocumentBuilder.ts`：保存和加载 `groups`。
- `frontend/web-ui/src/workflows/workflow-editor/validation/useWorkflowPreflight.ts`：前置校验 group id、rect、member node id。
- `frontend/web-ui/src/workflows/workflow-editor/pages/WorkflowEditorPage.vue`：接入组层、组选择、组属性面板和批量状态操作。

`frontend/web-ui/src/lib/litegraph/src/LGraphGroup.ts` 可作为交互参考，但正式保存格式必须使用本项目自己的 `WorkflowGraphGroup`，不能把 LiteGraph 内部序列化格式作为公开模板格式。

## 后端实现位置

建议新增或扩展：

- `backend/contracts/workflows/workflow_graph.py`
  - 新增 `WorkflowGraphGroupRect`。
  - 新增 `WorkflowGraphGroup`。
  - 在 `WorkflowGraphTemplate` 增加 `groups` 字段。
  - 校验 group id 唯一、rect 宽高为正数、成员节点存在。
- `backend/service/application/workflows/documents/`
  - 模板保存和读取保留 `groups`。
  - 模板校验返回明确错误。
- `backend/service/application/workflows/graph_executor.py`
  - 不新增 group 执行逻辑。
  - 继续只按节点 `enabled` 判断是否执行。

如果后续需要后端归一组状态，应放在模板 snapshot 固定或 validate 阶段，不放在单个节点执行阶段。

## workflow-app-20260710212239 建议分组

特征定位测试应用建议固化为 5 个验证分支组：

1. `Contour 验证分支`：Contour -> Contour Filter -> Min Area Rect -> Draw。
2. `Hough Circles 验证分支`：Hough Circles -> Draw Circles。
3. `Hough Lines 验证分支`：Hough Lines -> Draw Lines。
4. `Template Match 验证分支`：Template Region -> Template Match -> Draw Regions。
5. `ORB Homography 验证分支`：ORB Keypoints -> ORB Match -> Homography Estimate。

默认只启用一个验证分支，其余分支禁用，避免 Preview Run 被无关节点拖慢。

后续可以增加“独占启用该组”操作，用于调试验证应用中一键启用当前分支并禁用其他同级分支。该能力仍是编辑器批量操作，不进入 runtime 执行层。

## 实现顺序

1. 增加 `WorkflowGraphGroup` schema、前端类型和空 `groups` 保存加载。
2. 实现组框渲染、选择、改名、删除和颜色。
3. 实现组框 resize，并按完整包含规则同步成员。
4. 实现拖动节点加入或移出组。
5. 实现拖动组整体移动成员节点。
6. 实现组启用、禁用和部分启用三态。
7. 增加关键节点保护和冲突提示。
8. 更新 `workflow-app-20260710212239`，用节点组固化 5 个验证分支。
9. 做 Preview Run 验证，确认节点组不会增加 runtime 执行开销。

## 验收标准

- 已保存 workflow template 能持久化并重新加载组框。
- 调整组框大小后，只有完整位于组框内的节点成为成员。
- 拖动组框时，组内节点位置和 `ui_state` 一起移动。
- 组启用或禁用后，成员节点 `enabled` 状态正确同步。
- 组删除不删除节点和连线。
- Runtime 执行结果与只看节点 `enabled` 时一致。
- 节点组不会出现在 node catalog、node records 或 runtime DAG 中。
- `workflow-app-20260710212239` 能用节点组快速切换验证分支。
