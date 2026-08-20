# 节点系统说明

## 文档目的

本文档用于说明平台节点系统的位置、边界、类型、生命周期，以及它和节点编辑器的关系。

node pack 的拆分标准、包内目录、core 分类和兼容迁移统一见
[节点包边界和节点分类](node-taxonomy.md)。

本文档主要回答两个问题：哪些能力保留在核心平台，哪些能力通过 node pack 扩展；custom nodes 如何向 ComfyUI 的扩展体验靠拢，同时保持工业现场需要的版本、权限、超时、禁用和回滚约束。

## 设计目标

- 让核心平台保持稳定、可部署、可回滚，不把场景化需求持续堆入 core
- 让流程编排和节点编辑能够把核心节点与 custom nodes 统一纳入同一张执行图
- 让协议集成、结果处理、模块连接和硬件桥接优先通过 node pack 扩展
- 让现场定制能力通过受控 manifest、目录和 entrypoint 接入，而不是直接侵入 backend/service
- 在节点扩展自由度和工业现场可控性之间保持平衡

## 核心原则

- 核心平台处理公开接口规则、任务编排、版本管理和节点扩展生命周期管理
- 场景化能力优先通过 node pack 扩展，而不是直接扩散到核心模块
- 核心平台默认不内置相机、PLC、传感器、机械臂等硬件直连驱动
- 如确有现场直连需求，应通过受控 node pack 在独立边界中实现，并接受 manifest、权限、超时、禁用和回滚约束
- core nodes、custom nodes 和流程模板在节点编辑器中应作为统一的一等公民展示和编排
- 节点注册机制向 ComfyUI custom nodes 的灵活性看齐，但不能牺牲工业场景的稳定性和可追溯性
- node pack 之间允许存在依赖关系，这一点与 ComfyUI custom nodes 生态一致，但依赖关系必须保持范围清楚、行为可预期、失败点可定位

## 数值参数输入规范

- 节点参数继续使用 JSON Schema 作为唯一约束来源；需要精确小数网格的 `number` 参数必须声明正数 `multipleOf`，并按需声明 `minimum`、`maximum`、`exclusiveMinimum` 或 `exclusiveMaximum`
- 流程编辑器直接把 `multipleOf` 映射为原生数值输入框的 `step`，把边界对齐到同一数值网格，不使用 `step="any"`
- `integer` 未声明 `multipleOf` 时使用步长 `1`
- 第三方 `number` 节点未声明 `multipleOf` 时使用确定性范围规则：跨度不超过 `10` 使用 `0.01`，不超过 `1000` 使用 `0.1`，更大跨度使用 `1`；缺少完整范围时使用 `0.01`
- 范围规则只作为 UI 回退，新节点应显式声明 `multipleOf`，确保前端交互、API 校验和执行期参数解释使用同一数值网格

## node pack 依赖约定

- node pack 不要求绝对独立；当某个 pack 复用另一个 pack 中已经稳定、复杂、重复成本高的能力时，可以建立 pack 间依赖
- 简单节点优先在本 pack 内完成实现；参数规范化、小型 helper、单一结果整理这类逻辑，优先放到当前 pack 的 support 模块，不要为了少量代码直接依赖另一个 pack
- 复杂节点、组合节点、桥接节点或结果处理链，在复用另一个 pack 的成熟能力比重复实现更清楚时，可以依赖另一个 pack
- pack 间依赖应尽量是显式、窄范围依赖，不要让一个简单 helper 把整个 sibling pack 变成启动期硬依赖
- pack 间依赖必须在 manifest metadata 或包文档中写明依赖的 pack、用途和最低版本边界
- pack 间依赖如果缺失，应在依赖节点自身附近给出清楚错误，而不是让无关节点或整个服务启动阶段一起失效
- 不要通过 backend entrypoint、目录扫描初始化或类似全量预加载链路，引入仅为单个简单节点服务的跨 pack 顶层 import
- 如果 pack 间依赖属于长期稳定关系，后续应继续向正式 dependency 字段、兼容性校验和启用前检查收敛，而不是长期停留在隐式代码耦合

## 节点系统在整体架构中的位置

- backend-service：发现 node pack、读取 manifest，并按 enabledByDefault 决定是否把 pack 纳入统一 NodeCatalogRegistry
- workers：在运行时环境中执行 custom node 逻辑，处理节点输入输出规则
- frontend/web-ui：读取统一节点目录、参数 schema 和分类信息，在节点编辑器与配置面板里渲染节点能力
- contracts：放 node pack manifest、节点定义、payload 规则 和输入输出 schema 的共用格式
- runtimes：放节点运行环境和依赖隔离边界
- packaging：处理默认 custom_nodes、可选 node pack 资产和发布装配

## node pack 类型

### 流程节点包

- 提供模型节点、传统视觉节点、控制节点、条件节点和工具节点
- 参与统一流程编排和节点执行图
- 通过输入输出 schema 和参数 schema 接入执行器与节点编辑器

### 集成节点包

- 提供与上位机、采集系统、MES、PLC 网关、设备代理系统等外部系统的协议交互能力
- 处理请求接入、状态订阅、结果回传和联动触发
- 可声明定制输入输出端点、回调格式和结果映射规则

### 结果处理节点包

- 提供检测结果过滤、规则判定、尺寸测量、缺陷归并和结果转换能力
- 与模型推理结果、传统视觉结果和外部结果处理链路组合使用
- 可在流程执行链中承担标准节点角色，而不是旁路脚本

### 现场桥接节点包

- 作为独立可选扩展实现相机、PLC、传感器、机械臂等硬件直连能力
- 不属于核心平台默认能力，必须在节点扩展边界内独立实现和管理
- 与核心平台只通过受控接口规则交互，不把硬件 SDK 和驱动逻辑渗透进 core

### Trigger Source Bridge / Listener 节点包

- 作为独立可选扩展实现 PLC 条件监听、MQTT 订阅、ZeroMQ 本地主题监听、gRPC 入口桥接、IO 变化监听和传感器阈值触发
- 这类 node pack 的职责是把外部事件转换成 WorkflowRun 创建请求，而不是把业务图执行逻辑搬进监听器本身
- trigger source 默认只创建 WorkflowRun，不直接执行图；图执行仍由 runtime instance 负责
- listener 或 bridge 可以长期运行，但应停留在受控边界中，不把协议循环、驱动状态机和厂商 SDK 直接写进 backend-service 主链路
- 当外部事件到达后，bridge 应优先创建 WorkflowRun 并交给 runtime instance 执行，而不是让 workflow 首节点长期空转轮询外部世界
- 这类扩展应声明独立 capability、timeout、外部依赖、去抖策略、幂等键来源和启停方式，保证现场长期运行时的可控性和可审计性

## node pack 目录结构

```text
custom_nodes/
└─ <node-pack-name>/
   ├─ manifest.json
   ├─ backend/
   │  └─ entry.py
   ├─ workflow/
   │  └─ catalog.json
   ├─ categories/ | providers/ | recipes/
   ├─ schemas/
   │  ├─ config/
   │  ├─ inputs/
   │  ├─ outputs/
   │  └─ ui/
   ├─ assets/
   └─ docs/
```

一个技术域只保留一个一级 node pack。功能分类放 `categories`，实现后端放
`providers`，业务配置场景放 `recipes`。OpenCV basic、geometry、measurement，
USB/UVC，相机厂商，SQLite/MySQL 和 MES 提交都不是一级 pack 的默认拆分依据。

## manifest 最低要求

- `id` 和独立 SemVer `version`
- `category`、`capabilities` 和 `dependencies`
- `entrypoints.backend` 和 `customNodeCatalogPath`
- `compatibility.api`、`compatibility.runtime`，以及可选的操作系统和架构范围
- `timeout.defaultSeconds`、`timeout.maxSeconds` 和 `timeout.killGraceSeconds`
- `enabledByDefault`

节点实现的 `NodeDefinition.version` 与 node pack 版本相互独立。流程模板同时固定
`node_pack_id`、`node_pack_version` 和节点实现版本，不能用后端版本或 pack 版本自动覆盖
节点实现版本。

## 生命周期

### 1. 发现

- backend-service 在 custom_nodes 根目录中发现可用 node pack
- 使用 NodePackManifest 校验 manifest 完整性、版本兼容性和依赖边界
- backend-service 启动时读取 manifest、catalog，并加载已经启用且审核通过的 custom node
  handler；这些 handler 与 core node 共用进程内调用路径

### 2. 注册

- 使用 LocalNodePackLoader 读取 manifest 与 workflow/catalog.json
- 通过 NodeCatalogRegistry 合并 core nodes 与 custom nodes
- 为前端节点编辑器和执行器生成统一节点目录
- 安装 ZIP 在 staging 中执行路径穿越、绝对路径、链接、重复路径、大小写冲突、
  加密成员、文件数、单文件大小、解压总量和异常压缩率校验
- staging 静态规则通过后，平台直接加载 backend entrypoint，并要求全部 executable node
  完成 handler 注册；导入异常、入口不可调用或注册缺失都会拒绝安装

### 3. 启用

- 允许按 node pack 启用或禁用；激活版本由版本库状态唯一确定
- 启用前进行 manifest dependencies 依赖检查和运行时兼容性校验
- 启用、禁用、安装、升级、回滚和 reload 都写入持久化审计记录

### 4. 执行

- 执行器按节点输入输出规则直接调用 custom node 逻辑
- 结果和错误统一回到后端服务状态流中
- 节点扩展能力可在受控接口内连接内部模块、外部端点和相关数据对象
- 编辑器同步 Preview 在 backend-service 内复用已加载的 runtime registry，不为 core node
  或 custom node 新建执行进程；常驻 AppRuntime 在自己的长期 worker 中直接调用同一套 handler
- manifest 的 timeout 继续用于参数校验、协作式取消和运行记录，但不再为了单个节点启动或
  强杀额外进程；不能协作式停止的节点由管理员在导入前审核其实现和外部调用超时

### 5. 升级

- 升级以 node pack 版本为单位进行，不覆盖历史版本记录
- 相同 id + version 只能对应同一个内容 SHA-256，不允许同版本覆盖
- 版本内容写入 `.amvision-node-packs/versions/` 的不可变版本库；激活目录通过同卷
  rename 原子替换，状态文件提交失败或运行时刷新失败时恢复原目录
- 当前项目仍处于 v1 开发阶段，不保留旧 schema 或旧数据兼容分支；节点 schema 或
  行为变化直接更新当前 v1 规则，并同步更新节点实现版本、测试和文档

### 6. 禁用与回滚

- node pack 可被禁用或回滚到不可变版本库中的任一已登记版本
- 回滚前再次校验版本目录哈希、manifest 身份、兼容范围和依赖；目录切换、状态指针和
  runtime reload 作为一个事务处理
- `transaction.json` 记录尚未提交的激活过程；服务重启后先恢复未完成事务，再接受新的
  生命周期操作
- API 提供 ZIP 安装、版本列表、回滚、启用、禁用和审计查询，前端节点目录页使用同一组
  接口，不直接修改 manifest 文件

## 可信直调边界

本地工业视觉部署把 node pack 的安装和启用视为使用者已经完成的信任选择。core node、
内置 node pack 和导入的第三方 node pack 使用同一套进程内 handler 注册与调用方式，不做
per-node 权限 scope、不注入权限代理，也不为单个节点创建隔离进程。HTTP、数据库、PLC、
相机、ObjectStore 和模型资源由节点实现直接调用项目已有接口。

WorkflowAppRuntime 的长期 worker 和 deployment 的常驻推理进程仍然保留，因为它们是平台
进程生命周期与故障恢复边界，不是节点权限或隔离策略。节点代码自身需要为外部调用设置
明确的连接、读取和执行超时，避免一个阻塞调用占住长期 worker。

## 信任与执行边界

- Python node pack 是管理员主动安装、启用并审核的受信任扩展。安装验证仍可使用一次性
  子进程检查 import 和 handler 注册，但正常节点执行不经过隔离进程或跨进程 RPC。
- 同步 Preview 在 backend-service 内直接执行；正式 AppRuntime 仍有长期 worker 生命周期，
  但 core node 与 custom node 都在该 worker 内直接调用，不按节点拆进程。
- scope 只约束平台管理的 ObjectStore、HTTP、数据库、PLC、相机和模型资产入口。普通
  Python 代码如果直接调用 `open`、`socket`、`subprocess` 或厂商 SDK，不能由应用层 scope
  完成操作系统级阻断。
- 当前 Python node pack 不是面向任意租户的不可信代码沙箱。需要运行未经信任的第三方
  代码时，必须另设 service-call 节点或接入
  Windows AppContainer、Linux namespace/seccomp/container 等操作系统隔离配置，不能只靠
  manifest 权限宣称安全。

## 节点编辑器对齐 ComfyUI 的方向

- 节点编辑器需要统一展示 core nodes 与 custom nodes
- custom nodes 应支持分类、搜索、图标、说明、参数 schema 和输入输出端口声明
- 流程模板应像 ComfyUI workflow 一样能保存节点图结构、参数状态和版本引用
- custom node 的注册、卸载和升级不应要求修改核心前端代码结构
- 与 ComfyUI 对齐的是“节点扩展模型”，不是照搬其无约束运行方式

## 通用 Parallel 执行边界

Workflow 核心节点使用 `Split List`、`Parallel Start`、现有 `Get List Item` 和
`Parallel End` 组合任意数量的显式分支。List 节点归入
`core.logic.collection`，并行执行边界归入 `core.logic.parallel`，节点名称、端口和
参数保持 English。

分支数量由画布连线决定，`max_concurrency` 仅限制同时运行数。执行器不自动并行整张 DAG。当前 80 个 ROI、3 个 deployment instances 的 classification 应用只是现场配置，不得把 3、托盘、插槽或 classification 固化到节点实现。详细契约和验证要求见 [workflow-parallel-branches.md](workflow-parallel-branches.md)。

## 节点组边界

节点组用于 workflow editor 中的画布整理、调试分支管理和批量启用 / 禁用节点。节点组可以向 ComfyUI 的 group 框体验靠拢，但它不是 runtime node。

## 模型 Load Checkpoint 节点

图内加载模型的 custom node 使用统一的 `WorkflowModelSessionProvider`，详细规则见 [Workflow Model Session 运行时](workflow-model-session-runtime.md)。

- loader 负责模型资产、设备和精度。
- 推理/分割节点只消费 model session 引用和业务输入。
- AppRuntime 启动时先加载、warmup 和验证全部 loader，完成后才 ready。
- 不同 loader 使用有上限的独立线程并行准备；同一 loader 内仍严格按 load、warmup、
  validate 顺序执行，并且只有全部成功后才统一发布 lease。
- 每个 AppRuntime 独立持有模型；同一 session 串行执行。
- 编辑器 Preview 按 Project + Application 使用稳定 scope，同一应用重复运行只在 Loader 配置变化时换代。
- Preview 同一应用禁止重复提交；删除或禁用 Loader 后必须回收孤立 lease，API 进程保留的 Preview scope 数量必须有硬上限。
- 不允许 node pack 绕过该边界建立服务全局模型池或跨 AppRuntime 共享。
- ObjectStore 中未变化的 Mask 和模板图片可在同一 runtime scope 内复用只读解码结果；
  文件版本变化、scope 回收或 runtime 停止时必须失效，不允许跨应用共享可变图片状态。

节点组的正式边界：

- 节点组是 `WorkflowGraphTemplate.groups` 中的 editor artifact。
- 节点组不注册 `NodeDefinition`，不出现在 node catalog，也没有输入输出端口。
- 节点组不参与 DAG 拓扑排序、不执行、不产生 node record。
- 节点组只在编辑器层批量写入成员节点已有的 `enabled` 字段。
- WorkflowAppRuntime、TriggerSource 和高帧率生产链路只读取普通节点和节点 `enabled` 状态，不读取节点组。
- 组成员按画布矩形完整包含判断；拖动组时组内节点同步移动；调整组框大小后重新计算成员。

当前实现见 [docs/development/workflow-graph-groups.md](../development/workflow-graph-groups.md)。

## 图像交互取参

传统视觉节点的参数编辑需要向 VisionMaster / Halcon 这类工业视觉软件靠拢。ROI、找圆、找直线、找边、模板区域、测量线和标定区域等参数不应长期只靠文本字段输入。

该能力属于 workflow editor 的通用参数编辑能力，不属于某个业务节点或某个应用的专用实现：

- 节点通过本次 Preview Run 的 `debug_preview.interaction.tools[]` 声明参数辅助工具，例如 `bbox`、`polygon`、`circle`、`line`、`grid`、`template-region`、`match-line`、`point-pair` 和 `homography-overlay`；前端不从节点类型名硬编码工具。
- `debug_preview.interaction.controls[]` 的数值调参控件应显式声明正数 `step` 以及有限 `min/max`；ImageViewer 使用同一共享网格对齐规则，缺少 `step` 时才按范围回退，避免调参框和 slider 使用不同有效值集合。
- 节点仍通过稳定的 `parameters` 执行，后端节点不依赖前端交互状态。
- 前端根据节点输入端口、最近一次 Preview Run 输出或当前公开输入解析可用图像，但不在属性面板内显示缩略图。
- 节点底部沿用现有 preview display 显示缩略图；节点参数提供 `debug_image_panel_enabled` 调试图片面板开关，默认关闭，编辑调试时手动打开。
- 双击节点底部缩略图打开统一交互式图片面板；该面板复用现有 ImageViewer / Preview 图片查看基础能力，并增加 overlay 编辑层，支持 pan、zoom、ROI、circle、line、point 和 polygon 操作。
- 用户确认后，前端把图像坐标转换并写回节点参数，例如 `source_points`、`bbox_xyxy`、`polygon_xy`、`line_xyxy`、`angle_deg`、`min_radius`、`max_radius`、`search_bbox_xyxy`、`source_points / target_points`。
- 参数 schema 仍是最终保存源，workflow template 不保存临时鼠标交互状态。生产 runtime 默认不生成调试缩略图，避免 BGR24 / BufferRef / FrameRef 转 PNG/JPEG/base64 的额外耗时；节点必须同时检查 `debug_image_panel_enabled` 和 `execution_metadata.debug_image_panels_enabled`。
- 高分辨率图像要区分节点小预览和交互取参面板：节点小预览在超过 1920x1080 像素量或长边超过 1920px 时自动使用长边 1920px 的 display 图，交互取参面板必须使用原图坐标和原图像素。`适配`、`100%`、缩放和平移只影响显示，不影响写回参数。后续如果需要优化 8K 原图浏览，应扩展 tile / pyramid viewer，而不是把取参图换成缩略图。

优先级：

1. ROI polygon / bbox：用于 crop、perspective-transform、roi-grid-create 和区域规则。
2. Circle：用于 hough-circles、circle-measure、圆孔定位、圆度和半径范围估计；Reference Circle 与 Search ROI 是两个独立参数对象，前者不得覆盖后者。
3. Line：用于 hough-lines、fit-line、找边、角度校正和平行度测量。
4. Template region：用于模板匹配、局部定位和换型参数准备。
5. Geometry：`rotation-correct` 用 line 写回角度，`affine-transform` 用 point-pair 写回三点关系，`undistort/remap` 用 debug preview 检查矫正结果和标定映射。

Line 工具的搜索 ROI、角度容差和搜索框 padding 必须由节点通过 `debug_preview.interaction.tools[]` 声明，例如 `angle_tolerance_deg`、`search_padding_ratio`、`search_padding_min`。前端 ImageViewer 只负责按声明显示方向线、搜索 ROI 和角度范围，并把结果写回节点参数，不在页面层硬编码算法默认值。

### Matching 双图交互协议

ORB、Homography、模板定位这类参考对位节点不应把调试交互伪装成普通 `line` 或 `polygon`。它们需要保留清楚的业务语义，同时复用 ImageViewer 的底层绘制能力：

- `match-line` 表示一条可点选的匹配线，用于写回 `debug_selected_match_ids`，支持多选和再次点选取消，只影响调试高亮和筛选，不改变正式匹配结果。
- `point-pair` 表示人工标记的一组或多组左右图点对，用于写回 `debug_manual_pair_lines_xyxy`，可用于人工校正、验证集记录和后续几何估计。
- `homography-overlay` 表示 Homography 投影框，用于写回 `debug_selected_projection_id`，只影响调试高亮，不改变 `planar-transform.v1` 输出。
- 后端节点通过 `debug_preview.interaction.tools[]` 声明可用工具和 `target_parameters`，通过 `overlays[]` 携带 `kind`、`id`、`target_parameters` 和 `parameters`。前端只按声明写回参数，不猜测节点内部语义。
- 语义 overlay 可复用 `line_xyxy`、`points_xy`、`circle` 等基础图形字段绘制，但 `kind` 必须保留业务语义，避免后续双图 overlay、匹配筛选、手动点对和投影框编辑继续叠临时字段。注意：`points_xy` 是 ImageViewer preview overlay 协议字段，`polygon_xy` 只用于 ROI、regions 等正式节点 payload。
- 这些调试参数只能用于编辑期 Preview Run；生产 runtime 默认关闭 `debug_image_panel_enabled`，不得因为 matching 调试图产生额外 BGR24 编码、数据库记录或节点输出负担。

Preview Run 与图像交互取参要保持边界清楚：Preview Run 负责提供可用图像和节点输出；交互编辑器负责把人工选择转换成参数。大循环或大图 workflow 没有预览节点时，Preview Run 默认不应返回完整 `node_records`，避免大对象复制和数据库记录拖慢调试。

## 与核心模块的关系

### backend-service

- 管理 node pack 注册、版本、启用状态和节点目录发布
- 记录 node pack 与流程模板、部署实例、任务类型之间的引用关系
- 暴露模板校验、保存、读取与后续执行所需的统一节点目录

### workers

- 提供节点执行容器、错误收敛和超时控制
- 确保 custom node 输入输出严格遵循 payload 规则 与端口规则
- 负责在任务执行过程中调用对应节点逻辑

### frontend/web-ui

- 读取统一节点目录并渲染节点面板、参数表单和流程图
- 为节点包配置、状态和错误提供受控展示界面

### contracts

- 定义 NodePackManifest、NodeDefinition、WorkflowPayloadContract 和 FlowApplication 等共用格式
- 避免不同 node pack 自行发明一套不兼容协议

## 安全和管理要求

- node pack 必须声明 capability scope，避免无限制调用平台能力
- 硬件桥接节点包和协议节点包必须声明额外权限和外部依赖
- node pack 必须支持 timeout、disable 和版本回滚
- 节点扩展错误不能直接拖垮后端服务主链路，应通过任务和状态流隔离处理
- 节点日志、错误和版本必须可审计
- 对其他 node pack 的依赖关系必须可说明、可追踪，不能只藏在顶层 import 链里

## 哪些能力优先放进 node pack

- 行业特定协议节点
- 客户定制结果处理逻辑
- 外部触发入口和完成后的数据上报逻辑
- trigger source bridge、listener 和协议到 WorkflowRun 的映射逻辑
- 硬件直连与厂商 SDK 封装
- 特定视觉后处理逻辑
- 模块之间的特殊衔接规则
- 自定义节点、节点组和参数面板

## 哪些能力应留在核心平台

- 任务模型和状态流
- 数据集、模型、部署、流程模板的核心对象模型
- 节点扩展生命周期管理和版本管理
- 节点执行基础框架和流程模板基础格式
- 统一 API、WebSocket 和审计能力

## 推荐后续文档

- [docs/architecture/workflow-json-contracts.md](workflow-json-contracts.md)
- [docs/architecture/system-overview.md](system-overview.md)
- [docs/architecture/project-structure.md](project-structure.md)
- [工业视觉与集成节点](industrial-workflow-nodes.md)
