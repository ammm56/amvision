# Workflow 文档导入、导出与统一载入器设计

状态：已实现；当前实现与验收边界。核对日期：2026-09-07。

本文冻结 Workflow Node App 编辑文档的 JSON 导入、导出、当前工作流加载和历史版本载入边界。目标是先建立一份稳定的便携文档和一条统一载入路径，再让历史版本功能复用该路径。本文不定义完整应用包，不改变 Workflow Runtime、Trigger 或高性能调用链路。

## 1. 已决原则

1. 导出的是编辑器当前内存中的 Workflow 内容，包括尚未保存的修改，不是重新读取服务端草稿。
2. 导入只替换当前浏览器编辑内容，不自动保存、发布、创建 Runtime、创建 Trigger 或切换 Runtime 版本。
3. 导入先完成读取、解析、校验和目标身份处理，全部成功后才一次性替换编辑状态；失败时当前画布保持不变。
4. 已保存工作流、导入文件和历史版本最终调用同一套编辑器载入实现，不维护三套节点、绑定和布局加载逻辑。
5. Workflow JSON 只携带工作流定义和资源引用，不嵌入模型、图片、文件、Deployment 或 ObjectStore 对象。
6. Runtime、Trigger、WorkflowRun、发布版本列表及服务端文档摘要不属于 Workflow JSON。
7. 初版不实现画布拖入 JSON、历史只读画布、草稿备份、版本比较、自动保存、自动发布或自动 Runtime 切版。

## 2. 当前代码基础

当前编辑器已有以下可复用能力：

- [useWorkflowDocumentBuilder.ts](../../../frontend/web-ui/src/workflows/workflow-editor/documents/useWorkflowDocumentBuilder.ts) 可以从当前画布和绑定草稿构造 `WorkflowGraphTemplate` 与 `FlowApplication`。
- [useWorkflowDocumentLoader.ts](../../../frontend/web-ui/src/workflows/workflow-editor/documents/useWorkflowDocumentLoader.ts) 通过 `replaceWorkflowEditorDocument` 统一替换已保存工作流、新建空文档、导入文件和历史内容；保存回读保留输入和选择。
- [workflow-app.service.ts](../../../frontend/web-ui/src/workflows/workflow-editor/services/workflow-app.service.ts) 已把 Application、Template、Runtime 和发布版本组合成页面文档；便携 JSON 不能直接序列化这份包含运行态与服务端摘要的页面对象。
- `validateWorkflowTemplate`、`validateWorkflowApplication` 和编辑器 preflight 已提供保存、预览、发布前的可执行性校验。导入通过 [workflow-app-document.ts](../../../frontend/web-ui/src/workflows/workflow-editor/documents/workflow-app-document.ts) 的纯结构解析器，不把当前 Node Catalog 是否完整作为载入门槛。
- [Workflow App Version 服务](../../../backend/service/application/workflows/app_version_service.py) 的版本详情已经回读并校验不可变文件集，返回完整 Application 与 Template；历史载入不需要新的恢复接口。

## 3. 便携 JSON 契约

顶层格式固定为：

```json
{
  "format_id": "amvision.workflow-app-document.v1",
  "application": {},
  "template": {}
}
```

`amvision.workflow-app-document.v1` 是文件格式版本，不是 Workflow App 的发布版本号。初版只接受该格式，不猜测或静默迁移其他根格式。

上例只展示文件外壳，两个空对象不是可导入示例。文件仍保存现有 Application/Template 字段，不发明另一套节点图结构。application_id、template_id/template_version 和对应 template_ref 标识保留在文件中并互相一致，用于描述源工作流；导入时按当前编辑目标重设这些标识，而不是按文件中的 id 切换资源。

### 3.1 application

`application` 保存当前 `FlowApplication` 的可编辑内容：

- display_name、description、runtime_mode
- format_id、application_id 和 template_ref
- App Entry 与 App Result 对应的 bindings
- binding 的 required、config、metadata 和 payload 类型信息
- `metadata.workflow_graph_editor`
- `metadata.app_mode`
- 其他属于 Workflow 编辑文档的扩展 metadata

### 3.2 template

`template` 保存当前 `WorkflowGraphTemplate`：

- nodes、edges
- format_id、template_id、template_version
- template_inputs、template_outputs
- groups、notes
- 节点 parameters、enabled、metadata、ui_state
- Template display_name、description、metadata

### 3.3 明确排除

以下内容不进入便携 JSON：

- 页面 Project 上下文、`application.metadata.project_id`、服务端文档的 ObjectStore 保存键和数据库记录定位信息
- ApplicationDocument、TemplateDocument 的 object_key、created_at、updated_at、created_by、updated_by
- draft_fingerprint、版本 manifest、contract、dependencies
- Runtime、Trigger、WorkflowRun、Preview Run
- Preview 临时输入、执行结果、订阅、对象 URL 和浏览器选择状态
- 模型、图片、文件、Node Pack 和 Deployment 的二进制内容

节点参数中的 Deployment id、ObjectStore key、本地路径等仍按普通 JSON 引用值保存。导入不保证目标环境存在这些资源；实际预览、保存或运行时沿用现有校验和错误反馈。

排除规则只针对上述文档层字段，不能递归删除所有同名 project_id、object_key 或 runtime_id，以免删掉节点真实参数。Application/Template 的扩展 metadata 原样保存，除了明确排除的 `application.metadata.project_id`。

由于 Template 已放在同一个文件内，导出时将副本的 template_ref.source_kind 设为现有契约支持的 `embedded`，source_uri 设为 null；保持 template_id/template_version 与文件内 Template 一致。这样不会把源 Project 的模板保存路径当成便携文档依赖。导入时恢复当前目标的 source_kind/source_uri，不修改源编辑对象。该处理仅属于文件适配，不修改发布快照或现有后端保存格式。

### 3.4 文件规则

- 默认文件名：`<application_id>.json`
- 编码：UTF-8
- 输出：两空格缩进，文件末尾保留换行
- 最大文件大小：初版固定 16 MiB，不提供页面配置
- 图节点最多 10000 个、说明最多 128 个；图集合及节点组成员引用合计最多 50000 项
- parameters、metadata、config 等自由 JSON 字段最多嵌套 64 层；整份文档最多遍历 200000 个 JSON 值
- 根对象不增加 exported_at、当前发布编号或 Runtime/Trigger id，避免同一内容因导出环境不同产生无意义差异

## 4. 导出流程

```text
当前编辑状态
  -> buildCurrentTemplate()
  -> buildCurrentApplication(template)
  -> 构造 amvision.workflow-app-document.v1
  -> JSON 序列化
  -> 浏览器下载
```

导出必须读取当前画布、公开绑定、节点组、说明节点、边界位置和 App Mode 草稿，因此未保存修改也会进入文件。导出不调用保存、发布、Runtime 或 Trigger API，也不检查模型、图片、文件和 Deployment 是否存在。

缺少当前 NodeDefinition 时仍允许导出已有 JSON，避免节点包状态变化导致现有工作流无法导出。导出使用与导入相同的纯结构校验，不调用保存或可执行性校验；允许空画布、缺少必填运行参数或尚未接好输入的编辑状态，只要字段结构与已有引用有效。字段类型或引用结构错误时显示错误位置，不下载一个自身无法导入的文件。

导出以可序列化的编辑模型为准；复杂参数表单中尚未解析的 JSON 文本先提交到该模型，解析失败直接使用现有字段错误，不静默导出该字段的旧值。浏览器下载触发后在适当时机撤销 Blob URL，不能在下载尚未取得内容前撤销；失败时不改变页面状态。

## 5. 导入流程

### 5.1 原子处理顺序

```text
选择 .json 文件
  -> 检查文件大小
  -> 按 UTF-8 读取
  -> JSON.parse
  -> 校验根 format_id、Application、Template 和内部引用
  -> 绑定到当前编辑目标身份
  -> 构造完整的新编辑状态（不要求当前环境可执行）
  -> 一次性替换当前编辑状态
  -> 清理旧 Preview 和临时资源
```

读取失败、JSON 语法错误、格式不支持、字段错误、引用错误、校验失败或网络错误均不能先清空当前画布。文件选择器处理结束后重置 value，使同一文件可以再次选择。

### 5.2 校验边界

导入只做纯文件结构校验，并复用编辑器已有的节点缺失等本地提示；保存、预览和发布继续走原有校验流程，不为导入增加环境检查阶段。

文件结构校验失败时不载入，范围包括：

- 顶层必须是 JSON Object，且只接受 `amvision.workflow-app-document.v1`
- application、template 必须存在且类型正确
- Application 与 Template 各自 format_id 正确
- `application.template_ref` 与 Template 的 id/version 一致
- 节点、边、Template 输入输出、binding、节点组和说明节点 id 唯一
- Edge、Template 输入输出、binding、group 成员引用存在
- 字段类型和当前 v1 契约一致
- 文件大小、图元素数量、JSON 嵌套和 JSON 值总数不超过固定边界

此处校验的是编辑文件结构，不直接调用要求可执行图的后端 Pydantic 完整校验。nodes 为空、节点必填运行参数暂缺或输入未接完整，不属于文件结构错误；可以先载入再继续编辑。真正保存或预览时由现有规则反馈这些问题。

前端使用纯函数 `parseWorkflowAppDocumentV1`，只负责把不可信 JSON 解析成可载入的 v1 Application/Template，不读取文件引用、不执行节点、不访问 Runtime，也不修改当前响应式状态。自由 JSON 字段使用显式栈检查，避免深层输入造成递归栈溢出；数量超限在构造画布前直接失败。不要为此增加新的数据库资源、后台任务或导入 API。

缺失 NodeDefinition 可用已有未知节点视图显示；不阻止结构正确的文件载入。文件不携带发布依赖摘要，因此不能判断节点实现相对导出时是否变化，也不新增历史摘要匹配响应。导入不查询 Deployment/ObjectStore/本地文件，不承诺载入时发现资源缺失。保存和预览沿用现有 preflight、validateWorkflowTemplate、validateWorkflowApplication；只有实际执行时才能发现的问题由运行错误反馈，不能声称现有保存校验会提前发现所有环境问题。导入不得自动安装、替换或执行节点。

### 5.3 当前目标身份

导入到已有工作流时，保留当前保存目标：

- 当前 Project
- application_id
- template_id、template_version
- template_ref.source_kind、template_ref.source_uri

从导入文件载入名称、说明、节点、连线、参数、Template 输入输出、Application bindings、节点组、说明节点、编辑器 metadata 和 App Mode 配置。

Application/Template 的名称、说明和扩展 metadata 从来源整体载入，不与旧工作流配置混合；仅目标身份和 `application.metadata.project_id` 按当前上下文处理。来源没有 app_mode 或 workflow_graph_editor 时清除原对应配置。文件中的 template_ref 只用于验证来源配对，替换后使用当前保存目标的引用字段。

在新建工作流页面导入时，继续使用新建草稿已生成的标准 Application/Graph id，不直接采用文件中的旧 id。这样导入不会切换浏览器路由，也不会把内容保存到另一个 Workflow 资源。

新建表单的名称说明同步为导入值，已有工作流的标题/说明编辑状态也同步；避免下一次 buildCurrentApplication/buildCurrentTemplate 又用旧表单值覆盖刚载入的内容。

发布快照中的 `application.metadata.project_id` 是运行和发布阶段注入的信息，不作为便携编辑内容迁移；目标 Project 始终来自当前页面上下文。

### 5.4 成功后的编辑状态

成功后一次替换：

- Application 和 Template 可编辑内容
- 节点、边、Template 输入输出和 bindings
- groups、notes 和画布位置
- App Mode 配置

同时清理：

- 原节点、边和边界选择
- 已失效属性面板状态与复杂参数临时草稿
- Preview 输入、结果、临时图片 URL 和迟到回调
- 只属于上一个编辑文档的浏览器临时状态

页面显示“已导入，尚未保存”。未保存直接刷新时重新读取服务端草稿；只有显式保存才更新当前 Workflow App。

## 6. 统一载入器

Document Loader 提供统一替换入口；输入为保留页面上下文的 WorkflowAppDocument：

```ts
replaceWorkflowEditorDocument(appDocument, preserveExisting = false)
```

文件和历史来源先通过 `retargetWorkflowAppDocument` 保留当前目标身份，再调用 `replaceWorkflowEditorDocument`；来源提示和未保存标记在页面处理，不新增 source 枚举。服务端载入和保存回读更新编辑基线，新建页面也把本地空文档交给同一入口。节点、边、binding、group、note 的赋值不分来源重复实现。

当前保存反馈刷新会保留 Preview 输入及选择，不应因抽取载入器被改成全部清空。按调用目的使用一个轻量的视图重置选项：打开/导入/历史载入重置旧 Preview 与选择；同文档保存反馈刷新沿用现有保留行为。该选项只处理 UI 状态，不引入多套文档模型。

统一载入器必须满足：

1. 输入数据先深复制，编辑操作不能修改导入对象、历史响应缓存或服务端读取对象。
2. v1 文档不得静默改写 node id、edge id、input/output id、binding id 或 template_port_id。
3. 已载入节点保留序列化参数；节点默认值只在新建节点或明确编辑时应用。当前 [useWorkflowGraphNodeViews.ts](../../../frontend/web-ui/src/workflows/workflow-editor/nodes/useWorkflowGraphNodeViews.ts) 已取消载入时的缺失默认值注入。
4. 视图层缺失位置或宽度可以使用显示兜底，但未发生实际编辑时不能把兜底值自动写回导出或保存内容。
5. 已有 HTTP 输出 id 和图片输入绑定兼容逻辑不得对当前 v1 文件做无条件迁移；确需保留的旧数据迁移必须与普通保存加载共用并可测试。
6. 缺失 NodeDefinition 的节点可以使用现有未知节点视图显示；保存、预览和发布继续由同一 preflight 阻止。
7. 替换本身不执行节点、不读本地文件、不下载外部资源、不保存数据库。

`workflowApp` 页面对象中的 Runtime、版本列表、latestVersion、服务端文档摘要和当前路由身份继续保留，只替换其中供编辑器使用的 Application/Template 内容，不能用版本详情对象覆盖整个页面对象。

## 7. 页面交互

空白画布右键菜单底部提供文档操作，顶部不再放置“文件”或“说明”按钮：

```text
空白画布右键菜单
  预览
  添加节点
  添加说明
  …其余画布操作
  ──────────
  导出工作流
  导入工作流
```

交互约束：

- 空白画布右键前三项固定为添加节点、添加说明、预览；不提供隐藏小地图项，显隐沿用底部视图控制。

- 使用现有 Menu、Button、图标、主题 token 和过渡效果
- 不使用浏览器原生 alert 或原生下拉样式
- 导出点击后立即下载，不增加配置对话框
- 导入打开系统文件选择器，accept 限定 JSON
- 文件输入独立于右键菜单挂载，关闭菜单不影响文件选择；取消选择不改变编辑内容。节点、连线、说明和 App 边界的右键菜单不提供文档替换操作。
- 菜单按视口边界调整位置，底部导入、导出项不会因右键位置靠近窗口边缘而不可见。
- 校验期间禁止重复导入，避免并发请求乱序
- 导入成功后关闭菜单、重置选择并反馈“已导入，尚未保存”
- 失败使用现有 InlineError/页面反馈，保留当前编辑内容
- 中文、英文、日语、韩语同步实现
- 初版不支持把 JSON 拖到画布，避免与节点、图片和普通文件拖拽冲突

## 8. 与保存、发布和运行的关系

| 操作 | 浏览器编辑内容 | 服务端草稿 | 发布版本 | Runtime/Trigger |
| --- | --- | --- | --- | --- |
| 导出 JSON | 不变 | 不变 | 不变 | 不变 |
| 导入 JSON | 替换 | 不变 | 不变 | 不变 |
| 载入历史版本 | 替换 | 不变 | 不变 | 不变 |
| 保存 | 保持 | 更新 | 不变 | 不变 |
| 发布 | 保持 | 先保存 | 通过校验和去重后新增不可变版本 | 不自动切版 |
| Runtime 切版 | 不变 | 不变 | 不变 | 仅显式操作后改变 |

发布仍沿用现有“保存 Application + Template，再按草稿指纹发布”流程。导入/载入不会停止 Trigger，不会改变 Runtime desired/active revision，不会影响 ZeroMQ、本机共享内存、目录 Trigger 或 HTTP Runtime 调用性能。

## 9. 实现组成

1. `workflow-app-document.ts` 定义 TypeScript 文件契约、format 常量、结构校验、身份处理与 Blob 下载。
2. Builder 从当前编辑状态导出；复杂参数草稿解析后写回，结构不合法则阻止导出。
3. Document Loader 统一替换图文档，正常打开与保存回读分别重置或保留选择/输入。
4. 空白画布右键菜单调用持久挂载的文件输入，读取本地 JSON 并解析后调用统一载入入口；历史详情复用同一路径。
5. 已有参数与 metadata 按原值保留；新建节点默认值与载入职责分开。

不新增数据库表、Alembic 迁移、导入后台任务、恢复任务、队列、Runtime 协议或 Trigger 协议。

## 10. 验收基线

1. 当前复杂 Workflow 导出包含节点、边、参数、bindings、Template 输入输出、groups、notes、位置和 App Mode。
2. 导出包含未保存修改，不包含 Runtime、Trigger、Run、Preview 结果和服务端摘要。
3. 导出后导入并再次导出，除目标身份、明确排除的 Project metadata 和便携 template_ref 外，Application/Template 语义深度一致；嵌套参数中的同名资源字段不被误删。
4. 无效 JSON、错误 format、超限文件、引用错误和校验失败均不改变当前画布。
5. 导入其他 Workflow 时，当前 Project、Application id、Template id/version 和保存路径不变。
6. 导入后不产生保存、发布、Runtime、Trigger 或节点执行请求。
7. 导入后 Preview、保存、刷新和发布使用新内容；未保存刷新恢复原服务端草稿。
8. 缺失 NodeDefinition 时不执行或替换节点，错误可定位；当前内容仍可导出。
9. 同一文件可重复选择；快速重复点击不会产生乱序覆盖。
10. 重复导入/导出后无 Blob URL、Preview 图片 URL、事件监听器或迟到回调保留。
11. 四语言、亮色/暗色、键盘焦点和错误反馈与现有编辑器一致。
12. 验证导入/导出没有发出 Runtime/Trigger 控制或节点执行请求；不为纯编辑器功能新增整条推理/触发链路的性能门禁。
13. 空画布、缺少运行必填参数和缺失节点包的文件能导出并重新导入；结构错误不能先清空页面；未解析的参数文本不得被静默替换为旧值导出。
14. 导入名称说明、Template metadata 和 App Mode 后再保存，内容不被旧表单或旧配置覆盖；正常保存反馈刷新继续保留原有 Preview 输入和选择行为。

实现验证记录见第 11 节。

## 11. 实现与验证记录（2026-09-07）

- 文件格式、16 MiB 上限、图元素/JSON 复杂度上限、显式栈校验、深复制、结构/引用校验、便携 template_ref 和目标身份处理：`documents/workflow-app-document.ts`。
- 空白画布右键入口与同一文件重复选择：`components/WorkflowGraphContextMenu.vue`、`components/WorkflowDocumentFileInput.vue`；Blob 下载由文档模块处理，导出先提交实际改动过的复杂 JSON 参数，解析失败时阻止导出。
- 统一载入器与 Builder 保留原始参数、公开 ID、metadata、groups、notes、App Mode；显示兜底位置不自动回写。参数、绑定和图状态均深复制。
- 载入后显示未保存状态；清理 Preview、选择、节点组操作和属性面板临时状态；迟到 Preview 请求/图片回调和关闭后的版本请求不会应用到新文档。
- `npm run build` 与前端全量 443 项测试通过；自动测试覆盖文件往返、无效引用/格式/非有限数字、空图、未知节点、保存目标、默认值和布局保真、保存回读、异步替换与菜单操作。
- 真实页面使用独立测试应用 `workflow-app-20260907100303`：Edge 实际下载并核对 JSON；内置浏览器导入错误文件保留原图，导入含 Value Input → Value Preview、节点组、说明节点和 App Mode 的文件后预览成功；分别发布 v1/v2，验证历史载入和显式保存。
- 验收期间应用 Runtime/Trigger 数保持 0/0。没有为导入添加数据库表、后台任务、节点执行或 Runtime/Trigger 控制请求。
- 最终审计补充 10,000 节点、128 说明、50,000 图元素、64 层 JSON、200,000 JSON 值和 16 MiB 文件边界；显式栈校验避免深层输入造成递归栈溢出。直接保存前会统一提交实际编辑过的 JSON 草稿，必填空值和非法值保持未提交并阻止保存，文档整体替换会同时清除草稿文本与编辑标记。前端 117 个测试文件共 471 项、`vue-tsc` 和生产构建通过。

测试文件不嵌入图片、模型等资源。App Mode 的内容仍受现有运行校验约束；结构可载入不代表能运行。Edge 扩展未开启文件 URL 权限，因此自动化文件选择使用内置浏览器；Edge 已验证实际下载。便携格式只包含文档，不是完整运行环境备份。

### 显式保存后的字段规范化

纯导入/导出保留源字段；显式保存仍调用既有后端 `synchronize_flow_application_bindings`。后端按模板同步 binding 的 required、config.payload_type_id 和 metadata.payload_type_id，并在缺省时补齐 metadata.display_name。该行为来自 [workflow_graph.py](../../../backend/contracts/workflows/workflow_graph.py)，不是前端载入迁移。

真实文件经过“导入 → 显式保存/发布 → 历史载入 → Edge 导出”后，按当前目标身份及上述既有 binding 同步规则比较，Application/Template 全部字段一致，包括布局宽度 300/320、分组成员、说明和 App Mode。

本轮新增测试已迁至仓库根 `tests/frontend/workflows/test_*.ts`，由前端现有 Vitest 依赖和 vue-tsc 统一执行，详见 [前端测试约定](../../../tests/frontend/README.md)。
