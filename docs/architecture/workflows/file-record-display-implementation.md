# 通用文件记录与结果显示代码实施清单

状态：待实施。整理日期：2026-09-15。本清单不表示节点、接口或测试已经完成。

需求与数据语义以[通用文件记录、增量汇总与结果显示方案](inspection-statistics-display.md)为统一入口；本文件负责实现顺序、文件范围、验证与完成条件。实现中发现冲突应先修订对应契约和测试，再修改代码，不能靠隐式默认值改变计数口径。

## 固定范围

- 提供可复用基础能力：字段提取 → 独立规则计数 → 任意对象组装 → 指定路径追加 JSONL → 有界读取与增量汇总 → 数值计算 → 字段显示 → 图片栏和大图组合。
- 每次正常完成且有结果的检测调用独立记录。总数来自配置常量，现场为 24 或 80；OK、NG 分别来自配置规则，禁止 NG=总数−OK。盘数和单次整体判定是可选、独立字段。
- 不绑定模型分类名称，不进行条码去重、复检管理，不在通用节点补造缺失槽位。输入计数单位由上游明确。
- 生产记录使用磁盘文件，不建生产数据库表或专用统计服务。文件恢复身份只处理被中断的同一次物理追加，不合并新调用。
- 保持 Runtime/Trigger 同步高性能调用、实例满载拒绝及模型部署调用边界。不引入推理队列、后台等待或模型加载分支。
- Preview 默认跳过正式日志写入；需要验证写入时显式启用并使用测试路径。显示调用只读取权威记录，可以更新自己的派生检查点。
- 第一阶段支持单文件、本机磁盘；不新增多文件扫描汇总、自动轮转、跨文件时间窗口或网络盘保证。已有 CSV 功能保持原样。
- API 保持 v1，App Mode 增加可选配置；既有无角标工作流继续可用。JPEG 和关闭 WebSocket permessage-deflate 的设置保持不变。
- 本次交付只有文档；后续执行本清单时逐步记录实际结果，不提前宣布准确率、性能或长期稳定性通过。

## 步骤与依赖

| 步骤 | 内容 | 前置条件 | 当前状态 |
| --- | --- | --- | --- |
| S00 | 契约、样例和验证基线 | 设计文档 | 待实施 |
| S01 | Count by Rules 与对象链路 | S00 | 待实施 |
| S02 | JSONL 文件协议与恢复 | S00 | 待实施 |
| S03 | Append JSONL / Read JSONL 节点 | S02 | 待实施 |
| S04 | File Summary 增量归约与检查点 | S03 | 待实施 |
| S05 | Value Display 与配置编辑 | S00 | 待实施 |
| S06 | App Mode 绑定与显示上下文 | S05 | 待实施 |
| S07 | 图片栏、大图与刷新生命周期 | S06 | 待实施 |
| S08 | 通用示例图与完整链路 | S01、S04、S07 | 待实施 |
| S09 | 真实环境、性能与交付核对 | S08 | 待实施 |

以下路径均相对仓库根目录。“拟新增”表示设计落点，编码前按邻近模块约定核对最终名称；不能把拟定路径当成已有实现。每步完成后检查差异、运行对应验证、记录结果，门禁通过后再推进依赖步骤。

## S00：固定契约和验证基线

1. 记录当前 Git 状态、目标 App 的草稿/发布版本、Runtime 绑定版本和现有输入输出。保留同一真实图片与同一模型配置作为耗时对照；不通过生产追加制造基线数据。
2. 为规则、文件提交元数据、写意图、游标、汇总检查点、Value Display 正文及 App Mode overlay 定义 v1 schema、必需字段和错误类型。区分业务对象与内部文件协议字段。
3. 将单条记录大小、批量记录数、读取字节数、执行时间、字段数、文本长度和精度上限集中定义，给出合法默认值与边界测试。时间预算按完整记录之间检查，不能以截断记录满足预算。
4. 明确数值和空值：整数精确累加并检查前端安全整数范围；拒绝 bool 冒充数值、非有限浮点与隐式字符串转数字；零分母由工作流处理为空值。
5. 统一来源上下文：文件 generation、已处理 sequence、snapshot_revision，图像与字段使用同一来源。游标含来源身份与完整行位置；规则摘要包括过滤条件、归约规则及相关语义版本。
6. 写出下文验收矩阵的输入/预期结果。记录写入成本与原推理成本分别测量，不用单次页面体感替代链路测量。

检查入口：`backend/contracts/workflows/`、`backend/nodes/core_nodes/support/`、`backend/service/application/runtime/io/`。新增 schema 应放在对应边界，不建立横跨前端、模型和文件服务的“大统计模块”。

完成条件：端口、字段、默认策略、错误与样例一致；没有待定的业务口径。工程参数的默认数值在本步确定并记录，不留到各层自行决定。

## S01：规则计数和通用对象组装

文件范围：

- 拟新增 `backend/nodes/core_nodes/logic/collections/count_by_rules.py`。
- 复用 `backend/nodes/core_nodes/support/condition_expression/`，必要的递归校验放在共用支持层。
- 核对既有 List Filter、字段提取、Object Field/Create/Merge、Number Operation；不重复造提取或对象模板语言。
- 核对 `backend/nodes/core_nodes/__init__.py` 自动扫描与 `backend/nodes/core_catalog.py` 契约。辅助模块放在 support 或符合扫描排除约定的位置，避免被误识别为节点。

实现动作：

1. 验证 `rules=[{key, condition}]`、唯一非空 key 和可选 fallback_group；进入列表循环前递归验证条件，包括空列表输入。
2. 复用现有条件 DSL，一次遍历计数。单项命中多个分组明确失败，同组多个备选条件只计一次。
3. 返回 counts、input_count、matched_count、fallback_count、unmatched_count。fallback 只处理实际输入项，不能增加输入项数量。
4. 节点 schema 提供可编辑规则行和字段说明；路径可手动填写，不依赖实时模型样本。

验证：任意类别名称、多值规则、缺失/null、未知值、空列表、非法规则、重叠规则、显式 fallback。验证计数恒等式，并用 `总数=24、OK=20、NG=2、未匹配=2` 证明无补差行为。共享条件解释器如有改动，回归已有 Filter List 等调用方。

完成条件：节点目录可发现，字段提取和对象组装能够得到任意结构的单次增量；没有生产字段硬编码，没有改动模型分类判定。

## S02：受管理 JSONL 文件协议

文件范围：在 `backend/service/application/runtime/io/` 下新增聚焦 JSONL 的协议/读写模块；复用 `path_write_coordinator.py`、`atomic_files.py`，核对 `write_journal.py` 的执行身份与恢复边界。新增模块不依赖 Vue、数据库或模型。

实现动作：

1. 统一解析并规范化日志、固定后缀元数据、写意图路径；拒绝碰撞。首期不接管已有非空、缺少管理元数据的普通 JSONL。
2. 锁外完成对象校验、UTF-8 严格序列化和大小检查；锁内使用非等待获取方式处理同路径写入，冲突明确报错。不修改既有全局锁策略。
3. 写入顺序固定为：核对并恢复旧意图 → 原子保存本次写意图 → 追加完整行 → flush/fsync 日志 → 原子发布新的提交元数据 → 清理已完成意图 → 返回提交回执。
4. 写意图至少记录操作身份、起始偏移、长度、摘要。恢复时以提交元数据和实际尾部共同判断：已提交则不再追加；完整未提交尾部经校验及持久化后完成提交；部分尾部只允许恢复到已核对的原提交边界。摘要冲突、提交边界以前损坏或未知尾部明确失败。
5. 元数据发布是可见提交点。提交前失败不能报告成功；提交后意图清理失败不得让调用方误以为可以重新追加，保留可识别的已提交状态供下次恢复清理。异常发生在原子替换结果不确定处时，先读回验证，不能盲目重写。
6. reader 固定一次提交边界，仅读取已提交区间，常规读取不持有生产写锁。校验实际文件与来源身份；截断、替换或中间损坏明确失败。
7. snapshot 模式只面向稳定外部文件，显式检查读取前后身份/边界；不为任意外部并发写入提供保证，不从 managed 自动降级。

验证：真实跨进程同路径竞争、连续完整行、同大小文件替换、半行尾部、坏行；对写意图前后、半写、日志 fsync 后、元数据发布前后、回执前分别注入中断。验证恢复结果确定且已提交记录不被截断。权限、磁盘写入失败和锁冲突有明确错误。

完成条件：同一物理追加恢复不重复；相同内容的新调用仍正常新增。测试结论限定到本机文件系统和进程中断，不宣称覆盖任意硬件掉电。

## S03：Append JSONL 和 Read JSONL 节点

拟新增文件：`backend/nodes/core_nodes/io/output/storage/jsonl_append_local.py`、`backend/nodes/core_nodes/io/local/jsonl_load_local.py`。节点封装只负责参数、payload、执行控制和协议适配，恢复逻辑统一调用 S02。

1. Append 接收对象 value，目录/文件名支持既有输入绑定、路径模板和权限规则；一次执行固定路径。返回 file、generation、sequence、committed_offset、write_state 回执。
2. 明确写入开关和 Preview 策略。默认预览不写，跳过状态不能伪装成已提交；显式测试写入应使用独立目录。
3. Read 接收 file 或 local_path、source_mode、cursor 和预算，输出完整 records、next_cursor、snapshot_end、has_more 及明确的文件状态。
4. 校验 cursor 与源文件身份，单条超限直接失败；无新增数据保持游标，不重放旧记录。missing 与损坏分开处理。
5. 复用既有取消/timeout 控制，在受控边界检查；中断不能留下被当成成功提交的半条数据。

验证：输入绑定、路径碰撞、对象而非 JSON 字符串、Preview 跳过、显式测试写入、缺失文件、重复读取与超限；既有 Append CSV/Save JSON 行为回归。

完成条件：节点目录和执行器可调用；正常回执与磁盘记录逐条对应，文件错误不会被转成成功空结果。

## S04：File Summary 与可恢复检查点

文件范围：拟新增 `backend/nodes/core_nodes/io/local/file_summary.py`；纯归约器放在节点 support，游标和检查点 IO 复用 S02 所在支持模块。既有 Array Summary 使用浮点转换，不能直接作为长期整数计数器。

1. reducers 配置 source_path、operation、output_key、numeric_type、missing_policy，支持 sum/count/min/max/last；明确记录过滤条件。输出 snapshot 包含 totals、latest、source、complete、status。
2. 在读取开始固定 snapshot_end。一次调用受预算限制；complete=false 时持久化进度，下次明确调用继续，不自己循环排队或启动后台任务。
3. 检查点原子保存来源身份、游标、规则摘要、累计值、latest 和 revision。无新增数据不得反复累加或无意义重写。
4. 读取和计算在检查点提交锁外进行；提交时以独立短锁核对原 revision，不允许旧计算覆盖新状态。同检查点冲突明确失败，不后台重试。
5. 规则变更或派生检查点失效走有界重建；权威日志损坏走错误。重建期间标注 loading，不将不完整累计呈现为最终数。过滤无匹配、文件缺失和空文件按设计返回空聚合。
6. 检查点写入失败不发布假成功的新检查点。下一次从原已提交游标计算，累计与游标始终一起提交。

验证：增量结果与独立全量参考算法一致；重复读、重启、检查点丢失/损坏/提交失败、规则修改、无新增数据、持续追加下固定边界追赶、整数溢出、空值和过滤。大日志单次处理有界，不随历史增长无限占用内存。

完成条件：显示调用任意重复不增加生产记录，累计无丢失/重复，慢显示读不长期占用写端锁。

## S05：Value Display 与参数编辑

文件范围：拟新增 `backend/nodes/core_nodes/io/preview/value_display.py`；核对 `backend/service/application/workflows/preview/display.py`、`backend/service/application/workflows/runtime_preview.py` 及 `frontend/web-ui/src/workflows/workflow-editor/preview/useWorkflowPreviewDisplays.ts`。

1. 输入 value、可选 context，fields 配置路径、标签、格式、精度和受控状态映射。输出 body 的 type 为 value-display，有序字段携带原始值；不把整个原始对象泄露到显示正文。
2. 在既有显示契约、Preview 流式捕获、Runtime 完成捕获及前端类型分派中接入新类型。复用现有连接，不新增 WebSocket 或改变响应结果语义。
3. 属性面板使用可添加/删除/排序的字段行，支持任意手写路径，校验空路径、重复规则 key、格式与精度。没有预览样本也可完成配置。
4. 新增通用字段展示组件，统一格式化整数、数值、百分比、文本和状态。null/缺失显示“—”；未知状态中性显示，状态同时有文字；限制宽度和文本长度。

验证：字段顺序、任意标签、零值/false/null、未知状态、0.9583→95.83%、大整数、错误配置、Preview 和 Runtime 均显示；不依赖生产文件或部署模型来运行组件测试。

完成条件：显示节点可独立使用，没有文件读取、生产计数、图像重编码或自行刷新副作用。

## S06：App Mode 配置与来源上下文

文件范围：

- `backend/contracts/workflows/workflow_app_mode.py`。
- `backend/nodes/core_nodes/io/image/image_preview.py` 及关联显示契约。
- `frontend/web-ui/src/workflows/workflow-editor/app-mode/workflow-app-mode.ts`。
- `frontend/web-ui/src/workflows/workflow-editor/components/WorkflowAppModeConfigDialog.vue`。

1. 图片项新增可选 overlay：Value Display 的 node_id、output_port、固定 top-left。fields 只在 Value Display 配置。
2. 对话框增加结果显示选择器，校验引用节点、端口、类型与启用状态。一个字段显示可绑定多个图片，不强制生成独立卡片。
3. 保存、读取、导出/导入、发布、不可变 App 版本和 Runtime 选版均保留并验证绑定；核对现有转换函数，防止新字段被过滤掉。
4. Image Preview 新增可选 presentation_context，与 Value Display.context 连接同源输出。仅传显示元数据，不改变 image-ref 所有权和图像内容。

验证：配置完整往返、旧配置无 overlay、同源复用、删节点/错端口/禁用节点、发布后 Runtime 可用。API 仍为 v1，不进行数据库迁移。

完成条件：后端与前端契约一致；可配置来源关联，无节点顺序或目录最新文件配对假设。

## S07：图片栏与大图共享显示

文件范围：

- `frontend/web-ui/src/workflows/workflow-editor/components/WorkflowAppModeDisplayGrid.vue`。
- `frontend/web-ui/src/workflows/workflow-editor/preview/useWorkflowPreviewDisplays.ts`。
- `frontend/web-ui/src/workflows/workflow-editor/components/WorkflowPreviewViewers.vue`。
- `frontend/web-ui/src/shared/ui/components/ImageViewer.vue`。
- S05 字段组件及必要的通用显示类型。

1. 图片栏左上角叠加字段组件，宽度受容器限制，可收起，不覆盖工具栏；不使用数字滚动或页面切换动画。
2. Shared ImageViewer 增加可选通用信息插槽，WorkflowPreviewViewers 注入同一字段组件。图片缩放、平移、适配和 100% 下，信息固定在视口左上角、工具栏下方。
3. 以显示 run 和来源 generation/sequence/revision 组织图片+字段成组更新。新图加载期间保留旧图与旧字段并标注更新中，或共同占位；禁止新数字配旧图。
4. 双击打开、缩略图升级源图、活动图片自动刷新、切图和关闭均携带/释放对应上下文。保持既有图片对象身份、Object URL 和资源所有权规则，不混用几何 overlays。
5. 缺图、来源不匹配、断线和迟到回调有明确状态，旧事件不能覆盖新结果。信息层普通区域不拦截拖动，收起按钮单独处理事件。

验证：小图与大图字段值/颜色/来源一致；四栏不同组、共享字段、双击、缩放、拖动、关闭重开、持续刷新、断线、延迟图像加载、缺失图像。回归 ROI/Mask/测量及未绑定信息层的通用查看器。

完成条件：显示不修改像素，不重复加载/编码图片，无上次结果残留和新旧来源混合。

## S08：组装完整示例与现场配置准备

1. 先在隔离测试目录和测试图验证：规则计数 → 字段提取 → Object Field/Create 组装任意 JSON → Append JSONL。生产总量常量只在图配置中出现。
2. 检测、判定和必需 Save Image 完成后汇合到一次追加，完成输出依赖回执。检查图分支，禁止槽位循环、多分支各追加整盘 N。文件提交以后不放置会影响“检测完成”含义的必需业务步骤；普通文件提交不具备跨节点回滚能力。
3. 记录 images 使用本次保存返回的持久引用；显示图使用同一条 latest 记录载入图片，替换独立目录各取最新文件的配对方式。
4. File Summary → 提取 totals/latest → 通用算术计算良品率 → Value Display，配合 Image Preview 同源上下文。显示刷新复用既有 Runtime/Trigger 调用，不由显示节点启动轮询。
5. 为治具/塑盒分别准备文件路径、检查点路径、24/80 常量、实际类别映射和显示绑定；明确累计从新日志起点开始。旧单次 JSON 不自动补录，避免来源重复和口径不一致。
6. 按既有草稿、发布、Runtime 选版流程接入；改现场图前保留可核对版本。核对目标检测 App `workflow-app-20260910030059`、结果 App `workflow-app-20260910030132` 的当时实际配置，不能盲目覆盖已发生的新修改。

完成条件：从追加文件到页面数字可逐条核对；结果显示图重跑不写生产日志；同次结果和图片一致，现有调用输入输出保持兼容。

## S09：验证、性能与交付记录

| 验证项目 | 必须成立的结果 |
| --- | --- |
| 多类别映射 | 不同任意标签可分别进入 OK、NG；重叠报错 |
| 独立计数 | N=24、OK=20、NG=2、未匹配=2，不将 NG 改成 4 |
| 24/80 场景 | 23+1、79+1、全 OK，以及上游显式提供缺槽/未知项的映射正确 |
| 新调用重复输入 | 同图/同条码两次正常完成，总量增加 48/160，不去重 |
| 失败与恢复 | 无正常结果不追加；物理追加中断恢复不重复；满载拒绝保持原行为 |
| 显示重复执行 | 多次读取、刷新、断线重连不增加总数；检查点恢复结果一致 |
| 图片关联 | 单次状态、累计和图片同源，小图/大图一致，迟到结果不覆盖新结果 |
| 空数据和重建 | 空值不装作 OK/0，部分汇总明确 loading，坏日志明确失败 |
| 高性能边界 | 未接记录节点的 Runtime/Trigger 行为不变；启用记录时单独量化磁盘成本 |

测试组织：规则、文件协议、节点、归约器使用聚焦 pytest；参考 `tests/test_node_catalog_registry.py`、`tests/test_node_catalog_taxonomy.py`、`tests/test_workflow_app_mode.py`、`tests/test_workflow_display_and_response_nodes.py` 及既有 Preview/Runtime 测试增加覆盖。前端围绕 App Mode 配置、DisplayGrid、useWorkflowPreviewDisplays 和共享查看器做行为验证，不新增只复述实现的测试。

Python 测试先 `conda activate amvision`，使用当前环境 `python -m pytest <本步测试文件>`；需要隔离时使用 `--basetemp=.tmp/file-record-display-<阶段>`。前端按 `frontend/web-ui/package.json` 当时已有命令运行对应测试、类型检查和构建，不假设不存在的脚本。

真实验证使用既有部署模型及已确认图片目录 `data/files/developer/图片/3570`，仅在测试记录路径累计。真实 NG 需要人工确认样本；没有样本时将规则合成测试与实际模型验证分开报告，不宣布真实 NG 精度通过。

性能验证采用约 3 分钟短测，固定输入、部署实例数、调用方式和显示频率，分别记录原链路、启用追加、并行显示读取/Preview 的样本数量与完成数、拒绝数、端到端 p50/p95/p99、追加耗时、读取耗时和内存/句柄/共享槽位回收。样本不足不宣称 P99 达标，不凭短测保证长期稳定。满载拒绝单独统计，不引入等待来掩盖容量行为。

.NET SDK 首先检查输入输出契约是否仍一致；仅新增可选显示元数据时不要求改 SDK 协议。使用既有 Console/Trigger 示例做兼容性验证，若发现实际反序列化问题再按证据修复，不能预先扩展数据面。

最终核对代码差异仅涉及本清单能力，同步节点文档、配置样例、错误说明和验证记录。完成且确认没有本任务进程使用临时目录后清理本任务临时产物；不自动修改版本号、提交 Git 或把未经核对的测试图替换正式运行图。

## 执行记录格式

每步实施后在本文件或关联验证记录中填写：实际文件、契约变更、检查命令与结果、未覆盖范围、下一步条件。未通过时保留失败结论及原因，不把“已编写代码”标成“已验证”。

业务语义以设计文档为准；实现进度以经过验证的步骤状态为准，两者不能混用。
