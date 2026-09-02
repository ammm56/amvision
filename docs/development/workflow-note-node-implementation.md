# Workflow 说明节点实施基线

## 状态与目标

> 当前状态：代码、自动化测试和真实 Workflow App 验收已完成。本文件同时作为实现、审查和验收基线；不得把说明节点改成可执行 NodeDefinition，或加入 Runtime 特殊执行分支。

Workflow 说明节点用于在画布中保存流程说明、输入约束、操作步骤、现场注意事项、维护手册和故障处理指南。界面上继续使用“说明节点”这一直接名称，内部契约使用 `WorkflowGraphNote`。

说明节点不是业务文本数据节点。需要参与 Workflow 数据处理的文本继续使用 App Entry `text.v1`、Text To Value、String Value 和字符串操作节点。说明节点内容不能连接端口、读取运行值、成为 App Entry/App Result，也不能进入 Workflow 输出。

实现参考 `projectsrc/ComfyUI_frontend` 中 `Note`、`MarkdownNote` 的虚拟节点边界和 Markdown 显示交互，但不得直接依赖 `projectsrc/` 代码、类型或运行时资产。

## 不可变边界

- 说明节点是 editor artifact，不是 `WorkflowGraphNode`，不注册 `NodeDefinition`，不实现 Python handler。
- 说明节点保存在 `WorkflowGraphTemplate`，随 Workflow App Version 一起发布、复制和追溯。
- Runtime 可以加载包含说明节点的 Template，但拓扑、依赖、执行、节点记录和耗时统计只消费 `nodes` 与 `edges`。
- 说明节点没有输入端口、输出端口、enabled、Preview、运行状态或节点耗时。
- 不使用 `metadata.editor_only`、禁用普通节点或特殊 `node_type_id` 模拟说明节点，避免隐藏执行语义。
- 不增加代码协议 v2。开发阶段在 `amvision.workflow-graph-template.v1` 中增加有默认值的 `notes` 和 `member_note_ids`；旧文档缺少字段时按空集合加载。
- 第一阶段只提供一个支持 Markdown 的说明节点。普通文本天然是合法 Markdown，不重复实现 Plain Text Note。
- 说明内容按字面值保存和显示，不展开日期时间块、变量、节点输出、App Entry 值或其他模板语法。
- 不自动加载外部图片、视频、iframe 或其他远程资源，保持离线部署、稳定渲染和确定行为。

## 公开 JSON 契约

`WorkflowGraphTemplate` 增加：

```json
{
  "notes": []
}
```

单个说明节点使用以下结构：

```json
{
  "note_id": "note-1",
  "title": "输入与判定说明",
  "content": "## 输入\n\n- request_image_ref：待检测图片\n- request_json：可选批次参数",
  "content_format": "markdown",
  "rect": {
    "x": 360,
    "y": 120,
    "width": 420,
    "height": 260
  },
  "tone": "neutral",
  "collapsed": false,
  "locked": false,
  "metadata": {}
}
```

`WorkflowGraphNote` 字段固定为：

| 字段 | 规则 |
| --- | --- |
| `note_id` | Template 内唯一、非空；前端默认生成 `note-<number>` |
| `title` | 非空，去除首尾空白后最多 128 个字符 |
| `content` | 原始 Markdown，单项最多 64 KiB |
| `content_format` | 当前固定为 `markdown` |
| `rect` | 有限数值；最小 220×120，最大 1600×1200 |
| `tone` | `neutral`、`info`、`success`、`warning`、`danger` |
| `collapsed` | 只影响画布呈现，不改变保存内容 |
| `locked` | 只限制编辑、拖动和缩放 |
| `metadata` | 有界扩展信息，不放运行时状态 |

Template 最多保存 128 个说明节点，说明正文总量最多 1 MiB。后端负责最终校验；前端在创建和编辑时提供相同限制与明确错误。

`WorkflowGraphGroup` 增加有默认值的：

```json
{
  "member_note_ids": []
}
```

组成员关系按明确 ID 持久化：

- `member_node_ids` 只引用可执行节点；`member_note_ids` 只引用说明节点。
- 移动组时，两类成员保持相对位置。
- 组 enabled 只更新 `member_node_ids` 对应节点，不改变说明节点。
- 删除组不删除节点、说明节点或边。
- 移动或 resize 节点、说明节点、组以后，继续按 full-containment 重新计算成员。
- 不使用数组位置、创建顺序或当前 DOM 顺序推断成员关系。

## 前端呈现与交互

说明节点在画布上使用独立 `WorkflowGraphNoteLayer`，绘制顺序位于节点组之上、可执行节点和端口之下。说明节点可以与节点卡片使用相同圆角和选中 token，但默认保持低强调背景，并通过文档图标和“说明”标签明确区分。

固定交互如下：

- 工具栏提供“说明”按钮，在当前视口中心创建说明节点。
- 画布空白处右键提供“添加说明节点”，使用右键对应的世界坐标创建。
- 单击选中；只有标题栏可以开始拖动，正文选取文本和点击链接不会拖动画布。
- 右下角 resize handle 调整宽高；锁定时不显示可操作 resize handle。
- 双击正文或点击编辑按钮进入 Markdown 源文本编辑。
- `Ctrl+Enter` 完成本次编辑，`Esc` 恢复进入编辑前的内容；失焦结束编辑但保留当前草稿到内存中的 Template，最终仍需点击 Workflow“保存”。
- 折叠后只显示标题栏；展开后恢复原 rect 高度和内容滚动位置不作持久化保证。
- 锁定后禁止编辑、拖动和缩放，但允许选中、解锁和删除。
- 右键菜单提供编辑、折叠/展开、锁定/解锁、复制和删除。
- Delete/Backspace 只在非输入控件焦点下删除当前选中的说明节点。
- 选中样式使用现有画布 selection token，不使用成功绿色或运行状态色。

说明节点必须进入小地图和“定位全部节点”的世界边界计算。说明节点正文内部滚轮优先滚动正文；到达边界后也不得隐式触发画布缩放，画布缩放继续只由画布区域接收。

属性面板在选中说明节点时显示标题、Markdown 内容、tone、折叠和锁定状态，并明确显示“仅用于流程说明，不参与执行”。说明节点不显示 NodeDefinition、参数、端口、Preview 和运行耗时区域。

## Markdown 与安全

前端使用维护中的 Markdown parser 和 DOMPurify，不自行实现 Markdown 或 HTML 清理器。依赖必须写入 `frontend/web-ui/package.json` 和 lockfile，构建结果随前端静态资源本地分发，不依赖 CDN。

第一阶段允许：

- 标题、段落、换行、粗体、斜体和删除线；
- 有序/无序列表、引用、分隔线；
- 行内代码和代码块；
- 表格；
- `http`、`https` 链接。

第一阶段禁止：

- 原始 HTML、script、style、iframe、object、embed；
- `on*` 事件属性和任意内联样式；
- `javascript:`、`data:` 等非允许链接协议；
- Markdown 图片、远程视频和自动媒体加载；
- 相对路径自动解析到 ObjectStore 或本地文件系统。

链接使用新窗口打开，并固定 `target="_blank"`、`rel="noopener noreferrer"`。渲染结果必须通过明确 allowlist 清理，不能仅依赖 Markdown parser 的默认行为。Markdown 只在内容变化时重新解析，拖动、缩放、平移和画布重绘不得重复解析正文。

## 保存、发布与 Runtime

Template/Application bundle 保存必须原样往返 `notes` 和 `member_note_ids`。复制 App、复制 Template、发布 Workflow App Version、比较版本和读取不可变快照时都要保留说明节点。

说明内容属于版本化文档，因此修改说明后发布会形成新的 App Version 和 snapshot fingerprint，这是预期行为。但说明节点不得：

- 进入 `referenced_node_type_ids` 和 Node Pack 依赖清单；
- 进入拓扑排序、required node selection、Parallel/ForEach/Selection 子图；
- 创建 handler 调用、node record、trace、Preview display 或 timing；
- 创建模型 Session、LocalBuffer、ObjectStore 临时对象或清理项；
- 改变 Runtime 输入输出契约、Trigger mapping 或 SDK 调用格式。

“节点级 Preview”只允许选择可执行节点，说明节点的上下文菜单和属性面板不得提供 Preview 操作。仅包含说明节点而没有任何可执行节点的 Template 继续不满足可执行 Workflow App 的最小校验，不因说明节点存在而绕过 `nodes` 非空规则。

## 实现顺序

1. 在 Python 合同中增加 `WorkflowGraphNoteRect`、`WorkflowGraphNote`、`WorkflowGraphTemplate.notes` 和 `WorkflowGraphGroup.member_note_ids`，补齐边界校验。
2. 同步前端 TypeScript 类型、Canvas Snapshot、Template 转换、bundle 保存、复制和加载逻辑。
3. 增加 Markdown parser、DOMPurify 和明确 allowlist，先完成安全渲染单元测试。
4. 实现 `WorkflowGraphNoteLayer.vue` 和说明节点的创建、编辑、选择、拖动、resize、折叠、锁定、复制、删除。
5. 接入工具栏、画布右键菜单、属性面板、键盘删除和多选互斥状态。
6. 扩展节点组成员同步、组拖动、小地图、fit view 和世界边界计算。
7. 完成后端契约、文档往返、发布快照和 Runtime 非执行回归测试。
8. 使用真实 Workflow App 完成浏览器创建、保存、刷新、复制、发布、Runtime Preview 与正式调用验证。

每一步完成后先检查保存 JSON 和执行边界，再进入下一步。不得先做界面效果、后补契约和 Runtime 隔离。

## 验收门禁

### 后端与契约

- 缺少 `notes`、`member_note_ids` 的旧 v1 Template 可以直接加载。
- 新 Template 保存、读取、复制、发布后说明内容、rect、tone、折叠和锁定完全一致。
- 重复 note id、越界正文、非法 rect、非法 tone 和不存在的组成员返回明确校验错误。
- App Version fingerprint 会随说明内容变化；Node Pack dependency manifest 不变化。
- Preview 和正式 Runtime 的节点执行数量、输出、node records 和 timings 与删除说明节点前一致。

### 前端

- 创建、编辑、取消、保存、刷新、复制、折叠、锁定、拖动、resize 和删除行为可复现。
- 节点、边、边界、节点组和说明节点之间的选中状态互斥且不会残留。
- 说明节点随节点组移动；组启用/禁用不改变说明节点。
- 小地图与 fit view 包含说明节点，长正文只在说明节点内部滚动。
- XSS、危险链接、原始 HTML、图片和媒体加载测试全部被阻止。
- 中英文、Unicode、代码块、表格、空正文和 64 KiB 边界内容正常显示。

### 稳定性与性能

- 100 个普通说明节点下，画布平移、缩放和节点拖动不触发 Markdown 重解析风暴。
- 重复保存和刷新 100 次不丢失内容、组成员或 rect。
- 说明节点不增加 Runtime worker 的 handler、模型 Session、LocalBuffer lease 或 ObjectStore 临时对象。
- 长时间 Runtime 调用成功率和内存趋势与无说明节点版本一致。

## 文档同步

实现完成时必须同步：

- [Workflow 编辑器](../architecture/workflows/editor.md)
- [Workflow JSON](../architecture/workflows/json-contracts.md)
- [节点系统](../architecture/workflows/node-system.md)
- 前端 Workflow 编辑器交互测试和 API/JSON 示例中涉及 Template 的结构说明

## 实施与验收结果

- 后端已实现 `WorkflowGraphNoteRect`、`WorkflowGraphNote`、`WorkflowGraphTemplate.notes` 和 `WorkflowGraphGroup.member_note_ids`，并校验数量、UTF-8 正文大小、总量、矩形范围、唯一 id 和组成员引用。
- 前端已实现工具栏与右键创建、Markdown 安全显示、源文本编辑、拖动、缩放、折叠、锁定、复制、删除、属性面板、节点组、小地图和 fit view；Markdown 结果按 `note_id + content` 缓存，位置变化不会重复解析正文。
- Markdown 只允许本文件列出的标签和 `http`、`https` 链接；原始 HTML、危险协议、相对路径、图片和媒体不会进入最终 DOM。
- 自动化验收包括后端契约与执行范围、前端文档往返、安全渲染、交互、节点组、视口、preflight、TypeScript 和生产构建。
- 真实验收应用为 `workflow-app-20260902102430`，已完成创建、保存、刷新、复制、删除、折叠、展开和发布 v1。应用包含一个可执行 String Value 节点和一个说明节点；说明中的 script 与远程图片均未进入 DOM。
- 正式 Runtime `workflow-runtime-e572bec733a54f598ac652c46c3f7c90` 调用 `workflow-run-6972e4e5213946969402ff82214be101` 成功。回执不包含 `note-1` 或说明内容，说明节点未改变公开输入输出；执行拓扑测试进一步确认节点级执行范围会清空 `notes` 与 `member_note_ids`。
- 本次验收确认功能和执行隔离边界；长时间生产 soak 仍属于发布前持续认证，不以一次开发态浏览器调用替代。
