# 3D Metrology 设计与实施基线

## 1. 状态与阅读约定

状态：**M0 收口；M1、M2 与 M3.1–M3.3 共十八节点已内部接通，R1–R4 修复已提交，三维契约统一 v1。R5 A 联合 ROI、B 本次 pose/U/V 已实现；C 动态截面尚未实施，十二钢片和两半圆尚未完成同定义实测验收。生产超时、容量和发行 profile 仍未验收，节点继续隐藏；M3.4、M3.5 未完成**。设计依据见 [ADR-0015](../decisions/ADR-0015-3d-metrology.md)，修正依据见 [真实工件审计](3d-metrology-audit-20261024.md)，当前进度见 [R4 实施记录](3d-metrology-r4.md)和 [R5 配方设计](3d-metrology-r5.md)。历史证据见 [M3.3 实施记录](3d-metrology-m33-acceptance.md)、[M2 几何节点](3d-metrology-m2.md)、[M1 真实发布运行](3d-metrology-m1-published.md)、[M1 I/O](3d-metrology-m1-io.md)、[输入适配](3d-metrology-m1-input.md)、[运行引用与生命周期](3d-metrology-m1-runtime.md)、[资产与保存导出](3d-metrology-m1-assets.md)、[节点与资源 API](3d-metrology-m1-nodes.md)和[传输与界面](3d-metrology-m1-transports.md)。下文历史源码检查和规格不等于全部能力已实现。

M0 的代码核对与契约设计已收口，M1 已按后续授权开始 I/O 修复，未注册空节点。已确认每次 Workflow 调用输入完整点云，同时支持文件和同机内存二进制数组，不接收连续实时点云流；每次提交载荷最大 1 GB，不是运行内存上限。生产调用不自动保留完整点云，配方显式选择保存，结果保留数值和有界显示证据。最低机器内存、目标同时运行数和单次时限未确定，不填默认值。

此前已核对 LocalBuffer、文件入口、Workflow、Preview、SDK、计量资源、规则读取方和发行边界，并补齐 M1 六节点、两入口、三维显示与持久引用规格。精度边界保持：**当前样本按 float32 保存和传递，外部文件按声明保留精度，算法按需要局部使用 float64**。PLY 基于 trimesh 5.1.1，PCD 基于 pypcd4 1.5.1；受控修复仅本项目使用，不提交上游。XYZ 使用现有 NumPy，Open3D 0.20.0 保持几何职责。当前固定 wheel 为 `trimesh==5.1.1+amvision.2`、`pypcd4==1.5.1+amvision.2`；前者含 M3.3 已授权的最小矩形受控扩展，后者修正不可压缩数据的 LZF 输出容量。完整原始 ASCII 样本和双平台读写结果见实施记录。已扩展现有 Scope、Snapshot、worker 收尾和计量资源服务，仍未启用节点或发布三维 profile。RPly 自建适配、meshio、plyfile、自写解码器均不引入。

本文是三维测量跨模块设计与实施步骤的总基线，不是当前节点使用手册。阶段细化从本文件链接，不维护平行架构。设计表不等于相应 API 或页面已可用；实际实现、验证和生产启用状态以本节及分批记录为准。未实现或未验证的能力不进入可用 Catalog，不以占位节点表示支持。

2026-10-23 阶段记录：M3.1 height-query/measure-step 和 M3.2 extract-boundary/fit-line/fit-circle 均接入内部 Catalog、GraphExecutor 和 Vue 编辑器，当时共十五节点。见 [M3.1 实施记录](3d-metrology-m3-height.md)、[M3.2 实施记录](3d-metrology-m3-boundary.md)。CloudRuntime 有序源点/生成顶点、边界证据保存恢复及三维读取方 v2 已同批接通，不改变原始行号语义。旧三维资产保留且需重建，不执行旧格式；二维资源、数组传输 ABI 与 Workflow 发布系统不变。下文 M0/M1/M2 历史表描述设计演进；涉及运行来源、拓扑及保存/显示的当前逐字段规格以 M3.2 第 5 节为准。精确量值仍须显式 Preview 完整重算，支持域外无效、不外推。组件和图执行通过不等于完整页面、真实新配方发布或生产发行验收。

M3.3 的实施规格见 [长宽、边间距与孔径设计](3d-metrology-m3-dimensions.md)。2026-10-24 已补 M3.2 真实发布/页面验收，完成矩形库扩展、三个尺寸节点、测量证据 v1 和前端，当前共十八个内部节点。边间距域外/缺口无效、不外推；最小矩形并列尺寸一致时保留量值并标识方向歧义；孔径直接消费 fit-circle 的 CircleFeature，不重复拟合。Windows 与 WSL Ubuntu 原生文件系统的历史定向组合各 362 项通过，见[实施记录](3d-metrology-m33-acceptance.md)。生产预算仍空缺，节点不启用；先完成本轮审计 R1–R5 修正与真实配方验证，再继续 M3.4，不能把内部验收等同于生产或现场计量验收。

2026-10-24 修复进度：公共参数分发、严格输入错误分类和有限连续边段选择已完成，内部包 `0.1.10`；边界方法升 v2，旧方法资产只读且需重建。Windows 501 项、Ubuntu 499 项（另 2 项 Windows .NET 条件跳过）、前端 209 项通过；双平台完整样本和空白页面至 App Mode 发布运行已验证。详见[本轮修复记录](3d-metrology-repair-20261024.md)，开头所列真实工件审计保留为修复前依据，不代表上述代码缺陷仍未处理。十二钢片/两半圆的同定义有效量值验收仍未完成。

R4 已实现两种显式基准模式：基准也需实测支持，或基准平面延伸并由配方给出最大距离；被测面始终需要真实支持，有基准覆盖但质量失败不能改走延伸。R4 内部包为 `0.1.11`，R5 A 已更新为 `0.1.12`；契约、证据、前端及实际验证范围见 [R4 实施记录](3d-metrology-r4.md)及 [R5 A 验收](3d-metrology-r5.md#75-a-批次实施与验收2026-10-26)。

2026-10-25 R4 实施基点为 `57070088`，十八内部节点不增加。按本轮确认，全部三维数据契约和方法统一 v1，不保留旧读取/降级分支；其他平台协议不动，旧三维文件保留，使用前重建。下文 M0/M1 历史规格中的格式升级计划由 R4 当前契约替代。下一步为 R5 的同定义工件配方，再进入 M3.4/M3.5；生产参数和节点隐藏边界不变。

2026-10-25 R5 规划核对基点 `23ed5f47`：已对照完整源文件摘要、手工计算脚本和结构化报告，列出十二钢片/两半圆的支持范围、算法差异、前端操作和双平台验收步骤，见 [R5 配方设计](3d-metrology-r5.md)。Q1–Q6 已确认：沿台面法向同线测距、严格实测边界、五 ROI 联合基准、显式工程支持 ROI、钢片本次交点中间高度/半圆 0.25 mm、固定台面 U/V 查询。两个等高参数只用于本工件。源云/特征保留源坐标，设计复用 pose 解析查询与截面，下游继承实际截面；不新增资源、脚本或发布系统。具体 XYZ/U/V、质量和测试预算仍需审核冻结；接线扩展尚未实现，先核对 A_top_L/S1，再扩展全部对象和双平台真实发布验收。该轮只更新文档，不新增算法/节点或运行验收，生产仍不启用。

2026-10-26 R5 A：已扩展现有 ROI 并集和编辑器，沿用只读子集、原始行号、预算、取消和 Scope 回收；参数/端口、资产方法及显示依赖同批核对。Windows 与 WSL 原生目录的完整文件逐行选择一致，真实发布/Trigger 与页面 Preview 已验证，详见 R5 第 7.5 节。下一步实施 B/C 的本次 pose 与动态截面接线，再冻结 A_top_L/S1 工程窗口；没有冻结生产参数或启用节点。

2026-10-26 R5 B：内部包 `0.1.13`，height-query/方向 measure-step 接本次位姿及固定 U/V，共用原位姿支持准入和 R4 数值内核；持久证据保存配置、源身份和解析线。旧开发配置需重建，无兼容分支。完整 14,745,099 点输入在双平台验证，页面改用真实百万点有界显示，修正大 Base64 校验、旋转轴和窗口重置问题，补缩放/平移/六向视图与详情展开。具体测试及限制见 [R5 第 7.6 节](3d-metrology-r5.md#76-b-批次契约与验证2026-10-26)。下一步为 C，生产继续隐藏。

已有样本脚本是独立探索产物，未接入 amvision。本文只保留可复用的需求、证据边界和回归参考，不复制会话日志、原始点云或一次性脚本。算法测试通过、工程闭环完成、真实计量准确度通过和生产验收通过是四种不同状态。

阅读顺序：第 3 节了解复用边界 → 第 14 节了解各阶段交付的测量功能 → 第 7 节查看具体节点/算法 → 第 9 节查看界面与操作 → 第 15.5 节查看实施前剩余条件。第 5、6、8、10、11 节提供对应的数据、数学、结果、资源和依赖详细依据，不是需要另建的五套系统。实施前还须阅读 [节点系统](../architecture/workflows/node-system.md)、[节点分类](../architecture/workflows/node-taxonomy.md)、[App 输入](../architecture/workflows/app-inputs.md)、[App 版本管理](../architecture/workflows/app-versioning.md)和 [Node Pack manifest](../nodes/node-pack-manifest.md)。

执行计划入口：第 4.1 节是单次生产调用，第 4.2 节是配方与现场操作，第 14 节按功能列出实现、复用、扩展、界面和验证，第 15 节区分已经明确的设计与真实剩余项。M1 就实现点云读写和基础处理节点，M2 实现基准几何，M3 实现常用尺寸；不是先重建平台再开始算法。流程设计、代码已实现和实测已通过分别记录。

## 2. 目标、范围与非目标

### 2.1 产品目标

建立通用工业三维测量能力，覆盖点云、深度、标定高度和轮廓数据的输入、预处理、定位、特征提取、几何尺寸、形状分析、公差判断及交付。采用现有节点和 Workflow 体验，不建立特定客户、工位、产品或相机的专用平台。

显示名称固定为 **3D Metrology**；拟定包 ID 为 `metrology3d.nodes`，Python 包目录为 `custom_nodes/metrology3d_nodes/`，节点前缀为 `custom.metrology3d`。`pointcloud_nodes` 不作为后续命名。

以下能力全部属于设计范围，按阶段完整交付，不用“基础版”结果冒充高级能力：

- 单点/指定位置高度、整体高度、双区域相对高度与台阶差。
- 长宽、孔径、圆心、槽宽、间隙、边缘到孔中心距离和夹角。
- 平面度、平行度、垂直度、翘曲、圆度及表面偏差。
- 凸起、凹坑、崩边、截面、圆弧、圆角及曲率分析。
- 投影面积、表面面积、基准上体积和闭合实体体积。
- 与参考点云、网格及标准 CAD 的比较。
- OK/NG/INVALID、质量信息、三维尺寸标注、追溯、协议输出和 SPC 集成。

### 2.2 范围边界

- 采集 SDK 是 Camera provider/受控设备扩展的职责；文件读取、数据转换和计量不依赖具体设备。
- 不内置相机、PLC、IO 驱动到平台核心，不为三维重建一套协议或数据库节点。
- 不把点云测量样本伪装成 YOLO 训练数据集，也不要求先创建 ModelVersion/ModelBuild。
- 不改变现有模型训练、推理数值或 Deployment 生命周期。需要 AI 定位时通过现有部署网关显式调用。
- 不实现任意 Python Script 节点，不直接复制参考软件 API，也不把 CloudCompare 作为生产运行依赖。
- 当前交付平台为 Windows x64 和 WSL Ubuntu x64；业务契约不绑定操作系统。macOS 保留架构适配空间，本轮不宣称已支持或验收。
- 不以“完整实现”宣称覆盖所有 GD&T 标准条款。每一种正式评价方法需要明确适用条件、算法和独立验证。

## 3. 已有实现与复用边界

| 组成 | 已核对的现状 | 三维实施要求 |
| --- | --- | --- |
| Node Pack/Catalog | 已有 manifest、分类、handler、参数 schema、payload 和 timeout 管理 | 沿用，不建立第二套注册系统 |
| Preview/Workflow Runtime | 已有执行作用域、取消、超时、generation 与进程回收 | 补齐三维资源支持，不创建每节点进程 |
| Workflow App 发布 | 已有不可变版本、依赖快照、Runtime 选版、回滚和 Run 追溯 | 直接复用；新增点云资源引用和确有必要的依赖执行检查，不建立第二套版本管理 |
| 通用数值 | `NumericItem`/`NumericTable` 已有单位、有限数或 null、valid、reason | 继续使用 `numeric-table.v1`，不复制成三维专用数值表 |
| 通用规则 | `core.rule.check-limits` 按配置检查必检集合；汇总 state 只有 ok/ng | 统一补齐 INVALID 与各消费者，不在新包中另建判定器 |
| 二维几何与显示 | `metrology.py` 的图像身份、二维特征、标定及预览契约有二维约束 | 三维使用独立版本化几何，不把 tuple 长度或图像字段偷偷改成三维 |
| ObjectStore/文件输入 | 已有文件快照与 HTTP 文件输入边界 | 复用受控文件资产、内容摘要、发布引用与删除检查 |
| 计量资源内容 | `MeasurementResourceContent` 当前仅接受 planar-calibration / localization-template | 三维资源需要显式内容契约和版本变更，不能直接塞进现有二维资源 |
| 执行期资源 | `ResourceScope` 已有登记、幂等关闭和逆序释放 | 复用生命周期边界；数组借用、派生引用及跨进程传递仍需独立设计和验证 |
| LocalBuffer/高速 Trigger | 正式数据面承载图片，小参数走已有结构化协议 | 不将点云、TIFF 文件或普通二进制冒充图片 |
| PLC/HTTP/数据库/保存 | 已有独立交付节点 | 输出小型数值/规则结果，扩展必要序列化，不重复连接管理 |
| 前端 | Vue 3、Catalog 驱动参数、Preview/Runtime 显示与受控编辑扩展 | 增加共享三维查看与参数交互，不按节点 ID 堆专用页面 |

代码事实来源：

- [通用测量契约](../../backend/contracts/workflows/metrology.py)。
- [限值判断算法](../../backend/nodes/core_nodes/support/measurement.py)与 [Check Limits 节点](../../backend/nodes/core_nodes/logic/rules/check_limits.py)。
- [OpenCV 包结构示例](../../custom_nodes/opencv_nodes/manifest.json)。
- [现有图片 BufferRef](../../backend/contracts/buffers/buffer_ref.py)。
- [现有计量资源内容](../../backend/contracts/workflows/measurement_resources.py)与 [统一资源作用域](../../backend/service/application/runtime/resource_scope.py)。

拟定分层：平台 contracts 保存跨包数据/身份契约；平台 application 管理资产、发布、预览交付和资源生命周期；`metrology3d_nodes/shared` 保存包内算法、适配器和质量函数；`categories` 保存薄 handler、schema 与目录定义；前端共享 viewer/编辑组件消费类型化数据。Core 不 import 新包，组合工具不调用其他 handler。

### 3.1 本次新增的内容与常用说法

3D Metrology 是现有 Node Pack 体系中的算法包：节点定义进入现有 Catalog，在现有 Workflow 连线，通过现有 Workflow App 发布，由现有 Runtime 执行。App Mode 是同一已发布 App 的操作视图，不是新的 Node App 产品、发布单元或执行器。

| 说法 | 在本次工作中的具体含义 | 复用或扩展边界 |
| --- | --- | --- |
| 格式可实现性、依赖锁定 | 确认选定库版本能否正确读写约定的 PLY/PCD/XYZ 字段，然后锁定实际验证版本 | 扩展现有依赖/发行清单，不实现另一套解析库 |
| 数据契约 | 规定节点之间的坐标数组、单位、坐标系、属性和失败状态 | 新增三维类型，数值表继续复用 NumericTable |
| 所有权、生命周期 | 明确谁持有大数组、谁借用、何时释放，取消和崩溃后谁负责收敛 | 扩展 LocalBuffer/ResourceScope，不新增 Broker 或进程管理器 |
| 三态 | 合格 OK、超差 NG、无法判定 INVALID；不等于任务运行状态 | 在既有规则和结果记录中表达，不另建公差引擎 |
| 结果读取方（原称消费者） | 显示或转发结果的表格、记录、SDK、PLC、HTTP、数据库等模块 | 只更新实际读取变更字段的模块，不新建服务或连接 |
| 发布执行检查 | 核对已发布依赖与实际加载节点实现是否一致 | 复用已有发布、启动和恢复入口；不是重新做 AppVersion |
| 资源格式升级 | 原有资源格式不能表达点云时增加显式格式版本和引用映射 | 不自动迁移训练数据、模型或全部 Workflow，不覆盖历史结果 |
| 验证 | 独立几何真值、坏输入、页面操作、资源释放和双平台测试 | 按本步影响范围执行；不重复无关模型 P99 或长稳 |

发布版本、节点包版本、数据格式版本分别记录配方快照、算法实现和字段解释，不能相互代替。现有发布能力见 [app-versioning.md](../architecture/workflows/app-versioning.md)；第 8.6 节仅描述共享语义变更时的执行检查与受影响配方处理。

## 4. 通用处理流程与节点粒度

```text
外部采集 / 受控文件
  → 输入校验与单位/坐标规范化
  → 有效点、去噪与 ROI
  → 基准建立 + 工件定位
  → 特征提取、身份匹配与显式配对
  → 指定定义的几何测量
  → 数值/质量/证据
  → 通用必检与公差规则
  → 三维显示、文件、PLC、HTTP、数据库、SPC
```

六阶段是可组合的工程流程，不是要求每个工作流必须串行调用所有节点。允许同一基准分支服务多个测量工具，允许 ForEach/Parallel 复用已有执行语义。算法层不因通用化而要求每个点、每个尺寸都放一个节点。

1. 基础算子：读取、ROI、变换、拟合、几何关系等单一可预测操作。
2. 常用工具：高度查询、孔测量、槽测量、表面缺陷等，复用基础算法并输出透明的中间证据。
3. Workflow/Template：产品配方、特征数量/身份、ROI、测量定义、公差、分组和交付策略。

图、节点参数、输入绑定、资源和方法版本共同构成可复算配置。每个算法节点必须列明数据类型、单位、输入前提、输出、失败原因、资源成本及取消安全点。

### 4.1 单次生产调用的完整流程

下表是目标流程，不代表当前三维链路已实现。首次发布/启动先通过执行身份准入；常驻 worker 的每次调用复用已验证的 revision/generation，不逐次重算整包代码摘要。文件和数组两条入口在三维引用处汇合，后续算法不依赖来源文件格式。

| 步骤 | 输入与动作 | 输出及负责边界 | 失败/资源要求 |
| --- | --- | --- | --- |
| R01 选择配方 | 选择已审核 AppVersion、资源版本和方法；Runtime 启动检查实现身份 | 既有发布服务、Runtime lifecycle 和 worker 确认同一执行版本 | 旧发布需审核、依赖不匹配或资源缺失时拒绝；不进入大数据解析 |
| R02 建立调用 | 校验项目/端点权限、输入绑定、调用身份与完整载荷描述 | 现有 API/Trigger/SDK，形成 run/observation 关联 | 缺必需输入、错误契约或无权限立即拒绝，不靠默认值补齐 |
| R03-F 文件输入 | 接收完整 PLY/PCD/XYZ 或受控资产引用，流式限额与摘要 | 既有文件服务形成不可变快照/受控引用 | 1 GB 输入上限；中断清理本次暂存，不改调用方文件；不默认永久保留 |
| R03-A 数组输入 | PREPARE 校验布局，取得写入 receipt；调用方写完关闭 writer view，再 REQUEST | 既有 LocalBuffer/Trigger 扩展，提交固定描述及分配身份 | 长度、offset、dtype、generation 与 owner 一致；写入失败按原 receipt 回收，不先生成文件 |
| R04 运行准入 | 校验实际执行容量、source permit、数据/临时区预算；含模型时检查对应部署容量 | 现有准入机制；数组原子发布只读并交接到 runtime owner | 不增加等待队列；无模型时不加模型并发上限；内存不足不降采样后冒充原精度 |
| R05 执行器接管 | worker 复核输入身份，登记文件/映射、reader guard、数组 owner | 本次 ResourceScope 中的受控资源 | 提交失败释放已取得资源和 permit；所有别名存活期必须被 owner 覆盖 |
| R06 格式解码 | PLY/PCD 使用受控 trimesh/pypcd4，XYZ 使用 NumPy；数组校验后直接借用；平台资产按规范块读取 | 规范三维引用，包含字段、数量、源精度与来源 | 乱序字段、截断、解压量、未声明列或不支持字段明确失败；不换库重试 |
| R07 单位与有效性 | 核对源单位/坐标，显式 normalize-units、filter-valid | 带源映射的规范点云与有效性摘要 | 不猜单位、不删真实零点；无有效支持是缺测，损坏格式是执行错误 |
| R08 选择分析区域 | 在明确 frame 中选 ROI；配方需要时才执行已公开的去噪/重采样 | 有源 owner 的索引视图或独立派生云 | 不修改原云；去噪/重采样不能隐藏在读取或显示中，未实现算子不开放 |
| R09 建立基准 | 拟合基准面、检查支持/质量，使用原点、面内轴或次基准构建 pose | features、pose、found；平面成立与姿态完整分别表达 | 缺基准、多解、约束不足传递明确状态，不复用上次矩阵 |
| R10 坐标变换 | 用 found pose 变换位置与方向，或按配方明确使用源坐标 | 同观测目标坐标云；失败时 unavailable | 不隐含缩放/镜像；unavailable 不分配假数组、不生成假端点 |
| R11 提取特征 | 提取有序边界/支持段，拟合线、圆等，按稳定 ID 匹配 | 带支持域、方法与质量的 features | 不按返回顺序猜孔/边；短弧、断口、遮挡和多候选明确解释 |
| R12 计算尺寸 | 按冻结 item_id、方向、位置、参考/目标和方法分别计算 | NumericTable 与同 observation/item_id 的三维证据 | 所有启用必检项都必须出现；不可测为 null/valid=false，不补零、不漏项 |
| R13 汇总质量 | 汇总各阶段已有支持点、残差、覆盖及适用条件检查 | 使用既有数值/规则基础的质量摘要；不重复拟合 | 几何质量不合格导致不可测；不能直接当产品超差或把插值当实测 |
| R14 公差判定 | 按冻结必检集合与公差执行通用 Check Limits | ok/ng/invalid、逐项原因及明确布尔放行语义 | 必检 INVALID 优先于 NG；执行错误/取消不包装成正常产品判定 |
| R15 组织结果 | 固定量值、方法、判定、端点和有界显示证据 | 既有 Result Record、Preview/运行结果存储 | 只保留有界证据时明确源未保存；不把临时 cloud ref 写入持久结果 |
| R16 可选保存 | 配方显式保存原始/派生资产或导出 PLY/PCD/XYZ | 既有 ObjectStore/计量资源服务生成不可变版本与 file-ref | 写入/校验成功后才提交；取消、磁盘满、字段遗漏不能伪报成功 |
| R17 输出与显示 | 通过既有 PLC 网关/HTTP/数据库/文件节点交付，前端显示同一结果快照 | 每个交付动作保留实际成功/失败；SPC 读取已保存结果 | 测量判定与交付状态分离；交付失败不改量值，也不宣称整次交付成功；不新建重试队列 |
| R18 释放与收敛 | 按依赖顺序关闭算法对象、索引/别名、view/guard、映射，再释放底层资源 | 既有 scope、Broker、worker 与 ACK 机制；归还真实已释放预算 | 关闭失败保留归属并阻止相关 worker 复用；晚 ACK/旧 generation 不能释放新资源 |

R03-F 与 R03-A 是互斥入口分支，不要求同次输入重复走文件和内存。数组 PREPARE 和 REQUEST 的两次校验沿用 10.6 的既有协议，不建立第二套预约/调度器；文件传输、执行准入、输出附件 ACK 的寿命不同，不把整个流程误写为一个租约。

R08–R12 可按测量定义组合或省略：源坐标高度无需强制工件定位；多个尺寸可共享基准与只读点云。每个阶段的质量检查即时生效，R13 只汇总，不把无效几何拖到公差阶段才发现。所有执行路径，包括坏输入、定位失败、算法异常、取消、进程退出和输出失败，都必须进入 R18 的对应清理路径。

### 4.2 配方制作、发布与现场操作

| 步骤 | 操作与配置 | 必须呈现的状态/结果 | 进入下一步的条件 |
| --- | --- | --- | --- |
| U01 导入样本 | 选择 PLY/PCD/XYZ 或已有资源；查看字段/列定义 | 读取中、格式/字段错误、源身份、有限显示证据 | 输入有效；新文件不能沿用旧文件的确认或异步结果 |
| U02 确认空间 | 配置单位、源坐标和无效值；需要时绑定标定资源 | 源值与规范值可区分；未知单位允许查看但不允许物理合格判定 | 确认绑定当前数据 revision，不靠相机型号或文件名猜测 |
| U03 建立基准 | 编辑参考 ROI、拟合方法、原点、次基准和轴方向 | 支持点、残差、pose 状态；定位失败仍可回到配置 | 自由度与质量满足配方要求，不自动补轴 |
| U04 定义测量 | 为高度、高差、长宽、孔/槽等选择对象、方法、方向及支持域 | 真实测量端点、稳定 item_id、单位与逐项质量 | 不使用显示偏移/LOD 点代替测量数据；缺特征行为已定义 |
| U05 定义判定与保存 | 配置必检、公差、显式保存与交付节点 | OK/NG/INVALID、测量失败与交付失败有不同展示 | 外部布尔消费者能解释 INVALID；输出字段与单位约定明确 |
| U06 草稿预览 | 使用完整算法和有界显示，切换样本、取消及重新计算 | 当前版本结果、历史结果标识、可定位的失败原因 | 失败/晚返回不能覆盖新样本；预览与正式执行使用同一算法契约 |
| U07 审核并发布 | 冻结图、参数、资源、必检集合、节点/依赖身份和格式能力 | 发布前检查、依赖变更说明、受影响旧版只读 | 资源及实现身份全部满足准入；不修改已发布版本 |
| U08 启动与调用 | 选择审核后的版本，在现有 Runtime 启动，外部系统提交完整点云 | Runtime 健康、调用结果、交付状态与资源不足原因 | 启动/恢复均通过相同身份及资源检查；不创建三维专用守护进程 |
| U09 结果复查与迭代 | 查看数值、证据、保存资产和统计；修改时创建草稿 | 未保存完整源时明确不能任意复算；旧版只读可追溯 | 新配方重新审核发布；不悄悄让旧结果使用新算法重算 |

上述能力位于现有 Workflow 编辑、资源管理、Preview、Runtime 和结果入口，不为每种格式/工件新建页面。共享三维 viewer 只负责显示、ROI/拾取交互和证据联动；卸载时释放订阅、请求、渲染循环及 WebGL 资源。M1/M2/M3 分阶段完成这些交互，但每个公开动作必须有完整的成功、错误、取消和生命周期行为。

## 5. 输入与数据契约

### 5.1 输入类型不能混用

| 类型 | 必要语义 | 禁止推断 |
| --- | --- | --- |
| PLY/PCD/XYZ 点云 | XYZ、字段类型、单位、源坐标系、可选颜色/强度/法向/标量 | 仅凭坐标大小或文件名猜单位；把 RGB 当高度 |
| 原始深度图 | 深度比例、无效值、成像/标定模型、深度是轴向距离还是射线距离 | 把灰度直接乘固定步距当三维坐标 |
| 标定高度图 | 行列轴、原点、网格步距、局部基、标量方向、valid mask | 默认等同透视深度图或普通显示图片 |
| 扫描轮廓 | 已标定轮廓坐标、顺序、采集身份、扫描位移/编码器语义 | 只按序号推断等间距 Y；忽略漏帧和倒序 |
| 网格 | 顶点、拓扑、单位、法向/朝向、有效性 | 默认闭合、默认可计算带符号距离或实体体积 |
| CAD | 内容版本、长度单位、模型坐标、拓扑、几何实体 | 用未知精度的显示网格冒充精确曲面 |
| CloudCompare BIN | 开发阶段检查工程/对照资产 | 作为生产必需格式或要求生产安装 CloudCompare |

PLY 的设计范围包括 ASCII 与明确字节序的二进制，尚不是已实现的支持声明；字段按名称读取，校验数量、dtype、有限值、容量及截断。未知附加字段采用明确保留/拒绝规则，不静默误解为测量语义。零坐标可能是真实点，不能统一删去所有零点；无效哨兵按输入定义处理。

PCD 与 XYZ 同属首批文件入口设计，不作为 PLY 的临时转换来源。PCD 按 FIELDS/SIZE/TYPE/COUNT、WIDTH/HEIGHT/POINTS 及 DATA 模式描述内容；组织结构、VIEWPOINT 和颜色打包信息不能因读到 XYZ 就被认定已经完整保留。XYZ 必须明确列数、列顺序、分隔规则、单位和坐标系；普通 XYZ 三列与 XYZN、XYZRGB、XYZI 分开声明，不猜测第四列或其余列含义。格式/编码/字段支持及拒绝条件见 11.2，能力须通过验证后才对外声明，不把扩展名清单当已交付支持范围。

### 5.2 拟定公共数据类型

下列名称是 M0 的契约设计，不代表当前 Catalog 已注册。首批字段范围见 5.4–5.11；深度、高度栅格、扫描轮廓、网格、CAD 和高级曲面的完整契约随对应阶段评审，不提前注册空 payload：

| 草案类型 | 内容 |
| --- | --- |
| `point-cloud-ref.v1` | 受控点数据引用、数量、字段布局、单位、坐标、源身份和有效性引用 |
| `depth-map-ref.v1` | 未反投影深度及成像标定引用，区别于三维高度栅格 |
| `height-map-ref.v1` | 物理网格、参考基、方向、有效掩码与采样映射 |
| `profile-ref.v1` | 有顺序的扫描/截面点、弧长或扫描位置以及数据来源 |
| `mesh-ref.v1` / `cad-ref.v1` | 可追溯几何资产，拓扑、单位和离散化误差元数据 |
| `transform3d.v1` | 仅表示有效的 source/target 刚性变换；不承载定位失败或隐式单位缩放 |
| `pose3d.v1` | 定位观测状态与可空的有效 transform；失败不得带旧矩阵，见 5.9 |
| `roi3d.v1` | 工件坐标中的盒、柱、截面带或有明确投影语义的区域 |
| `features3d.v1` | 类型化点/线/面/圆弧/圆柱等观测、稳定 ID、支持域、有效性 |
| `measurement-evidence3d.v1` | 与 numeric-table 同一 observation_id 的测量定义、有限几何、支持和质量证据；kind 分发高度/高差/长宽/边距/孔径 |

公共元数据至少能追溯 `run_id`、输入/观测身份、坐标系、单位、资源内容版本、标定版本和处理方法。大数组、支持点集合与偏差场使用引用；小型几何和摘要可以内联。引用必须经服务端验证，不能由普通 JSON 任意构造本地路径或跨运行内存句柄。

仅有不同 observation_id 的数据禁止直接合并为同一次测量；跨帧/多扫描操作需要显式配准与新的合成观测身份。所有几何关系需核对坐标、单位和来源，不以显示位置相近替代身份匹配。

### 5.3 单位、精度与缺测

- 源单位必须来自文件可信元数据或显式配置，并记录确认来源。未知单位允许查看原始坐标，但禁止生成物理尺寸合格结论。
- 内部计量长度拟统一规范为 millimeter，面积、体积和角度使用独立量纲；单位转换集中执行，不散落于节点 helper。源单位和转换比例仍保留。
- 保存和传递保留输入声明的 dtype：当前 ASCII PLY 的 property float x/y/z 对应 float32，不因为文本有小数或库使用 double 临时量就整云转 float64；外部声明 double 的字段保留 float64。拟合、累加、矩阵求解等按需要在局部 ROI、分块或小矩阵中使用 float64，并检查数值条件，不另建常驻全云 double 副本。源精度、算法计算精度与显示精度分开；算法派生量的 dtype 由该方法明确，不倒改源数据。
- 小数显示位数不是存储精度声明。不在导入时把坐标四舍五入到两位或四位小数，不从文本位数猜 dtype；float32 的可分辨量随坐标量级变化。更高计算精度不能恢复传感器未采集的信息，未知误差预算不填写默认阈值。
- 有效掩码区分实测、无效、未覆盖、插值/外推来源。插值或补洞是显式操作，不改变原数据；需要原始证据的测量不能误用补全数据。
- 规则网格重建要验证步距、重复点、每格多点、缺点及行顺序。不得把非等长扫描行直接 reshape；高度场无法表达多层/悬垂时保留点云，不能强行合并。

### 5.4 字段共用规则与运行内点云引用

以下表格是首批实现的字段规格，不是另一份机器 schema。实现时复用 [Contract、Identifier、Finite](../../backend/contracts/workflows/metrology.py) 的严格类型、未知字段拒绝、不可变和有限数约束。标识最长 128 字符，摘要为小写 SHA-256；整数不接受 bool 或小数。JSON 数量/偏移限 JavaScript 可精确表示的非负整数范围，运行预算通常更小；二进制 int64/uint64 属性不转成前端 JSON number。JSON 不承载 NaN/Inf；二进制坐标可以包含非有限值，但有效性扫描必须标为无效。

`point-cloud-ref.v1` 只在受控执行上下文解释，不能作为 HTTP 持久资产引用或返回给其他运行直接复用。下表描述 state=ready 分支；缺测的 unavailable 分支在 5.9 明确定义，不分配虚假资源：

| 字段 | 类型与约束 | 责任 |
| --- | --- | --- |
| `format_id` | 固定 `amvision.point-cloud-ref.v1` | 平台校验版本 |
| `state`、`reason` | ready 时 reason=null；unavailable 时按 5.9 | 状态不是产品 OK/NG |
| `run_id`、`observation_id`、`cloud_id` | Identifier；服务生成，当前 run 内解析 | 外部 observation 仅作为来源字段，不取得资源访问权 |
| `revision` | 正整数；同一内容发布后不可改写 | 数据、单位、坐标或有效性变化产生新引用 |
| `point_count` | 非负整数；入口必须大于零，派生 ROI 可以为零 | 不能用空输入和空测量域混淆执行错误与缺测 |
| `fields` | name/semantic/dtype/components/unit，取 5.5 相同语义但不含物理 offset/count/byte_length | worker 解析真实存储；ROI 的逻辑子集不能伪称物理紧密连续块 |
| `spatial` | 5.6 的单位、坐标声明 | 无单位/轴定义时允许查看，物理测量无效 |
| `source` | `kind` 为 `file`、`local-array` 或 `derived`；文件引用、载荷摘要或父引用按 kind 互斥 | 原始来源不冒充已经保存的资产 |
| `source_metadata` | null 或 10.13 的严格 PCD 组织/VIEWPOINT 描述；不是自由 metadata | 记录源格式信息，不应用为姿态变换；改变行结构的过滤/裁剪清除当前组织描述并记录来源 |
| `provenance` | `method_id`、`method_version`、`parameters_sha256`、父 `cloud_id/revision` 集合；原始输入无派生方法 | 参数正文来自冻结配方/结果方法记录，不能只留一个无法追查的 hash |
| `sample_origin` | `measured`、`interpolated`、`extrapolated` 或 `mixed` | mixed 必须有逐点来源块；validity 不能代替来源分类 |

实际 ndarray、文件映射、Broker receipt、reader guard、借用计数、索引和 closer 由现有执行资源作用域持有，通过 `run_id/cloud_id/revision` 解析。不把 Python 对象地址、系统路径、释放 token 加到公共引用中。父引用失效时子集不能独立存活；保存时须物化为独立数据，详见 10.11。

### 5.5 二进制描述与属性字段

同机输入的控制描述采用新业务格式 `amvision.point-cloud-buffer.v1`，并复用现有 LocalBuffer 定位结构，不重新定义 arena ABI。字段为 `format_id`、`point_count`、`content_length`、`fields`、`spatial`、可选 `source_observation_id` 和可选 `source_metadata`（10.13 的严格分支，缺省为 null）。PREPARE 返回的分配身份不由调用方填写；REQUEST 不再重传可变布局。摘要与交接见 10.5–10.6。

| 每个 `fields[]` 字段 | 完整规则 |
| --- | --- |
| `name` | Identifier，唯一；`positions`、`normals`、`colors`、`validity`、`sample_origin` 为保留名称，不得用普通标量冒充 |
| `semantic` | `position`、`normal`、`color-rgb`、`validity`、`sample-origin`、`scalar`；名称与语义一致 |
| `dtype` | 固定宽度 `int8/uint8/int16/uint16/int32/uint32/int64/uint64/float32/float64`；多字节一律 little-endian；禁止 object、字符串、复杂数和自定义 dtype |
| `components` | position/normal/color-rgb 为 3，其余为 1；不接受任意向量长度 |
| `count` | 与载荷 N 一致；块为连续 N×components，不接受 stride |
| `offset_bytes`、`byte_length` | 非负整数，紧密排列并按 dtype 宽度补零对齐；长度等于 count×components×itemsize，不重叠、不溢出、不留尾随数据 |
| `unit` | scalar 必须显式给出单位标识、无量纲 `1` 或 null（未知）；position 从 spatial 取长度单位，normal/color/标记块为无量纲 |

`positions` 必须 float32/64；`normals` 也是 float32/64；`colors` 固定 uint8 RGB，不偷偷把 0–1 浮点色值量化；其他颜色布局须显式适配。`validity` 固定 uint8 的 0/1；派生 `sample_origin` 固定 uint8 的 0=measured、1=interpolated、2=extrapolated，不能覆盖无效掩码。用户输入只有实测来源，派生块不能由外部请求伪造算法追溯。

图内 ROI 索引不是输入属性。其源索引采用 uint32 或 uint64，由源点数范围明确选择；跨语言索引不得截断。派生资产需要追溯时保存索引块及父内容摘要；父数据未保存也必须明确不能据此复算。标量原名称若不符合 Identifier，解析适配器须保存可逆的 `source_field_names` 映射，名称冲突拒绝，不默默丢弃或覆盖。

控制描述连同原有信封受 [WorkflowTrigger 64 KiB 请求限制](../../backend/contracts/ipc/local_message_profiles.py) 约束，不能把 64 KiB 全部算给字段列表再遗漏其他字段。不新增独立的无界 metadata；完整描述超限在分配前拒绝。支持域和点索引不内联到描述。合法例见 10.5 的 34 字节布局；dtype 不匹配、重叠、越界、负 stride 和未知字段均是协议错误，不转成测量 INVALID。

### 5.6 空间与变换字段

| 对象 | 字段 | 校验 |
| --- | --- | --- |
| `spatial` | `length_unit`、`unit_source`、`frame_id`、`axes` | length_unit 为 m/mm/um 或 null；其他源单位先由显式适配转换并记录。unit_source 为 metadata/configuration/unknown，unknown 与 null 一致。frame_id 为 Identifier；axes 明确 X/Y/Z 方向及 handedness，未知只能查看 |
| 单位转换追溯 | `source_unit`、`target_unit`、`scale`、输入/输出引用 | scale 为正有限数，由已声明单位计算；位置和所有有长度量纲的属性同步转换，法向不缩放；保留源，不原地改写 |
| `transform3d.v1` | `format_id=amvision.transform3d.v1`、`observation_id`、`source_frame_id`、`target_frame_id`、`length_unit`、`matrix`、`provenance` | matrix 为行排列 4×4 有限数 JSON，作用于列向量 `[x,y,z,1]`；末行 `[0,0,0,1]`，旋转正交且 determinant=+1，平移与坐标同单位 |
| 变换组合 | 前一 target 等于后一 source；同观测、同单位 | `C_from_A = C_from_B × B_from_A`；禁止转置、隐含缩放及跨观测混合 |

源坐标的左右手性必须记录；首批刚性测量坐标为右手系。左手源需要显式轴映射及其追溯，不能把 determinant=-1 的矩阵谎称 SE(3)。矩阵数值校验容差属于数值算法策略，需用 dtype 与条件数的测试确定，不用图纸公差替代，也不在本轮随意给 epsilon。单位换算和坐标变换可局部使用 float64 计算，不因此要求整云输出 float64；浮点输出按节点声明检查精度与范围，不能把变换后的非整数结果写回整数源。

### 5.7 ROI 与特征字段

首批 `roi3d.v1` 为 `format_id=amvision.roi3d.v1`、`roi_id`、`frame_id`、`length_unit`、`kind` 和与 kind 对应的 `geometry`。ROI 属于配方坐标，不含本次 observation；绑定到数据时检查 frame/单位。geometry 是显式联合类型，拒绝多种形状混填：

| kind | geometry 字段 | 约束 |
| --- | --- | --- |
| `box` | `center[3]`、`rotation[3,3]`、`size[3]` | 有限数、正交右手旋转、尺寸均正；不以 min/max 的错误排序自动纠正 |
| `cylinder` | `center[3]`、`axis[3]`、`radius`、`length` | 单位轴、半径/长度正；center 在轴段中点 |
| `section-band` | `origin[3]`、`normal[3]`、`thickness`、`bounds_roi_id` | 单位法向、厚度正、裁剪范围引用已定义 ROI；不默认为无限平面 |

边界定义为闭集，距离计算按 float64；数值比较策略须随方法版本冻结，不能偷偷扩 ROI。任意多边形/环形/CAD ROI 留给后续明确契约，不以自由 JSON 宣称支持。

`features3d.v1`：`format_id=amvision.features3d.v1`、`run_id`、`observation_id`、`frame_id`、`length_unit`、`items`。每项为 `feature_id`、`kind`、`valid`、`reason`、`geometry`、`support`、`quality`、`method`；ID 唯一，有效则 reason=null，几何满足对应约束；无效则 geometry=null、reason 必填，但保留支持/质量诊断。首批每个数组沿用通用数值表 8192 项的有界原则，同时受交付字节预算限制。M2 仅注册真实实现的 plane 分支，以下其他几何为后续阶段目标。

| kind | 有效 geometry | 支持/失败信息 |
| --- | --- | --- |
| `point` | `position[3]` | 实测点或插值点明确标识，不用零向量表示缺失 |
| `line` | `origin[3]`、`direction[3]`、`parameter_range[2]` | direction 为单位向量；有限支持范围，不能把拟合无限线全部当已观测 |
| `plane` | `normal[3]`、`offset` | normal 单位化，方程 n·p+offset=0；法向正向来自参数/基准，不由本次 SVD 任意符号决定 |
| `circle` | `center[3]`、`normal[3]`、`radius` | 正半径、单位法向；支持弧和缺口放 support，不以圆模型暗示全周有观测 |

M2 support 直接复用只读 point-cloud-ref 子集，不另建索引资源。沿已有 CloudView 读取最初输入的 source_indices，source_point_count 为原始总点数，归属同一 Scope。quality 复用 NumericTable 和 LimitRule，记录方法实际适用的指标；未知量为无效 NumericItem(null)，残差带单位，角度统一 rad，不能凭 RMS 生成 confidence。method 的方法 ID、版本、参数及质量策略按 5.11，不保留平铺方法字段。后续边界/测量的支持域须在对应阶段定义，不作为 M2 自由扩展字段。

### 5.8 数值和三维证据

量值继续使用 `numeric-table.v1`，不新增三维 NumericTable。M3.3 将证据升级为 `measurement-evidence3d.v1`，包含 `format_id=amvision.measurement-evidence3d.v1`、`observation_id`、`frame_id`、`length_unit` 和 `items`；items 用 kind 分发测量方法，与量值以 item_id 关联，不靠数组顺序。旧测量配方审核重发，不保留 v1 算法/读取兼容分支；无测量部分的点云资产不因此升级。

M3.1 每项实际字段为 `item_id`、`value`、`valid`、`reason`、`method`、`geometry`、`support`、`quality`、`sample_origin`。特征 ID 和查询定义位于强类型 `method.parameters`；方向/实际端点位于有判别字段的 `geometry`，避免重复散落字段产生矛盾，完整定义见 [M3.1](3d-metrology-m3-height.md)。无效结果 geometry=null；独立 ROI 统计差没有唯一物理点对，endpoints=null，保留双方支持和统计定义，不用质心连线代替。未来圆直径分支给圆心/圆模型与所显示直径方向；面积/体积不硬塞两个端点。显示文本位置/线偏移放前端呈现配置，不进入物理端点。

证据中的有效性必须与对应量值一致；有数值但不能完成不确定度判定时，量值/证据仍有效，规则状态单独 INVALID。显示数据是独立的有限采样及特征附件，不用本 payload 内联原云；源未保存的历史结果不得保留悬空 runtime ref。未来高级几何各自新增判别分支与验证后注册，不在首批接受任意 `geometry:object`。

### 5.9 失败定位与缺测传递

复用现有 [PoseObservation](../../backend/contracts/workflows/metrology.py) 的“观测状态与变换分离”原则，不扩展二维矩阵、不新增执行器状态机。`pose3d.v1` 字段如下：

| 字段 | 类型/约束 |
| --- | --- |
| `format_id` | 固定 amvision.pose3d.v1 |
| `run_id`、`observation_id`、`pose_id` | Identifier，与当前输入一致 |
| `source_frame_id`、`target_frame_id`、`length_unit` | 明确的源/目标与物理单位；不能在失败时假设两者相等 |
| `state` | found / not_found / ambiguous / underconstrained / insufficient_quality |
| `transform` | found 必须有 5.6 的有效 transform 且 frame/单位/observation 一致；其他状态必须 null |
| `reason` | found 为 null，其余为 Identifier，如 datum_missing、datum_axis_missing、multiple_poses、datum_quality_failed |
| `reference_feature_ids`、`method`、`quality`、`support` | 5.11 的有界集合；只引用本次观测的实际证据；失败时也保留可用诊断 |

不存在的配方 ID、循环基准依赖、非法矩阵/单位属于配置或接线错误；本次没有找到配置要求的基准属于正常 not_found。已找到平面但缺面内轴属于 underconstrained，不自动补原点/方向。原生库崩溃、超时和取消不转为这些观测状态。

`build-frame` 输出 `pose:pose3d.v1` 与 `found:boolean.v1`（仅 state=found 为 true）。found 可连接现有 Conditional Start，表示是否执行可选分支；它不是产品放行。正式量测默认直接消费带状态的 pose，不要求每张图手写一个失败分支来补齐必检值。

`transform-cloud` 的输入冻结为 `cloud` + `pose`，内部只在 found 时使用 transform。失败时不执行矩阵运算，输出 point-cloud-ref 的 unavailable 分支：保留 format_id/run_id/observation_id/source/provenance、目标 spatial 声明及 reason；`cloud_id/revision/point_count/fields/sample_origin/source_metadata` 全为 null。该分支没有数组、索引或 Broker 租约；target frame 是请求的目标，不代表存在已变换坐标。ready 的空 ROI 则 point_count=0 且有真实资源身份，二者严格区别。

所有首批云消费者统一先校验身份/状态：unavailable 在 filter/crop/transform/边界提取中原样传递来源原因；拟合为相应 feature_id 输出 valid=false、geometry=null；测量按冻结 items 输出所有启用项的 NumericItem(null)/相同 observation，并附定位或支持不足原因。成功数据也不得因连接次序改变 item_id。Save/Export 不接受 unavailable，会明确报告未保存；不得生成空成功文件或吞掉失败。输入 read-cloud/同机协议不能由调用方提交 unavailable 绕过校验。

measurement-evidence 的 frame 表示评价目标；无效时实际端点、查询交点及几何为 null，不画单位矩阵下的假位置。UI 可以显示源点云和标为“预期”的 ROI，不能将其当已定位结果。只测源坐标中的高度可直接用该 frame，不强制建立工件坐标系；配方要求工件坐标时必须消费定位结果。

验证：成功 → 缺基准 → 多解 → 成功连续切换不能复用旧矩阵；两条失败支路合并仍保留全部必检项；optional 分支跳过不把必检集合缩小；unavailable 不触发 registry lookup/分配/保存。此设计由包内共享契约校验/算法入口实施，不通过 handler 相互调用或通用异常兜底。

### 5.10 有序边界与支持段

有序边界作为 `features3d.v1` 的 `kind=boundary` 分支，不再新建平行轮廓系统，也不能把点云行号排序当拓扑。geometry 为：

| 字段 | 类型/约束 |
| --- | --- |
| `vertices` | 同 run/observation/frame/unit 的 ready point-cloud-ref，按实际边界顺序排列；可为源索引视图或派生交点，不是显示 LOD |
| `segments` | 有界列表，每项 segment_id、start、count、closed；start/count 指 vertices 的逻辑行，正 count，范围不重叠、按 start 递增并完整覆盖边界行 |
| `role` | outer / hole / open-edge / unknown；unknown 不可直接作为已确认孔/外轮廓测量 |
| `orientation` | ccw / cw / undetermined，针对 projection_frame_id 的 +Z 看向平面所约定的 XY 正向；不靠屏幕朝向 |
| `projection_frame_id` | 明确评价平面坐标；用于内外轮廓/方向定义，不改变三维坐标 |
| `closed` | 仅当恰有一个 segment 且其 closed=true 才为 true；多段不得靠隐式末首连接假装整体闭合 |

每个开段至少两个不同点，闭段至少三个不同点；闭段首点不重复存为尾点，闭合边由 closed 明确表达。段间没有连接边，缺扫/断口须断段；不按距离阈值悄悄跨洞。方向不确定的开放边不能假称孔边界。内外角色和 segment_id 来自显式几何/匹配规则，不使用本次连通域返回顺序作长期身份。自交、多重轮廓和覆盖不足由方法的质量检查明确拒绝对应测量，不统一修复成凸包。

segments 与 features 项数采用已有 8192 项上界并同时受描述字节预算约束；超限拒绝该结果，不截断后继续测量。小范围拟合可按明确段 ID 取子集；fit-line/fit-circle 输入冻结为 features 中指定 boundary ID/segment IDs，内部借用 vertices，不再让外部任意无序 cloud 冒充边缘。measure-hole 只消费既有 CircleFeature，不重选支持或拟合。其他调用者确需对无序点拟合时须显式声明方法，不改变这些测量工具的边缘定义。

Boundary support 记录原云索引或派生来源；等值线交点是 interpolated，不假称传感器实测点。导出普通点云 PLY 不自动保留段拓扑；完整边界保存为点云资产与段描述的受控证据关联，原始云未存仍可保留有界显示证据。运行结束时不可将 vertices 的瞬时引用写入历史结果，需替换为证据资产或显式保存引用。

M3 开工时的源码核对：原 CloudRuntime 子集要求索引严格递增，派生数组要求与父云等点数。M3.2 已在同一 CloudRuntime 扩展有序源点和生成顶点，普通 subset 仍保持严格递增；当前来源、拓扑及保存字段以 [M3.2 实施记录](3d-metrology-m3-boundary.md#5-运行引用与保存契约)为准，不另建资源系统。

### 5.11 嵌套字段与校验矩阵

所有对象 extra=forbid；文本 ID 复用 Identifier，说明文字长度复用现有名称上限 128，非空；数组除以下形状要求外还受现有信封/结果/manifest 字节预算。没有定义的对象不能通过 metadata 扩展业务语义。

| 对象 | 逐字段定义 | 交叉校验 |
| --- | --- | --- |
| `spatial.axes` | handedness=right/left/unknown；axis_labels 为三个非空短文本；definition_source=metadata/configuration/unknown | labels 是显示/语义描述，不是数值变换；unknown 不允许推导物理轴，数值方向只来自明确 transform/单位向量 |
| `source` file | kind=file，file 为现有受控 file-ref；source_observation_id 为 Identifier 或 null | 同项目/调用输入，文件摘要实际验证，不能仅按文件名绑定 |
| `source` local-array | kind=local-array，content_sha256、descriptor_sha256、source_observation_id | 两种摘要不可混同；不保存 writer token |
| `source` derived | kind=derived，parents 为同 run 的 cloud_id/revision 或 pose_id；父缺测时记录原因身份 | 非空、唯一，无循环；派生数据不可冒充原始输入 |
| `method` | method_id、method_version、parameters 为该方法专有严格 schema 对象、parameters_sha256；需要质量判定的几何/测量方法另必填 quality_policy，M1 数据方法禁止伪造空 quality_policy | canonical JSON hash 必须匹配参数；无自由脚本/任意算法名；版本必须出自实际节点实现 |
| `quality_policy` | policy_id、policy_version、rules 为现有 LimitRule 列表 | 规则使用质量指标的稳定 item_id，单位一致；数值来自配方，不提供样本常量 |
| `quality` | metrics 为 NumericTable，checks 为 8.4 的 limit-check.v2 摘要 | 同 observation；指标计数非负、inlier_count≤input_count；rms/max_residual 非负、单位明确；比率限 [0,1]，角覆盖/最大缺口限 [0,2π]；无可用条件数用无效指标，不用 Inf |
| M2 `support` | PlaneFeature 为一个现有 CloudReference；Pose 为与 reference_feature_ids 对齐的 1–3 个 CloudReference | 同 run/frame/observation/unit；真实原始行号和总数由既有 CloudView/Runtime 提供，禁止显示索引或新增独立索引资源；有效几何只能引用 ready 支持 |
| 稳健支持追溯 | fit-plane-support 方法增加 indices_sha256，覆盖递增父逻辑行号的 little-endian uint32/uint64 字节 | 与父描述、实际方法和点数共同确定支持身份；相同参数/点数但不同候选支持必须可区分；不改变原始行号语义 |
| `domain` | kind=roi：roi3d；kind=boundary：feature_id；kind=interval：line_feature_id/start/end；互斥 | 只接受同观测已定义且无循环的支持域；start≤end，单位取所在几何；域缺失不能解释为无限观测 |
| `quality` 判定映射 | 共享 Check Limits 的纯函数/LimitRule，不调用其 handler | 质量规则 ng/invalid 都使对应几何/量值不可测，但不是产品 NG；只有有效量值进入产品限值判定 |
| `evidence.endpoints` | null 或两个有限 Point3；direction 为 null 或单位向量 | 与量值方法匹配，长度单位/frame 一致；无效项为 null，显示偏移不得写入 |
| `provenance` | method 或原始输入 null；parents 的稳定身份/内容摘要；source_retained:boolean | 不能仅凭 digest 声称源可读取；持久记录必须用资源引用或明确未保留标识替换 runtime 身份 |

quality 的通用指标并非每个方法都必须计算；方法 schema 声明所需指标及规则，未计算指标标记无效，不伪造零。无需判定的只读显示节点不构造空 quality_policy 并声称“质量通过”。计量结果有效性、定位 state、质量 checks.state、产品 state 是四个不同层级，禁止用同一个布尔混用。

2026-10-22 M2 实施确认：上表 `limit-check.v2` 是 M3.4 的目标，不是现有实现。M2 几何质量复用当前限值计算的完整逐项 `valid/passed/reason` 判断几何可用性，不发布 v2 或改变产品判定；全平台三态与消费者升级仍留 M3.4。M2 四节点的实施规格及实测状态见[几何节点实施记录](3d-metrology-m2.md)。

M2 公开嵌套方法已收口：参数正文与 quality_policy 分开，parameters_sha256 只覆盖正文；实际节点配置复用同一参数校验器。transform3d.provenance 保存建坐标方法、完整质量证据，以及按主/次/第三顺序排列的实际平面 geometry/method/quality/support_content_sha256。该持久快照不含 run/cloud 访问引用，source_retained=false 明确其未保存源数组；不能仅凭摘要复算。Pose 自身仍是运行观测，保存派生点云时只保存变换快照。几何消费者通过既有 check_limits 重核逐项结果，不信任伪造 passed 摘要，不另写比较器。本阶段尚未发布，直接替换旧内部形状，无旧格式兼容分支。

需覆盖的契约异常：字段互斥/遗漏、ready 与 unavailable 混填、found 携 null、非 found 携旧矩阵、段重叠/缺口/越界、闭段重复尾点、错误 orientation/frame、索引跨云、质量指标超范围、参数摘要不符、过量/循环引用。它们用平台错误拒绝；合法观测不足才沿缺测分支传递。

## 6. 坐标、基准与定位

### 6.1 坐标约定

明确源/相机系、载物台基准系、工件系和特征局部系。变换采用 `target_from_source` 命名和固定向量约定，在 Python、JSON 和 Three.js 边界测试转置、手性与组合顺序。原点、单位、轴向和法向正方向必须可见。

平面拟合只确定平面位置与法向，不足以确定完整工件姿态：平面内原点和旋转还需要次基准、边、孔、模板或明确轴配置。翻转法向不能悄悄改变高度正负号。

单位转换是显式操作；定位限定 SE(3) 刚性变换，禁止缩放、镜像、切变和非刚性拟合吸收实际尺寸缺陷。基准约束配准与最佳拟合配准分别声明用途、自由度和评价指标；ICP 收敛不等于找到了正确工件姿态。

### 6.2 高度计算的正式定义

规定查询位置 `p` 和单位方向 `v`，测量线为 `q(t) = p + t*v`。对于平面 `n·q + d = 0`，交点参数为 `t = -(n·p + d)/(n·v)`；两面沿同一方向的有符号差为 `t_target - t_reference`。

`n·v` 接近零、交点位于不允许的支持域之外、参考面不存在或多解未消歧时，返回结构化无效原因。平面有符号距离需除以法向长度或保证法向归一化，不能把系数大小当物理高度。

以下方法必须是显式的不同定义：

- 指定工件 XY 处沿基准法向查询高度。
- 指定源坐标 XY 处求表面点，再计算其基准高度。
- 实测点到参考平面的正交距离。
- 两个 ROI 各自的均值、中位数、分位数之差。
- 同一评价位置的两个拟合面之间的方向距离。

不同位置、不同方向或不同统计量不能直接相加。厚度必须说明两侧表面或贴合/底面假设，单侧点云通常不能独立证明真实材料厚度。

### 6.3 特征身份与配对

模板定义预期特征/组、稳定 ID、名义区域和配对关系。候选观测通过工件坐标、几何约束和匹配规则关联；缺失、多余和歧义分别输出。对称工件的多解必须暴露，不以返回顺序或屏幕上下左右默认消歧。

不强制数量为 6 或 12，不固定 A/B/C、L/R 名称，不把 `zip`、连通域 label、检测排序或图节点数组位置当身份。分组汇总不能替代逐特征结果。缺失必检项必须留在预期集合中，不能通过漏输出变成通过。

## 7. 节点能力清单

拟采用 `categories` 布局，内部实现模块建议为 `io`、`preprocess`、`localization`、`feature`、`measurement`、`surface` 和 `comparison`；公共 category 继续遵守 `<namespace>.<root>.<child>` 两级分类。分类名不等于单独 Node Pack。

| 能力组 | 拟定节点/工具 | 算法或实现重点 | 输出与失败边界 |
| --- | --- | --- | --- |
| 数据 | Read Cloud / Save Cloud | 成熟 PLY/点云解析器、严格字段与容量校验 | 类型化引用；坏格式、未知单位策略明确 |
| 数据 | Depth to Cloud / Profile to Cloud | 标定反投影、扫描坐标映射 | 必要标定或位移信息缺失时无效 |
| 数据 | Cloud to Height Map | 显式投影、格点聚合、覆盖统计 | 多层冲突和插值策略显式 |
| 预处理 | Normalize Units / Filter Valid | 单位转换、无效哨兵与有限值 | 不猜测单位、不按零值误删真实点 |
| 预处理 | Crop ROI / Remove Outliers | 几何 ROI、统计/半径筛选 | 返回保留索引与剔除统计 |
| 预处理 | Resample / Estimate Normals | 体素/规则采样、邻域法向 | 不替换原始测量证据；方向和邻域可追溯 |
| 定位 | Fit Datum / Build Frame | 参考特征拟合、次基准和轴约束 | 检查退化、法向与未约束自由度 |
| 定位 | Locate / Register | 特征匹配、粗配准、受约束 ICP | 残差、覆盖、多解、刚性约束 |
| 定位 | Transform / Compose / Invert | 现有架构内的三维显式变换 | 检查 source/target frame 和有效矩阵 |
| 特征 | Extract Section / Boundary / Edge | 截面带、真实深度跃变、支持点筛选 | 空洞边界不自动视为真实实体边 |
| 特征 | Fit Line / Plane / Circle / Arc | 正交拟合、稳健估计、必要的几何优化 | 残差、支持域、角覆盖、病态性 |
| 特征 | Fit Cylinder / Sphere / Cone | 对应几何模型与观测约束 | 模型可辨识性及覆盖检查；不凑合返回 |
| 特征 | Match Features / Pair Features | 显式 ID、名义布局、几何匹配 | 缺失、多余、歧义分别报告 |
| 尺寸 | Query Height / Measure Step | 方向交点、局部曲面或 ROI 统计 | 方法、位置、参考与外推限制明确 |
| 尺寸 | Measure Height / Thickness | 顶面/底面或已声明支撑关系 | 单面不足时不冒充厚度 |
| 尺寸 | Measure Extents | 指定轴跨度、最小投影包络 | 输出定义与方向，不等同图纸边间距 |
| 尺寸 | Measure Edge Pair / Gap | 对应截面边缘、直线/局部边距离 | 非平行时指定位置、范围或极值定义 |
| 尺寸 | Measure Hole / Diameter | 边界提取、圆或圆柱拟合 | 内孔/外圆、截面、弧覆盖和视角明确 |
| 尺寸 | Measure Relations | 点点、点线、点面、线线、面角度 | 有限实体与无限拟合几何的区别明确 |
| 曲面 | Measure Arc / Curvature | 截面、圆弧或局部曲线拟合 | 邻域、光滑尺度、拟合模型可追溯 |
| 形状 | Evaluate Flatness / Roundness | 明确的最小区域等评价方法 | 不以最小二乘残差冒充正式形状公差 |
| 形状 | Evaluate Parallelism / Perpendicularity | 相对基准的约束公差带 | 法向夹角另列，不能替代公差带宽 |
| 表面 | Surface Deviation / Warp | 指定参考面/标准面、残差与区域分析 | 参考、滤波和评价域明确 |
| 缺陷 | Surface Defects | 高度差分、有效掩码、连通区域 | 凸起/凹坑/崩边与缺测分别标识 |
| 面积 | Measure Area | 投影积分或三角表面面积 | 投影面积和实际表面积分别命名 |
| 体积 | Integrate Height / Measure Volume | 基准上高度积分、闭合网格积分 | 未覆盖、未闭合、交叠或方向错误明确失败 |
| 比较 | Compare Reference Cloud / Mesh | 明确采样与距离定义 | 点到点不等同点到面，方向性和覆盖可见 |
| CAD | Read CAD / Compare CAD | OCCT 几何读取、基准对齐、曲面距离 | 离散化误差预算；开面不默认有全局内外符号 |

候选节点 ID 示例为 `custom.metrology3d.fit-plane`、`custom.metrology3d.height-query`；完整 ID/端口表在 M0 生成并审查，禁止先发布空壳目录。

Open3D 等成熟库负责基础几何，不等于已经实现全部计量算法。最小区域等优化必须定义目标、约束、收敛与可验证误差；局部优化得到的候选不能直接声称全局最小。无法满足方法保证时不注册该正式方法，不用近似残差降级替代。

### 7.1 首批节点的共同规格

首批是 M1–M3 的交付集合，不要求 M1 一次实现所有算法。原 17 个数据/几何/测量节点加上 1 个必要的三维预览节点，共 18 个拟定节点；Check Limits、Result Record、表格和协议交付继续使用已有节点，不计为新增。节点 ID 采用 `custom.metrology3d.<下表后缀>`，包与节点实现版本由实际发布版本确定，不填写伪造的已发布版本。公共分类沿用两级规则，拟定 `metrology3d.data.io`、`metrology3d.data.preprocess`、`metrology3d.geometry.datum`、`metrology3d.geometry.feature`、`metrology3d.measurement.dimension`，显示节点分类沿现有分类规则定稿。目录生成沿用现有 Catalog 工具。

- capability 包括已有 `pipeline.node` 以及按实际功能声明的 `metrology3d.io/preprocess/datum/feature/measurement`。manifest 的 dependencies 是节点包依赖，不是 pip 包清单；Python 依赖走现有发行机制。
- 表中 cloud/features/roi/pose/transform/evidence/table/file 指第 5 节类型、`numeric-table.v1` 和现有 `file-ref.v1`，不是自由 JSON。特征集合通过稳定 feature_id 选取，不按首个元素猜对象。
- 测量参数包含稳定 item_id、方法、参考/目标、质量策略；长度阈值带单位。邻域、支持点数、RANSAC、拟合/收敛、弧覆盖与残差门槛由配方或已验证方法明确给出，没有通用工件默认数值。
- 缺测输出无效特征或 NumericItem(null)，保留预期 item_id；坏配置、格式、资源访问和依赖故障抛平台错误。不允许统一 catch 后返回空表或零值。
- 输入只读；派生数组/索引登记本次 scope。纯函数经验证才能声明 thread-safe，原生共享状态按实际要求 serialized，不新增进程或线程池。
- 分块读写、过滤、迭代与节点间检查取消；不可中断原生调用受现有 worker timeout/整组停止控制。保存是副作用节点，取消不得留下已宣称成功但不完整的资产。
- [manifest](../../backend/contracts/nodes/node_pack_manifest.py) 必填 timeout.defaultSeconds/maxSeconds，另有 killGraceSeconds。其他包的 30 秒不是三维时限证据；具体值未定，不能先创建 manifest 随意填值。Windows/Linux 架构分别核对 amd64/x86_64，不直接假定 x64 字符串匹配。

### 7.2 首批端口、参数与算法

所有拟合和测量输出附 method/quality。save/export 的资源身份由现有受控服务形成，节点不能构造任意 ObjectStore 路径。下表统一采用 5.9–5.11 的失败定位、有序边界和嵌套字段设计；M1 参数规格在 7.4 定稿，后续算法参数随对应阶段细化；全链路校验尚未实现，不作为已经注册的公开接口。

| ID 后缀 / 阶段 | 输入 → 输出 | 必须明确的参数/算法 | 特有失败与独立验证 |
| --- | --- | --- | --- |
| `read-cloud` / M1 | file 或参数中固定资产引用 → cloud | PLY/PCD/XYZ 格式与编码、字段或列定义、源单位/坐标；同一入口按已验证能力选择处理器，哨兵由 filter-valid 显式处理 | 坏字段/截断/超预算为执行错误；乱序字段、端序、PCD 解压、XYZ 列歧义及附加属性 |
| `save-cloud` / M1 | cloud → 持久资源引用；original 从已保留的来源解析 | original/derived、保存目标及策略，采用 10.11 格式 | 原始已释放不能拿派生代替；重读逐字段与 hash 相同 |
| `export-cloud` / M1 | cloud 或参数中固定资产引用 → file + summary | 显式选择 PLY/PCD/XYZ、编码、字段映射及单位说明；交换格式与无损资产分开 | 精度或字段不可表达时拒绝或要求显式字段选择，不静默窄化；逐格式独立读回核对 |
| `normalize-units` / M1 | cloud → cloud | source/target unit、量纲属性；不做定位 | 不盲乘未知量纲；m/mm/um 同一几何等价 |
| `filter-valid` / M1 | cloud → cloud + summary | 掩码、有限值、显式哨兵；保留源索引 | 不自动删零坐标；空结果合法但后续不可测 |
| `cloud-preview` / M1，M2/M3 扩展叠加 | cloud，可选同观测 features/evidence/table → 有界三维显示 body | 显式声明 ui.preview；只生成显示点和证据，样本预算与选择方法可追溯；显示数据不得作为正式测量输入 | 源释放前完成独立交接；跨观测叠加拒绝；显示失效不伪造测量失败；慢页面不延长原云寿命 |
| `crop-roi` / M2 | cloud + roi → cloud + summary | frame 绑定、闭边界；源索引子集 | frame/单位错误拒绝；旋转 ROI、空域、边界与源释放 |
| `fit-plane` / M2 | cloud → features | 正交 SVD；稳健模式显式 RANSAC 后内点重拟合；法向正向 | 共线、支持不足；已知旋转面、外点和法向符号 |
| `build-frame` / M2 | features → pose + found | 基准面 ID、原点、面内轴或次基准、约束优先级；见 5.9 | 次基准缺失/平行/矛盾不能给单位矩阵；已知姿态、多解 |
| `transform-cloud` / M2 | cloud + pose → cloud | source/target 校验；found 时位置变换、法向旋转、标量保留；否则 unavailable | 禁止非刚性/隐含缩放；组合/逆变换、失败后不能残留旧坐标 |
| `extract-boundary` / M3 | cloud + roi + 评价基准 → boundary features | 显式投影/截面/高度等值方法；vertices 引用与 segments 按 5.10 表达 | 缺扫不默认是孔，不自动只取凸包；凹形、多孔、开轮廓 |
| `fit-line` / M3 | 指定 boundary/segments 的 features → features | 正交 TLS、支持段、稳健策略 | 短支持/退化/多边混入；旋转直线与已知距离 |
| `fit-circle` / M3 | 指定 boundary/segments 的 features + 评价平面 → features | 平面残差检查、正交几何圆拟合；代数解只作初始化；弧覆盖和条件检查 | 短弧、小 RMS、非共面；已知圆、部分弧及不同采样 |
| `height-query` / M3 | cloud + 基准 features → table + evidence | 查询 frame、方向、邻域；首批局部平面正交拟合，不自动切最近点/插值 | 无支持、多层、方向平行为 INVALID；6.2 的解析交点 |
| `measure-step` / M3 | 参考/目标 cloud，方向面法另需 features → table + evidence | directional-planes 指定查询位置/方向；roi-statistic 指定统计量/投影基准；互斥参数 | 不平行面位置效应、交换变号；独立统计真值 |
| `measure-extents` / M3 | 指定 boundary 的 features + 评价坐标 → table + evidence | 轴向跨度/投影包络定义、两个 item_id；借用 vertices，不冒充图纸边距 | 只称可见范围；旋转矩形/凹形/遮挡 |
| `measure-edge-pair` / M3 | features → table + evidence | 两边 ID、方向、位置/区间、平行性门槛 | 非平行无评价位置不能给唯一宽度；相交、缺边、外推 |
| `measure-hole` / M3 | 指定 CircleFeature → table + evidence | 圆特征 ID、闭孔/开放弧、上游质量与求解终态；不再次拟合 | 多候选不能取第一个；圆心/直径逐项证据；多孔、部分孔、缺扫 |

失败定位和有序边界已有 5.9/5.10 的明确设计，不再保留上表的旧端口。剩余核对是严格参数 schema、跨节点状态/身份传播、失败必检项补齐和资源消费矩阵；不是重新选一套定位/轮廓系统。不能把失败定位伪装成合法矩阵，也不能用无序 cloud 暗示有序边，不创建占位节点绕过。

首批不注册深度/轮廓导入、自动 ICP、圆柱、正式形位公差和 CAD 空壳。Remove Outliers/Resample 等只有在所属节点独立规格通过后公开，不能作为隐藏前处理改变上述定义。高级能力仍属于 M4/M5。

### 7.3 组合与独立真值

F1：read-cloud/同机入口 → normalize-units → filter-valid；F2：crop-roi → fit-plane → 明确基准建立；F3：height-query；F4：两 ROI 与 measure-step；F5：extract-boundary → fit-line/measure-edge-pair，或显式 measure-extents；F6：extract-boundary → fit-circle → measure-hole；F7：NumericTablesMerge → Check Limits → 版本化记录/既有交付节点。需要三维显示时显式接 cloud-preview，数值表仍接现有预览节点；不自动把所有中间云上传页面。save/export 是显式旁路，不是默认副作用。

真值用公式及人工构造坐标产生，不调用被测拟合器。平面交点按 6.2 直接求解，平行面间隔、旋转矩形跨度、已知圆和单位比例分别验证。噪声/外点例与精确解析例分开，固定随机种子/生成参数；0/1/多个特征、相反法向、近竖直面、短弧、缺失必检分别断言 reason，不只断言布尔。真实样本报告用于方法核对，不作准确度真值。

### 7.4 M1 六节点详细规格

本节冻结节点语义；`read-cloud`/`export-cloud` 的格式实现路线见 11.2.8，设计 G1 已收口，实际能力须通过 M1 I/O 验收后才能开放。不是注册六个占位节点，也不把尚未通过的格式列入可用选项。参数与嵌套对象沿用 5.4 的严格类型；下文“可选”表示可以缺省，显式 null 仅用于注明可空的字段，其他位置拒绝 null、未知字段和类型强制转换。

共同约定：输入端口名、参数名和资源引用身份固定，不按显示标题匹配。输入 `cloud` 为 `point-cloud-ref.v1`，同机数组直接由 App Entry 接入该端口，不再经过文件节点。只有 `read-cloud` 负责外部文件/已有资产到运行内引用的转换。资源、timeout、线程与显示上限取已有运行配置中的显式策略，参数不得绕过上限；缺少必要策略时能力不启用，不用无限值兜底。错误沿既有 `code/message/details` 返回，details 只带阶段、binding/node、字段或行号等安全定位信息，不泄露本地绝对路径或凭据。

#### 7.4.1 read-cloud：读取点云

| 项目 | 定稿规则 |
| --- | --- |
| 输入/输出 | 可选 `file:file-ref.v1` → 必填 `cloud:point-cloud-ref.v1`；持久资产通过下述资源参数选择，不再建立“读取资产”节点 |
| `source` | 严格联合：`{kind:file}` 或 `{kind:asset, reference:ResourceReference}`；file 分支必须有 file 输入；asset 分支禁止 file 输入，reference.kind 必须为 point-cloud |
| `file_options` | 仅 file 分支必填：`profile_id:Identifier`、`profile_version:正整数`、`spatial:5.6 对象`、`field_mapping:数组`；asset 分支禁止该对象，不能覆盖已保存单位/字段 |
| `field_mapping[]` | 每项含 `source_names:非空且不重复的字符串数组`、`target_name:Identifier`、`semantic/dtype/components/unit:5.5 定义`；源字段恰好覆盖所声明数据，分量数一致，目标名称唯一；不得隐式 cast 或忽略字段。源名称/列号以格式 profile 定义，不猜 RGB/强度 |
| 文件格式参数 | profile 冻结编码、标量/list 范围、列/注释规则和读写方向；后端能力表与前端、App Contract 同源。未通过 M1 格式验收的 profile 不列为可用；不开放自由库名/函数名/自动换库参数 |
| 数值/有效性 | 保留源 dtype、点顺序、属性及无效值；建立有效性证据，不自动删点、去重、降采样、填洞、变换或归一法线。单位未知可读取与查看，不能冒充已确认 mm |
| 资产恢复 | 核验 project/resource/version/hash/kind 与 manifest/blobs 后恢复独立数组；生成新的 run/observation/cloud 身份，历史身份只作来源。零点派生资产可管理/导出，但不得作为非空调用输入 |
| 执行/失败 | 先核验长度、摘要、格式/布局与预算，再在现有 worker 读取；全量完成后才发布 cloud 引用。截断、重复字段、越界、无法证明完整读取、解码超预算、摘要错误均执行失败，禁止返回部分云 |
| 验证 | 字段重排、float32/64、非有限数保留、缺/多字段、编码不符、损坏、取消、asset 换项目/版本/hash、旧运行引用；Preview 与 Runtime 使用同一读取实现 |

#### 7.4.2 normalize-units：统一单位

| 项目 | 定稿规则 |
| --- | --- |
| 输入/输出 | `cloud` → `cloud`；不新增变换矩阵或定位状态 |
| 参数 | `target_unit` 固定 `mm`；可选 `source_unit:m/mm/um` 仅用于原单位未知时显式确认。源已有单位时传入不同 source_unit 必须拒绝，不作为强制覆盖 |
| 算法 | 已知长度比例统一转换；positions 及浮点长度标量保持各自 float32/float64 dtype，可在有界块内用 float64 计算再写目标数组，不保留整云 double 中间副本。整数长度标量仅在转换结果仍为整数且原 dtype 可表示时保留，否则明确拒绝，不截断或隐式改型。单位相同且无确认变化时可返回同一不可变引用 |
| 属性 | normals、colors、validity、sample_origin 不缩放；unit 明确为 m/mm/um 的标量按相同比例转换；其他量纲或未知 unit 原样保留，不伪称已统一。坐标 frame/轴不变，记录源单位与转换比例 |
| 状态/边界 | unavailable 透传原因且不分配；ready 空云保持 ready。有限输入转换溢出是执行错误；原本无效坐标仍保持无效，不把 Inf 转成零 |
| 验证 | 当前 float32 输入/输出 dtype 不变；同一几何的 m/mm/um 输入独立预期、混合属性、整数标量不可表达时拒绝、未知单位、重复执行、输入只读、声明 float64 的小差异及大坐标、取消后无残留 |

#### 7.4.3 filter-valid：过滤无效点

| 项目 | 定稿规则 |
| --- | --- |
| 输入/输出 | `cloud` → `cloud`、`summary:value.v1`；summary 采用本表关闭的结构，不接入产品公差判断 |
| 参数 | `finite_fields:字段名数组` 必须包含 positions，其他字段显式选择；`sentinels:数组` 可为空；始终尊重已有 validity，不提供忽略原掩码开关 |
| `sentinels[]` | `field:字段名`、`values:分量值数组`、`match:all/any`；长度等于字段 components，值必须可由该 dtype 精确表示；int64/uint64 分量使用规范十进制整数字符串，其他分量按严格数值类型校验，不接受超 dtype 范围。精确比较，不暗设 epsilon。NaN/Inf 由有限值规则处理，不写入 JSON 哨兵 |
| 算法 | 保留 validity 有效、所选字段各分量有限、未命中任何哨兵的点；按源顺序形成只读索引子集，借用父数组。全部属性与 sample_origin 同步取子集；不把零点坐标默认无效 |
| summary | `state:ready/unavailable`、`reason:Identifier/null`、`input_count/kept_count/removed_count:非负整数或 null`、`invalid_counts:{mask,non_finite,sentinel}`。ready 时计数齐全且 kept+removed=input；原因计数允许重叠，不相加当 removed。unavailable 时全部计数与 invalid_counts 为 null |
| 空/失败 | 全部过滤后输出 ready、point_count=0，后续测量按缺支持处理；非法字段/哨兵为配置错误，不返回空云掩盖错误 |
| 验证 | NaN/Inf、合法零值、掩码与哨兵交叠、0/全保留/全剔除、稳定顺序/源索引、父资源借用与分支清理 |

#### 7.4.4 cloud-preview：点云预览

| 项目 | 定稿规则 |
| --- | --- |
| 输入/输出 | M1 为 `cloud` → `body:response-body.v1`，body 的关闭结构见 9.9；声明 `ui.preview`。features/evidence/table 端口在 M2/M3 实现对应叠加时增加，不先发布空能力 |
| 参数 | `point_limit:正整数`、`color:严格联合`；point_limit 必须不超过服务显示策略。color 为 `{mode:solid}`、`{mode:rgb}` 或 `{mode:scalar,field,component,range}`；component 为 0 起始整数且小于字段分量数。range 为 `{mode:finite-range}` 或 `{mode:fixed,min,max}`，min/max 为规范十进制字符串，解析后有限且 min<max；不用 JSON number 表达 int64/uint64 边界 |
| 采样 | 首个方法固定为确定性源序号均匀选取，不求平均、不产生新几何；候选为 validity 有效且 XYZ 有限的点，保留源顺序。候选数 K、显示数 M=min(K,point_limit)，M>1 时取 floor(j*(K-1)/(M-1))，j=0..M-1；M=1 取首个，K=0 不取点。保存源索引；不得称为均匀空间采样或保证细小缺陷可见 |
| 颜色 | rgb 需要已有 colors；scalar 需要合法字段/分量；非有限 scalar 用显式无效颜色/计数，不影响测量，也不自动改为另一字段。有效色标无范围时显示无有效标量，不伪造 0..1 |
| 副作用/失败 | 仅有界显示交接，无自动原云保存。坏配置仍执行错误；显示容量、编码/发送问题进入现有 display_error，不改业务量值/产品判定。源释放前完成独立显示副本，显示不可借用原云 lease |
| 验证 | 精确采样索引、空云、全非有限、色标、源释放后可显示、无观察者/慢观察者、切 run/node/generation、卸载/WebGL 丢失，详见 9.8/9.9 |

#### 7.4.5 save-cloud：保存点云资产

| 项目 | 定稿规则 |
| --- | --- |
| 输入/输出 | 必填 `cloud` → `resource:measurement-resource-ref.v1`；这是新 payload 对现有 ResourceReference 字段的严格注册，不另建资源身份。完整字段见 10.13 |
| 参数 | `mode:original/derived`；`target` 为 `{kind:new,name}` 或 `{kind:new-version,reference,name}`，name 复用现有资源名称约束。new-version 引用为期望基版本，版本冲突明确失败，不自动覆盖/重试 |
| 保存范围 | original 沿源关系保存当前输入的原文件/原始数组及原始 spatial/source_metadata/dtype，不把归一或变换后的元数据贴到原件；derived 保存当前 cloud 的全部字段/有效性/空间/追溯及独立物化子集。禁止字段筛选或 dtype 窄化 |
| 资源责任 | 执行准备识别 original 保存依赖并保留相应源，不能等源释放后按文件名再找。无法定位唯一原始来源或来源已失效时拒绝；节点通过受控资源写入边界提交，不直接写数据库/任意路径 |
| 提交 | 复用现有资源版本及 ObjectStore，数据块完成且核验后提交 version.json；输出只能包含已提交的不可变版本。取消在提交前清理临时块；提交后取消不能删除已提交版本，记录真实副作用身份供审计 |
| 幂等 | 同一次 run/node/invocation 的提交身份由平台形成，重入核对既有提交与摘要；用户新一次执行属于新保存动作，不按同名文件误去重。若既有资源服务缺此写入边界，在原服务扩展，不另建提交服务 |
| 验证 | 原件逐字节、派生逐字段/索引、空派生云、版本冲突、磁盘满、写入/提交两侧取消、重复提交、发布依赖删除保护 |

#### 7.4.6 export-cloud：导出交换文件

| 项目 | 定稿规则 |
| --- | --- |
| 输入/输出 | cloud 输入与 `source={kind:asset,reference}` 二选一；cloud 分支 `source={kind:cloud}`。输出 `file:file-ref.v1` 与 `summary:value.v1`，file 只引用已完成的不可变对象 |
| 参数 | `profile_id/profile_version` 取后端已验证的写能力；`fields:不重复字段名数组` 必须包含 positions；`file_name` 只允许文件名，不含路径；`spatial_acknowledged:bool` 在交换格式不能表达完整空间信息时必须为 true |
| 数据规则 | 输出沿当前单位，不在导出中隐藏单位转换；字段可显式不选，但 dtype/值不可静默窄化。能力不支持所选字段/编码时拒绝，不换库、换编码或自动删字段 |
| summary | 关闭结构：`profile_id/profile_version`、`point_count`、`fields_written/fields_omitted:字段名数组`、`spatial:5.6 对象`、`source_reference:ResourceReference/null`、`file_checksum`。全部字段必填，source_reference 仅资产来源非空；summary 不是无损资产，也不保证单独流转文件包含完整单位/追溯 |
| 写出 | 流式/受控写临时对象，检查完整性后发布；写接口 true 不自动等于成功。独立逐字段重读验证属于该 profile 的启用条件；11.2.8 已确定修复路线，M1 未验证完成前不能开放对应 profile |
| 验证 | 当前样本 float32 往返、声明 float64 的独立精度用例、源不可变、字段选择/拒绝、颜色/法线、空派生云、元数据损失确认、磁盘满/短写/取消、错误文件不返回下载引用 |

#### 7.4.7 M1 接线与契约审计案例

- 文件：既有 App Entry file binding → read-cloud → normalize-units → filter-valid → cloud-preview；save/export 是显式旁路。
- 同机数组：既有 App Entry 新类型化云 binding → normalize-units → filter-valid → 相同后续节点；没有第二套算法或 read-array 节点。
- 配方固定资产：read-cloud 的 asset 参数持有完整 ResourceReference → 相同后续节点；发布冻结该具体版本，不解析“最新”。
- 合法最小布局示例：2 个 XYZ float32 点，positions offset=0、byte_length=24、content_length=24；若输入显式声明 float64，则为 48 字节。有效性如有必须是独立 2 字节块并计入总长度。不能把 48 字节 descriptor 套到 24 字节载荷。
- 非法组合：file 与 asset 同时存在、运行内 cloud_id 作为跨请求输入、未知单位却不确认即归一、字段重复/块重叠、把显示点数组接入测量、将 source 的历史 run_id 当当前 owner，均在执行/引用边界拒绝。
- 三态规则升级仍在 M3.4；M1 的 unavailable、空云、显示失败与任务失败不是产品 INVALID，不能提前改写现有二维 Check Limits。

## 8. 量值定义与测量质量

### 8.1 各类量值的约束

| 量值 | 必须声明的条件 |
| --- | --- |
| 单点高度 | 查询位置、方向、支持半径、邻域点数、插值/拟合方法及外推权限 |
| 整体高度/厚度 | 顶/底面定义、测量轴、评价位置/范围、是否采用支撑贴合假设 |
| 相对高度/台阶差 | 同一位置的面间差或独立 ROI 统计差；符号方向 |
| 长宽/间距 | 工件轴、投影面、包络/拟合边/截面方法及可见性 |
| 孔径/圆心 | 圆截面或圆柱模型、内外轮廓、支持弧、缺口和拟合约束 |
| 槽宽/间隙 | 边缘选择、共同有效区、局部宽度还是极值/统计宽度 |
| 平面度/圆度 | 评价方法、采样域、预处理和收敛证据；残差统计单独输出 |
| 平行度/倾角 | 公差带宽与法向夹角分别命名、分别校验量纲 |
| 翘曲/缺陷 | 参考、支持域、缺测处理及区域阈值；不默认都是材料缺陷 |
| 面积/体积 | 投影或表面、封闭条件、基准、积分单元及缺失覆盖 |
| CAD 偏差 | 基准/最佳拟合模式、自由度、距离定义、表面朝向和离散误差 |

### 8.2 质量证据

逐项记录有效点数、内点率、支持域、采样间隔、拟合残差、角覆盖、最大空缺、矩阵/拟合条件、插值/外推标志及范围。阈值来自方法/模板配置，不把本样本的 0.03 mm、特征数量或 ROI 当所有工件默认值。

拟合可使用显式稳健估计，但剔除真实缺陷会改变评价对象。计量必须保留剔除证据和策略；“去噪后平面更平”不能自动作为形状公差改善结论。显示降采样不参与最终量测；定位粗采样后应回到满足误差预算的测量数据。

半圆/短弧的小 RMS 不能证明直径可靠。应检查角度覆盖、最大缺口、半径可辨识性、阈值敏感性及独立参考。外推允许范围由方法明确声明，不把所有缺测都无条件判 NG 或无条件判有效。

算法结果至少区分 measured、interpolated、extrapolated 等证据属性；这些属性不是 OK/NG。拟合残差、参数敏感性、数值收敛误差、重复性、测量不确定度是不同概念，不能用一个 confidence 分数替代。

### 8.3 公差、INVALID 与执行错误

- OK：所有启用的必检项具备有效量值，且按明确限值/判定规则通过。
- NG：必要观测有效，但至少一个必检条件超差。
- INVALID：存在缺失、歧义、单位错误、不可测、质量不足或不能完成判定的必检项。混合无效/超差时汇总为 INVALID，并保留已有超差项，不丢弃信息。
- 执行错误：坏配置、I/O 故障、依赖不可用、timeout 等仍按平台错误传播，不能伪装成正常产品 NG。

必检集合为空不得返回 OK；选填项不应悄悄成为必检，但仍保留质量信息。缺测或无效 NumericItem 的 value 为 null，禁止 NaN/Inf 或零占位。

测量有效但不确定度判定规则无法给出结论时，应保留真实量值和 `valid=true`，在判定层给出 INVALID/明确原因；不能为表示“未能放行”而篡改原始量值有效性。最终判定规则及是否采用保护带须由计量需求明确，不自行承诺标准合格。

现有 Check Limits 的 boolean 输出只能表示通过/不通过，不能单独表达三态。实施须统一版本化其 summary 语义、节点版本、UI、模板、协议交付和持久结果消费者，不在 metrology3d 内另做同名规则。公开版本迁移显式实施，旧发布快照不可被无提示改义；不保留隐藏兼容节点或静默降级。

### 8.4 规则真值与新结果契约

继续复用 NumericItem/NumericTable/LimitRule，限值开闭区间也保持原定义。变更发生在判定汇总和结果记录，不改变历史量值。规则只针对启用项，必检集合取冻结配置而不是本次成功结果。

| 输入/规则条件 | 单项 state | 必检时的总状态影响 | `passed` |
| --- | --- | --- | --- |
| 有效、同单位、在限内 | ok | 全部必检均如此才 OK | true |
| 有效、同单位、超上限或下限 | ng | 无必检 invalid 时为 NG | false |
| 缺项、无效量值、单位不匹配、质量/判定依据不足 | invalid | INVALID，优先于 NG | false |
| optional 项为 ng/invalid | 保留实际状态 | 不改变必检总状态 | 按自身状态，不冒充通过 |
| disabled 项 | 不参与本次判定 | 不参与计数；配置仍保留 | 不生成伪通过项 |
| 没有启用的必检项 | 无可用总判定 | INVALID / no_required_checks | false |
| 配置非法、资源损坏、依赖/执行失败 | 不生成正常判定 | 任务失败/取消，不包装为产品 INVALID 或 NG | 无成功输出 |

新版 Check Limits 保留 `result:boolean.v1`，精确定义为“可放行”。`summary:value.v1` 内加入固定 `format_id=amvision.limit-check.v2`，逐项 `state`，总 `state` 为 ok/ng/invalid；直接把 summary 连接到 Result Record 的 decision 输入，不新增重复摘要端口，也不经过布尔往返。节点版本、schema 与发布依赖同步变化，不能把旧 summary 当同版兼容输入。

summary 字段：`format_id`、`observation_id`、`state`、`passed`、`reason`、`items`、`required_count`、`required_ok_count`、`required_ng_count`、`required_invalid_count`、`optional_count`。前三个 required 状态计数之和必须等于 required_count。去掉含混的 passed_count：当前实现计入所有启用项，不能拿它与 required_count 计算通过率。items 保存 item_id、required、state、passed、量值 valid/value/unit、actual_unit、上下限/开闭标志和 reason。总 reason 为 no_required_checks/required_invalid/required_out_of_limits 或 null，详细原因留在各项。

首批 decision_policy 只支持明确的数值区间判断；不宣称已完成测量不确定度保护带算法。配置要求尚未支持的决策方法应在发布时拒绝；已实现方法执行后依据不足才是决策 INVALID，不能以普通区间判断悄悄代替。

现有 `result-record.v1` 必须升级为显式 `result-record.v2`，不能只向 v1 enum 添加 INVALID。新版固定 `format_id=amvision.result-record.v2`，必需 `state:ok/ng/invalid`、`passed:boolean`（仅 ok 为 true），保留明确的可选 `reason/metrics/conditions/metadata/alarm/image/video`。不同时保留 ok_ng/ok 旧别名；alarm 是独立设备/流程信息，不等于测量 INVALID。三维证据作为受控结果附件引用，不能放进 image 字段。

Result Record 消费完整判定对象并验证 state/passed/逐项一致性；普通 Process Decision 的布尔业务可产生有效 ok/ng，但不能声称从 false 恢复 invalid。`core.rule.ok-ng-decision` 等纯布尔节点不承担三态聚合，三维链路禁止先丢弃原因再把其输出接回正式测量判定。原来使用字符串 decision 的受影响模板需显式改图并重发，不保留运行时双格式分支。

批次汇总增加独立 invalid_count；unknown_count 仅表示缺字段/不合约输入，不能与 invalid 合并。总体通过率分母仍为结果总数，不能排除 INVALID 后提高通过率；有效件通过率如需提供必须另命名并另写分母。零件数、invalid、alarm 和任务错误分开统计。SPC 不把缺测 null 转成零样本。

### 8.5 结果读取方与修改责任

“消费者”在本文仅指读取、显示或交付结果的现有代码，不是新增进程或服务。例如孔径 10.00 ± 0.05 mm，可靠测得 10.02 是 OK，可靠测得 10.12 是 NG，缺孔边缘而不能可靠测量是 INVALID；三种结果必须到达表格、记录和外部接口。执行异常另走任务错误，不能混入产品判定。以下清单用于 M3.4 的同批变更与回归，不要求在 M1 点云读写前先升级所有结果模块。

下表来自本轮源码检索和关键实现阅读，不包含无法访问的外部上位机程序。生成 Catalog、示例和文档须由对应源头更新，不能只手改生成物。所有变更集中在原模块，不新增三维专用规则、PLC 或结果管理器。

| 消费者 | 真实位置与现状 | 迁移/验证要求 |
| --- | --- | --- |
| 数值生产/合并 | `backend/contracts/workflows/metrology.py`、`core_nodes/logic/value/numeric_tables_merge.py`、numeric_table_to_value；connector_nodes 的 measure/pin_array_locate | NumericTable v1 不改义；同 observation、唯一 item_id；二维/三维缺测测试一起覆盖 |
| Core 判断 | [measurement.py](../../backend/nodes/core_nodes/support/measurement.py)、[check_limits.py](../../backend/nodes/core_nodes/logic/rules/check_limits.py)、ok_ng_decision/process_decision | 真值表、可放行 bool、逐项状态/计数；不从 bool 反推三态 |
| 结果契约与构造 | [core_catalog.py](../../backend/nodes/core_catalog.py)、[inspection_record.py](../../backend/nodes/core_nodes/support/inspection_record.py)、io/output/records/result_record.py、process_decision.py | v1 当前只认 OK/NG、ok；v2 源头/构造器/生产者同批改，拒绝不一致 state/passed |
| 批次/Workflow 输出 | support/batch_result_summary.py、io/output/records/batch_record.py、batch_result_summary.py、workflow_result.py；logic/collections/array_summary.py | 区分 invalid 与 unknown，冻结分母；通用数组路径配置必须迁移，不静默猜旧字段 |
| 序列化与保存 | [payload_adapters.py](../../backend/nodes/payload_adapters.py)、logic/value/payload_to_value.py、io/output/storage/json_save_local.py、csv_append_local.py | 类型白名单、列名、空值、精度和新 format；不得把 invalid 转 NG/0 |
| HTTP/数据库 | custom_nodes/http_nodes 的请求 payload 与 Catalog；database_nodes/providers/sql 的 sql_upsert schema/Catalog | 接受 v2；绑定路径和 SQL 字段映射审核；不自动修改外部数据库 schema |
| PLC | [result_signals/payloads.py](../../custom_nodes/plc_nodes/protocols/modbus_tcp/backend/runtime/result_signals/payloads.py)、同目录 config/sources/execution 及 write_result_signals Catalog | 当前严格 OK/NG 与 ok 一致；新格式明确状态映射及写入失败策略。地址/编码由现场配置，不假设 NG 就是 not passed；不把顺序写多寄存器宣称为事务 |
| 参数/静态校验 | frontend 的 WorkflowLimitRulesEditor、limit-rules、recipe-validation、static-numeric-items、trusted-recipe-providers | 已有空规则/缺必检检查保留；三维 provider 扩展现有注册；未知动态项不能伪报静态有效 |
| 表格显示 | [result-format.ts](../../frontend/web-ui/src/shared/ui/image-viewer/result-format.ts)、result-geometry.ts、WorkflowResultTable.vue、WorkflowPreviewTable.vue、useWorkflowPreviewDisplays.ts | 原 result 格式把 false 显示 NG；新增明确 decision-state 格式显示三态，不修改所有普通 bool 的含义 |
| 后端预览表 | core_nodes/support/preview_results.py、io/preview/value_preview.py | 与前端 format 白名单同步；二维几何不承载三维证据，保留现有行/列/字节限额 |
| App/模板/SDK | WorkflowAppListPage、newAppDraft/输出绑定、docs/examples/workflows、API 示例、仓库 .NET SDK 与文档 | 默认 ok_ng 路径改为新字段；SDK 用三态 fixture 验证 JSON/回调，示例同步；外部消费者另行签收 |
| 测试 | test_core_payload_contracts、test_industrial_rule_nodes、test_connector_metrology_contracts、test_preview_result_table 及前端/SDK 测试 | 正常/NG/INVALID、混合状态、空必检、optional、晚返回、发布拒绝、输出一致性 |

### 8.6 发布执行身份与审核重发

源码核对：app_version_service 会冻结节点版本/定义摘要和包 manifest 摘要；[worker/process.py](../../backend/service/application/workflows/worker/process.py) 校验冻结文件内容指纹，但执行仍使用当前 handler。runtime_service 的定义变化检查用于只读画布提示，不能等同执行时锁定旧代码。因此不能仅凭“文件指纹没变”宣称旧规则仍按旧算法运行。

现有 [Workflow App 版本管理](../architecture/workflows/app-versioning.md) 已完整定义草稿、不可变版本、依赖文件、Runtime 选版、generation、回滚和运行追溯。本节不是重做这些功能，也不能把当前节点实现身份字段从部分指纹材料中排除，单独当成“没有版本校验”的证据。需要核对的是实际加载代码与发布要求的一致性；检查在既有发布/启动边界完成，不每次调用扫描包目录。

已确认升级规则：受影响的旧发布保留只读历史，审核配方和交付映射后发布新 AppVersion，才允许在新实现上运行。不保留旧算法执行分支，不在本轮删除或迁移数据，也不能凭历史 NG 的原因猜测重写为 INVALID。

影响范围必须由依赖和引用盘点得出：新增不被旧图引用的三维节点不要求旧 App 重发；共享 Check Limits/Result Record 改义时，只对使用被改变节点/结果契约的发布实施审核。资源格式版本也不等于数据库必须迁移：新点云资产可只使用新版本；确需改旧二维引用时，先列明原因、映射与恢复步骤。不得借本节点包实施全仓库旧数据清空或全部发布停用。

实施时在现有发布/导入/启动与恢复准入中共享同一依赖执行校验：冻结依赖与当前节点版本、定义摘要及包实现身份不一致时拒绝执行，给出受影响节点/资源及审核重发要求。Preview 使用当前草稿，同样检查输入/资源/契约，不能靠 Preview 绕过旧发布拒绝。单靠 manifest hash 不能证明 Python 源码未变；受控发布必须绑定可核验实现版本/发行内容，相关身份生成复用既有发布机制，不另建版本管理器。

迁移顺序：消费者清单与发布依赖盘点 → 统一契约/生产者/消费者修改及测试 → 冻结新实现 → 对受影响旧版标只读/阻止恢复 → 审核并创建新发布 → 在新发布验证 SDK/PLC/DB/文件输出。数据结构若需变化，单独提供正式迁移和回滚方案；M0 不执行数据操作。

## 9. 测量证据与前端设计

### 9.1 证据结构

每个测量项沿用 NumericTable 的 `observation_id` 与 NumericItem 的 `item_id`，以该组合关联证据，不另建一套测量编号。证据至少包括目标/参考特征 ID、坐标系、查询位置、测量方向、实际端点、辅助线/圆弧/参考面、观测支持区、外推区、算法方法和资源版本。大点集与标量场仍使用引用。

显示偏移、标签位置、颜色和可见性属于呈现配置，不能写回测量端点或改变量值。前后端显示、报告导出和结果表必须使用同一份证据，禁止分别重算一套数值。

### 9.2 交互与界面边界

- 使用共享 Vue 3 + Three.js 查看组件，供样本、节点 Preview 和 Runtime 结果复用，不建立独立三维业务导航或另一套前端框架。
- 参数主要由 Catalog/schema 驱动；ROI、基准、特征关联和尺寸定义通过已有受控编辑扩展与共享控件完成，不新增任意在线脚本加载。
- 支持点云/高度图/截面联动、正交与透视视图、坐标拾取、单位与坐标系显示、参考面及 ROI 编辑。
- 点击数值表定位测量项，联动显示真实边界、尺寸端点、方向和原因；逐特征、分组和总览互相一致。
- 白色/原始颜色、原始 Z、基准高度、局部高度差和偏差场为不同显示模式；恢复白色只是关闭着色，不删除数值。
- 颜色映射范围、显示裁剪和算法 ROI 是三个独立设置。色标 0–10 mm 不得隐式裁掉范围外测量点。
- 实测边界与拟合/外推几何同时使用线型、文字或状态区分，不只依赖红绿色。
- 俯视图上的高度标签不能冒充真实高度方向；侧视/截面显示真实测量方向和参考位置。非等比例截面需明确标示。
- 预览 LOD 拾取要返回原始点/原始支持区的核对结果；预览点、格心或插值点不能标成原始实测点。
- 模板 ROI 保存在工件坐标系，不保存在某次屏幕像素位置；模板发布后按不可变版本复算。

### 9.3 生命周期与防错

沿用现有任务身份、请求代次和取消模式。切换数据、项目、节点或运行后，旧请求、旧 WebSocket 消息、旧拾取和旧计算结果不能覆盖新对象；卸载后不得建立订阅或重连。

释放 WebGL geometry/material/texture、渲染循环、事件监听、worker、Object URL 和网络请求。使用稳定的显示预算及受控并发加载；不能一次性让浏览器解析完整的大型 ASCII PLY。宽桌面和工控机视口需验证标签碰撞、遮挡、字体、离线资源与显存释放。

### 9.4 消费状态、预算与版本

| 状态/消费者 | 允许操作 | 禁止操作与释放责任 |
| --- | --- | --- |
| 文件待确认单位/坐标 | 查看字段/有限预览，显式确认并产生新数据 revision | 不允许据未知单位发布物理尺寸合格结论；旧确认不能套到新文件 |
| Preview 活动 | 在 session 预算内拾取/编辑 ROI/重算，使用完整源核对 LOD 拾取 | 切换/关闭取消旧请求，关闭 session owner；不能仅 dispose WebGL 后保留服务端源 |
| 运行完成且源已保存 | 看数值/证据，按权限显式重新加载资产 | 不自动后台加载全部云；复算使用新 run 并保留方法/配方版本 |
| 运行完成且源未保存 | 查看数值/有限证据，显示“源数据未保留” | 禁用原精度任意查询/重拟合；不把源未保留改写为原测量 INVALID |
| 量值 invalid / 规则 invalid | 显示原因、缺失支持、已存在的 NG 项 | 不以 0/NG 取代；颜色之外有文字/图例；不能显示旧运行结果作为当前量值 |
| 交付失败/超预算 | 明确区分计算结果与证据/保存交付状态 | 不显示“完整保存成功”，不通过无限重试或隐式队列续传 |
| 受本次语义升级影响的旧发布只读 | 查看冻结配置及历史结果，审核后新建发布 | 禁止受影响版本启动/恢复；无关发布不受影响；前端禁用不能替代后端校验 |

配置归属：输入字节上限在平台/App Contract；运行数组/索引/缓存预算在现有执行资源配置；Preview 持有时间和字节在 session 配置；显示点数/显示字节在后端证据生成与前端加载的共同契约；结果附件保留期在现有结果策略；算法参数在冻结配方。全部预算需正值/有限值，缺少必要配置时不宣称大数据能力可用，不把未定值转换为 unlimited。

最低 RAM、并发、单次时限、显示上限和保留期尚未有产品数值，本轮只明确配置责任与越限行为，不抄当前机器容量。结果页面只消费同版本的量值/判定/证据，不重算正式尺寸；静态报告和交付节点使用同一结果快照。前端验证分为三态 formatter、资源编辑、请求代次/卸载、发布升级和真实大数据视图，后续测试放 `tests/frontend/`。

### 9.5 工程师与现场人员的使用路径

两类使用路径复用已有视图，不新增用户角色体系、页面设计器或独立发布单元。权限仍由项目既有机制处理；不能把只读界面当成后端权限验证。

| 使用场景 | 现有入口 | 操作流程 | 必须避免 |
| --- | --- | --- | --- |
| 工程师制作配方 | Workflow 节点编辑器和 Preview | 选择样本/单位 → 预览点云 → 添加 ROI/基准 → 添加尺寸 → 配置限值/交付 → 预览审核 → 发布 | 用大段 JSON 或手填内部资源 ID 代替常规配置；修改参数即触发正式生产调用 |
| 工程师排查结果 | Preview 或 Runtime 只读画布 | 选中节点/结果行 → 查看支持点、基准和测量线 → 查看失败原因 → 返回草稿调整并重发 | 在运行图直接修改已发布节点参数；把最新草稿当实际生产版本 |
| 现场人员手动测量 | 既有 App Mode | 确认 App/版本/Runtime → 提交公开输入中的文件/参数 → 调用 → 查看合格、超差或无法判定 → 查看指定测量项 | 强制操作连线、开放内部算法阈值、把 SDK 二进制输入变成浏览器 JSON 文本框 |
| 外部系统自动调用 | 既有 Runtime 监视/App Mode | 只观察当前 Runtime 的结果；需要时查看最近证据 | 打开页面、切视图、断线重连即自动执行或补发业务请求 |
| 历史结果追查 | 现有结果和资源入口 | 查看数值/判定/有界证据；已保存原云时显式新建复算 | 原云未保存时伪装可重拟合，或为了显示重新执行原生产图 |

现场视图显示当前版本、连接/运行状态、测量结果表和三维证据，隐藏连线和内部参数；公开输入来自已发布 App Contract，不能让 App Mode 私自增删必填项。SDK 专用的同机数组输入按 transport 能力明确显示为外部输入，不要求操作人员粘贴二进制或内存句柄。

### 9.6 节点参数与三维查看的交互规格

保持现有节点画布、参数检查区和预览查看区。节点卡片只呈现名称、端口、关键参数与状态摘要，复杂 ROI/尺寸配置在已有检查区打开受控编辑组件；三维查看复用同一组件，避免每个算法节点常驻一个 WebGL 场景。App Mode 沿用已有显示槽和全屏，不另造布局编辑器。

| 节点/功能 | 常规配置控件 | 三维联动与防错 |
| --- | --- | --- |
| read-cloud | 文件/受控资产选择；格式、字段映射、源单位和坐标选择；点数/属性摘要只读 | 文件更换后重新确认单位/映射；不按坐标数量级猜单位，不显示当前不支持的格式能力 |
| normalize-units / filter-valid | 带单位的选项；掩码/有限值/声明哨兵设置；前后点数与原因 | 不默认把坐标为零的点删除，不把有效性过滤写成去噪 |
| cloud-preview | 视图方向选项、颜色模式、色标范围；适配视图/复位/全屏图标 | 显示单位、坐标系和“显示采样”状态；改变色标、视角和显示裁剪不触发测量参数变更 |
| crop-roi | ROI 名称/所属坐标、形状、中心/尺寸/方向；图形编辑的应用/取消 | 拖动只改编辑草稿，应用后一次写入参数；数值与图形同一来源；不能误保存为屏幕像素 |
| fit-plane / build-frame | 参考区域、方法、法向；原点和面内轴/次基准逐项选择 | 点/面高亮与列表选择一致；缺基准明确指出，不能自动补单位姿态 |
| transform-cloud | 源/目标坐标和所用定位结果 | 显示变换方向；相机视角变动不写入变换矩阵 |
| extract-boundary / fit-line / fit-circle | 评价面、提取方法、边界/支持段选择；质量参数在高级区 | 轮廓 ID、内外圈、开闭状态、支持弧可见；不自动采用列表第一个候选 |
| height-query | 查询点列表、坐标系、方向、邻域和局部拟合要求 | 输入坐标与拾取同步；点击显示点只是选择候选位置，正式量值由后端完整支持区计算 |
| measure-step | 参考/目标两个 ROI；方向面差与统计差分别选择参数 | 交换对象后显示符号变化；不同方法所需字段互斥，不能保留隐藏旧值影响计算 |
| measure-extents / measure-edge-pair / measure-hole | 明确包络/边距/孔定义、评价方向、对象选择、稳定测量项名称 | 表格行、边/孔和尺寸线双向联动；显示拟合、实测、外推区别；无效项仍保留名称和原因 |
| 既有 Check Limits / Result Record | 复用限值表：项目、必检、单位、上下限/开闭规则；输出映射 | 合格/超差/无法判定有文字和状态标识；INVALID 不能只显示 false 或 0 |
| save-cloud / export-cloud | 显式保存原始/派生；目标、格式、字段和精度选项 | 在提交前列出不可表达字段；无源时禁用原始保存；取消或失败不显示成功下载 |

公共交互规则：

- 常用参数首先可见；高级区仅折叠方法细节，不隐藏必填项、失败原因或将未填写阈值补成未经验证默认值。相同参数在卡片和检查区绑定同一份草稿，不复制状态。
- 数字使用数值输入/步进，精密尺寸不用仅有滑条的输入；二选一使用复选/切换，方法使用选项列表，视图使用分段控件；工具按钮复用现有图标库并有名称提示。
- ROI 编辑、旋转查看、特征选择是明确互斥的工具状态，防止拖动视图误改测量区域。没有可用数据或基准时禁用对应动作并给出具体缺项。
- 参数应用后旧结果标为待重算；开始计算由现有 Preview 动作明确触发，不每次拖动自动执行整个图，不增加后台等待队列。
- 运行、取消、保存配方、发布、生产 Runtime 启停是不同动作，保持既有位置/语义；不增加一个含义模糊的按钮串行执行所有副作用。
- 故障文字说明出错对象、原因和可采取的动作；正常界面只保留必要标签/状态，不堆放架构术语、算法宣传或长篇使用说明。
- 长测量名称、负值、科学计数和不同单位不遮挡相邻内容；色标和数值列单位明确。工控机视口下保留当前动作、结果和失败原因，必要时切换面板，不缩小字体硬塞。
- 颜色之外同时使用文字/符号/线型；键盘可到达控件，选中态和焦点清楚；断线/过期/无法判定不能只靠颜色区分。

### 9.7 前端实现位置与显示交接

| 现有源码/机制 | 直接复用 | 只扩展什么 |
| --- | --- | --- |
| [WorkflowNodeParameterWidgets.vue](../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowNodeParameterWidgets.vue)、[trusted-editors.ts](../../frontend/web-ui/src/workflows/workflow-editor/parameters/trusted-editors.ts) | Catalog 参数绑定、枚举/数值/资源控件、随包构建的受控编辑器 | 三维 ROI、基准与测量项编辑；不加载 manifest 指定的远程脚本 |
| [WorkflowMeasurementResourcePicker.vue](../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowMeasurementResourcePicker.vue)、measurement-resource.service | 已有资源选择和服务调用 | 三维资源摘要、显式版本和格式能力；不新建资产选择体系 |
| [useWorkflowPreviewDisplays.ts](../../frontend/web-ui/src/workflows/workflow-editor/preview/useWorkflowPreviewDisplays.ts)、[WorkflowNodePreviewDisplay.vue](../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowNodePreviewDisplay.vue) | 显示身份、失效状态、节点显示适配 | 增加显式三维显示类型与共享 Vue/Three.js 组件，不塞进二维 image overlays |
| [WorkflowPreviewViewers.vue](../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowPreviewViewers.vue)、Preview session | 现有查看入口、会话和取消/清理 | 三维查看和受控拾取；相同 viewer 支持可编辑与只读两种模式 |
| [WorkflowAppModeDisplayGrid.vue](../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowAppModeDisplayGrid.vue)、[workflow-app-mode.ts](../../frontend/web-ui/src/workflows/workflow-editor/app-mode/workflow-app-mode.ts) | 发布版显示槽、ui.preview 选择、同一运行结果 | 三维 body 的验证和渲染，保持 node_id/output_port 身份；不增加 App Mode 专用连接 |
| [WorkflowLimitRulesEditor.vue](../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowLimitRulesEditor.vue)、WorkflowResultTable | 限值编辑、测量项和表格 | 三态文字、同观测证据选中联动；不重做规则编辑器或用普通 bool 猜 INVALID |
| WorkflowPublishDialog、版本历史、Runtime 选版 | 草稿/发布/运行与版本冲突处理 | 需要时展示明确的受影响节点/资源和审核要求；不新增三维发布页面 |

三维显示不是每个算法自动返回全云。cloud-preview 在图中显式连接数据，生成有界显示 body，通过既有“完成后单次交接”进入编辑态、Runtime 监视和 App Mode。只扩展合法显示类型与资源传输，不增加逐节点进度、第二条 WebSocket、跨运行结果缓存或显示重放。显示慢客户端仍不能阻塞业务返回或延长原云的借用时间。

M1 显示 body 的详细字段已在 9.9 定稿，覆盖格式版本、观测/数据身份、空间单位与坐标、有界点/属性、采样方法与原点映射及不可用状态；特征/尺寸证据叠加随 M2/M3 扩展。运行身份沿既有观察消息取得并交叉核对，不再自建运行编号；公开业务输出与显示输出保持独立。

页面不持有 1 GB 全云，也不访问本机 mmap 句柄。工程师精确拾取复用 Preview 持有源的受控请求，携带当前观测和参数 revision；生产源已释放时只允许查看证据。浏览器浮点显示不作为测量真值，显示原点平移等渲染处理不能写回算法坐标。

### 9.8 前端验收用例

| 场景 | 通过条件 |
| --- | --- |
| 制作首个配方 | 使用文件选择、字段/单位控件、ROI 和基准控件、测量项/限值表完成 F1–F7；常规操作不要求 JSON 或内部 ID |
| 文件/节点/项目切换 | 旧文件确认、旧 ROI 编辑回调、旧解析/拾取结果不能写入新对象；取消或关闭编辑不提交草稿 |
| 异步晚返回与卸载 | request generation、run/observation/revision 校验；卸载后不建订阅、不重连；释放请求、监听、渲染循环、Object URL 和 WebGL 对象 |
| 工件连续成功/失败 | 旧基准、量值、尺寸线不能补到失败工件；INVALID、执行失败、证据失效分别显示 |
| App Mode 和监视 | 只读内部参数、只消费所选 Runtime 实际版本；切视图/重连不执行图；公开输入与发布契约一致 |
| 单位与精度 | 数字、色标、尺寸线同单位；显示舍入不改变原始值/判定；显示采样不改变正式测量支持点 |
| 无源与有界显示 | 未保存源明确不可重拟合；显示失效不自动重跑图；超显示预算不扩大到全云或拖住业务 ACK |
| 工控机操作 | 现有明暗主题、长标签、缩放、标准桌面与目标工控视口、键盘操作；截图和真实 canvas 像素验证非空及交互有效 |
| 公差和交付 | 缺项、超差、无法判定、保存/外发失败分别可辨；纯布尔输出明确只是可放行，不能丢失详细状态 |

新增前端测试位于 tests/frontend/，同时复用现有测试工具和真实浏览器验证；不移动无关历史测试。本轮没有运行上述用例或生成 UI 原型。浏览器只读访问停在登录页，交互规格来自上述源码和 [现有显示架构](../architecture/workflows/runtime-display.md)，不记作实际页面验收通过。

### 9.9 M1 三维显示正文与界面规格

显示沿现有 `response-body.v1` 增加显式类型，不另建显示连接/Runtime。外层 Runtime、AppVersion、revision、generation、worker、run、node、output_port、invocation 和 sequence 沿 [现有观察 v1](../api/workflow-runtime-preview.md)，不得由算法包伪造。下面是拟实现的关闭正文，不是当前前端已经认识的类型。

| 字段 | 类型、必填与生产/读取责任 |
| --- | --- |
| `type`、`format_id` | 固定 point-cloud-preview、amvision.point-cloud-preview.v1；节点生成，Preview/Runtime 捕获与共享 renderer 显式识别 |
| `state`、`reason` | ready/empty/unavailable；ready 要求 display_point_count>0，empty 为 0（原云可非空但无有效可显示点）；二者 reason=null，unavailable 必须有 Identifier 原因；三者都不是 OK/NG |
| `observation_id`、`cloud_id`、`revision` | 来自输入，供同一外层 run 内关联；unavailable 的 cloud_id/revision 必须 null，与 5.9 一致；不是可重新借用原云的凭据 |
| `spatial` | 5.6 的完整空间声明，未知单位明确显示“单位未确认”；浏览器不根据坐标大小猜单位 |
| `source_point_count`、`display_point_count`、`excluded_non_finite_count` | ready/empty 为非负整数；source_point_count 为最初输入总点数，不是过滤后子集点数；display 不大于实际可显示候选数；unavailable 为 null。无效点不投影成原点 |
| `sampling` | ready/empty 必填 `{method_id:source-index-uniform-v1,requested_limit:正整数}`；unavailable 为 null；显示算法、选择数可审计，不参与正式计算 |
| `bounds`、`render_origin` | ready 必填：bounds 为当前显示点有限坐标 min/max 三元组，render_origin 为该范围中点；empty/unavailable 为 null。原点仅供渲染局部化，不改变空间坐标或姿态 |
| `data` | ready 为 `{encoding:base64,content_length,checksum_algorithm:sha256,checksum,fields,content}`；empty/unavailable 为 null。只装独立显示副本，不装原始云 lease/系统路径；长度与 hash 校验后才创建 TypedArray |
| `data.fields[]` | `name/dtype/components/count/offset/byte_length`，little-endian、按 dtype 对齐、紧密分量、无重叠，填充为零且末块结束等于 content_length，count=display_point_count。必填 positions 保留源 float32/64、source_indices 为最初输入原始行号的 uint64×1，过滤/重读后不重新编号，每值小于原始 source_point_count；rgb 模式另必填 colors:uint8×3，scalar 模式另必填 scalar:源数值 dtype×1，其他模式禁止无关块。整数属性不得经 JSON number 损失精度 |
| `color` | unavailable 为 null；其他状态为严格联合 `{mode:solid}`、`{mode:rgb}` 或 `{mode:scalar,field,component,min,max,invalid_count}`。无有限标量时 min/max 为 null，否则为源 dtype 的十进制字符串，避免 int64/uint64 JSON 舍入；invalid_count 非负。finite-range 仅针对显示样本，renderer 不重新选择另一个字段 |
| `source_asset` | ResourceReference 或 null，仅在已有独立完整资产与当前云内容/字段/空间一致且可访问时填写；仅存在原始祖先资产不够，不能由 cloud_id 或 file_name 猜出保存版本 |

M1 使用已有有界 JSON 观察/Preview 正文传输显示副本，不新建二进制 WebSocket 通道或证据下载服务。Base64 额外长度按 `4*ceil(content_length/3)`、加元数据计入现有消息限制；CPU 解码副本、TypedArray、渲染缓冲分别计入显示预算。现有 64 MiB Runtime 消息上限不是建议显示大小，也不能据此填写 point_limit 默认值。显示策略未配置时能力不能启用；图中 preview 节点仍照常执行，页面关闭只取消观察捕获，不能声称节点生成成本也消失。

数值给用户查看时使用保留的源精度显示点；WebGL float32 缓冲采用减 render_origin 的局部坐标，并检查与原值的显示误差。超出配置的显示误差/显存预算就显示不可用，不改变测量结果，也不偷偷降低算法分辨率。uint64 索引与属性在 JavaScript 使用精确整数处理，需要文本时转十进制字符串，不转不安全 number；仅渲染色标可作有界归一。finite-range 的 min=max 表示常量场，使用同一颜色，禁止除零；没有有限标量与常量零场分开。输入资源释放后显示仍能读取自己的正文，不能再向 worker 请求“原云第 N 点”。M2 的 ROI/查询拾取是物理坐标参数编辑，并经用户确认后重算全精度数据，不把显示抽样点作为拟合支持。

界面沿既有画布节点卡片 → 共享查看器 → App Mode 显示槽：节点卡片给单位、点数、状态和打开查看器按钮；主查看器为不嵌套卡片的三维视口，工具栏提供旋转/平移、复位、正交/透视、轴视图、色标和点大小，使用现有图标与 tooltip。工程师参数留在现有检查区；现场 App Mode 只显示公开输入、运行状态、数值与证据，禁止修改内部处理参数。M1 不显示尚未实现的 ROI/拟合/量测工具。控件适配现有明暗主题和 i18n，不依赖外网模型/字体/CDN。

创建或激活查看器时才申请受预算约束的 renderer；不能让每个未打开节点长期持有 WebGL 上下文。替换/清空 run、换节点/版本/generation、关闭查看器和卸载时，按既有异步 generation 检查阻止晚返回，再 dispose geometry/material/renderer、释放 TypedArray/监听器/动画回调。空云无 bounds，不调用基于空范围的自动缩放；WebGL context lost 明确提示，恢复只重建当前有界副本，不重跑 Workflow。

结果中的有界证据可由现有结果保存路径显式持久化；Runtime 观察通道本身仍无历史存储。配方未保存证据时页面刷新不可承诺重放；未保存完整源时禁用原精度复算。M2/M3 的几何叠加在同一 renderer 扩展已有 5.10/5.11 类型，必须匹配 observation/frame/unit，不预先发布任意 JSON 叠加协议。

## 10. 数据资产、执行资源与性能

原始输入不可变，保留内容摘要；规范化数组、空间索引、LOD、标量场和报告是带方法/参数摘要的派生产物。不能靠文件名或可覆盖绝对路径判断版本。参考 CAD、基准、标定与模板资源随 App Version 冻结，纳入导入导出和删除依赖检查。

文件输入先走现有 ObjectStore/HTTP 文件快照。大型解析、索引和测量在已有 Preview/Workflow Runtime worker 内由节点执行，不在 FastAPI 请求中直接计算；不新建三维导入 worker 或每节点辅助进程。

运行内新增类型化三维资源引用时，需要补齐分配、只读借用、派生引用、释放和取消清理；现有 image registry 不能被当成已经支持任意数组。执行内尽量共用只读数组，禁止每个节点复制整个点云。

已确认的输入边界（2026-10-21）：沿用现有 Workflow 的逐次调用方式，每次输入一份完整点云，文件和内存二进制数组都必须支持，不做连续采集流的拼接、帧队列或流式会话。每次提交的文件或二进制载荷最大 1 GB；该限制不用于解析数组或运行内存。这里的完整输入是业务语义，不禁止传输或解析时采用有界分块，也不代表全部数据必须在请求线程同时装入内存。公开容量字段须使用明确的字节数，GB/GiB 不混用。

当前图片 LocalBuffer 不能直接承担点云数据。两个输入适配入口进入统一的运行内点云资源契约，不能从“不实时输入”推导为“只能传文件”或“必须持久保存”。内存数组只需同机调用，采用现有 LocalBuffer 的外部写入与所有权交接底层，显式扩展三维类型；不扩展 ZeroMQ 点云传输，不新增 Broker、frame channel 或流式会话。mmap 的文件后备不等于长期保留一份原始点云资产。

代码核对发现，现有 [Broker 配置](../../backend/service/application/local_buffers/broker_settings.py)默认 arena 为 2 GiB、单次分配上限为 1 GiB；[客户端](../../backend/service/application/local_buffers/local_buffer_client.py)已有外部租约分配、发布交接和条件释放入口。这只能证明存在可复用底层，不证明点云类型已受支持，也不代表输入、输出、并发运行和既有图片能同时满足容量。不得仅修改 MIME、shape 或限额就把图片契约当成点云契约。

性能约束：

- 解析和规范化避免重复；二进制/内存映射只在格式适用时使用，不宣称 ASCII 可直接 mmap 成 XYZ。
- 空间索引与缓存按数据/方法/参数/坐标版本命中，设字节预算和释放策略，禁止无限按文件名缓存。
- 局部 ROI 查询优先避免全点复制；全局算法需声明峰值内存和取消粒度。显示 LOD 与计算分辨率分开。
- 控制原生库线程与现有 Runtime 并发的乘积，避免每次调用新增线程池或抢占模型资源。
- 不增加隐藏等待队列或自动重试。纯测量 Workflow 不添加模型实例数限制；模型调用按实际实例容量准入。
- 原生函数不可协作中断时沿用既有 Worker timeout/整组终止边界，不增加每节点辅助进程。
- 性能目标依据数据规模、算法、节拍和冻结环境制定；不能在文档中先宣称 1475 万点实时或工业精度达标。

后台任务、预览、Runtime 的容量和日志边界继续由平台统一管理。不因添加 3D Metrology 改变现有模型数值容差、并发语义、停止和恢复准入。

### 10.1 工业软件和 CloudCompare 的核对证据

查证日期为 2026-10-21。下表区分公开源码事实、公开接口事实和未公开的内部机制。CloudCompare/CCCoreLib 链接指向本次阅读的 `master` 内容，并非本项目锁定依赖；选用库前还须固定提交和发行配置。

| 来源 | 已证实的行为 | 对本项目的意义及限制 |
| --- | --- | --- |
| CloudCompare `PlyFilter.cpp`、CCCoreLib `PointCloudTpl.h` | PLY 读取先为点数预留空间，回调逐点加入点云；点坐标容器是 `std::vector<CCVector3>` | 常规 PLY 路径是内存点云，不是磁盘按需取点引擎；流式读取文件不等于算法无需内存 |
| CCCoreLib `ReferenceCloud.h` | 子集保存关联源点云和点索引，通过索引访问坐标，不复制全部 XYZ | 可借鉴 ROI/分支引用；索引仍占内存，源对象必须存活。该类包含转发写操作，不能把它当不可变、自动保活或跨进程引用 |
| CCCoreLib `DgmOctree.h` | 空间索引保存点索引与空间编码，提供邻域搜索 | 空间索引与坐标分别计入预算；不能照抄旧 wiki 的每点字节数作为当前 ABI 的实际峰值，结构对齐、容量和工作区需另算 |
| CloudCompare `ccPointCloudLOD.h/.cpp` | 显示端维护 LOD 层级、可见性及显示索引 | 显示预算与计算数据分离；LOD 本身不能证明计算支持 out-of-core。Qt 线程终止方式不移植到本项目既有进程管理中 |
| CloudCompare Global Shift and Scale | 大坐标转换到局部坐标，并保留平移/缩放元数据，以减轻 float32 精度损失 | 坐标量级、存储精度、计算精度和导出还原需分别设计，不能为省内存无条件把 float64 降为 float32 |
| VM3D V2.2.0 官方手册第 7.3 节 | 模块输入输出有 `POINTCLOUD`、`PCDEXTINF`、`BOX3D` 等专用类型，与深度图属性及几何类型区分 | 参考类型化模块连接和操作方式；公开资料不足以确认其零拷贝、内存池、mmap 或跨进程实现，不能声称已知其内部机制 |
| HALCON 24.11 的 `read/prepare/clear_object_model_3d` | 读取返回对象句柄；可为重复操作准备派生数据；清理后句柄失效，多线程清理需同步 | 可参考对象身份、派生缓存和显式释放；句柄小不代表数据不占内存，也不代表句柄能跨进程使用 |

CloudCompare 还可作为平面/局部曲面、配准和距离计算的算法参考及独立结果对照。不同软件的拟合目标、采样、支持域和异常点规则不一致时，不要求数值盲目相等；算法一致也不能替代真实计量标定。

许可证需按组件审查：CloudCompare 主程序声明 GPL；独立 CCCoreLib 声明 LGPL-2.0-or-later，CMake 文件另为 MIT，可选依赖也有各自条件。参考设计不等于获准复制或链接代码。尚未选用 CCCoreLib、Python 包装器或 CloudCompare CLI，不能据此新增生产依赖或与 Open3D 堆叠同类框架。

### 10.2 500 MB 文件与运行内存不是同一指标

以第 12 节已记录的 14,745,099 点 ASCII PLY 为例，文件为 479,677,235 字节，XYZ 声明为 float32，保存/传递采用该类型。下表是紧密数组的理论数据量，`MiB = 2^20` 字节，不是进程峰值或实测性能；float64 行只作额外副本成本对照，不是当前样本的必要分配。

| 数据 | 计算 | 数据量 |
| --- | --- | ---: |
| XYZ float32 | 点数 × 3 × 4 | 168.74 MiB |
| XYZ float64（对照，不为当前样本常驻分配） | 点数 × 3 × 8 | 337.49 MiB |
| 覆盖全部点的一份 uint32 索引 | 点数 × 4 | 56.25 MiB |
| 每点一字节有效性数组 | 点数 × 1 | 14.06 MiB |

还需计入解析工作区、原生库转换/拷贝、空间索引、法向量/标量、派生坐标、并行运行、预览数据和缓存。不能用文件大小直接预估 RAM，更不能只用 XYZ 大小承诺峰值。

需要参与计算的数据必须进入可访问的内存；是否同时装入全部点，取决于算法和底层库。内存映射允许按访问载入页面，但仍使用物理内存/文件缓存；算法若访问全体数据、要求连续 double 数组或自行复制，不能靠 mmap 自动消除峰值。ASCII PLY 不能直接映射成数值 XYZ，需要解析。

预处理扫描、部分统计可能采用分块实现；任意全局配准、邻域算法或网格重建是否能分块、边界如何处理，需要逐算法证明。显示降采样不得静默替代正式测量数据。

### 10.3 源码核对与扩展位置

核对基点为 `945872933f75f9f07954978fcd8fdaf00fb4dcc8` 及当前工作树，日期 2026-10-21。以下是静态源码事实，不是新增点云链路的测试结果。通用底层已经存在，缺少的是三维语义及其接入，不据此判定现有图片链路整体失效。

| 实际入口/符号 | 已有能力 | 三维接入边界 |
| --- | --- | --- |
| [uploads.py](../../backend/service/api/rest/v1/routes/workflow_runtime_support/uploads.py) `build_multipart_runtime_invoke_request` | `request.form()` 后按 binding 校验，再向 ObjectStore 流式写入 | 当前限额不是接收前/接收中的完整保护；补上传阶段字节与临时磁盘预算，不新建点云文件服务 |
| [input_contracts.py](../../backend/service/application/workflows/input_contracts.py) `WorkflowInputValidator` | 文件默认 512 MiB，binding 可声明限额；验证项目、长度、摘要和快照 | 点云文件 binding 显式允许 1 GB；不能扩大所有图片/文件默认值 |
| [local_dataset_storage.py](../../backend/service/infrastructure/object_store/local_dataset_storage.py) `write_immutable_stream` | 分块写入、增量摘要、长度检查、原子发布和失败清理 | 复用该路径；`materialize_immutable_object` 中读取整份可变对象的路径不作为大点云导入方案 |
| [buddy_allocator.py](../../backend/service/infrastructure/local_buffers/buddy_allocator.py)、[mmap_buffer_arena.py](../../backend/service/infrastructure/local_buffers/mmap_buffer_arena.py) | byte extent 分配、descriptor、epoch/generation、锁和隔离回收 | 复用内存布局与回收协议；不能从底层能存 bytes 推导公开支持点云 |
| [local_buffer_arena_pool.py](../../backend/service/infrastructure/local_buffers/local_buffer_arena_pool.py) `publish_external_lease_and_transfer` / `conditional_release` | 发布与转移 owner、失效凭据拒绝、条件释放 | 提取/复用中立定位与所有权部分；类型元数据不能继续要求图片字段 |
| [local_shared_mailbox_supervisor.py](../../backend/service/application/workflows/trigger_sources/local_shared_mailbox_supervisor.py) | PREPARE、准入、外部写入、REQUEST、worker、RESPONSE/ACK、失败补偿 | 在同一状态机增加类型化输入适配，不复制一份点云 supervisor |
| [snapshot_execution.py](../../backend/service/application/workflows/snapshot_execution.py) | 验证输入、执行图、输出交接、清理 | 当前登记清理先于 `ResourceScope.close()`；引入映射数组前必须明确依赖顺序，见 10.7 |
| [execution_cleanup.py](../../backend/service/application/workflows/execution_cleanup.py) | 跨进程只保留可序列化执行元数据，剔除作用域等本地对象 | 只传小型定位/契约和内部凭据，不把大数组放进 pickle 或 worker 消息 |
| [resource_scope.py](../../backend/service/application/runtime/resource_scope.py) | 线程安全登记、逆序关闭、幂等、收集关闭错误 | 不包含数组引用计数；关闭前清空登记，不会在下次 `close()` 重试失败对象 |
| [resource_pool.py](../../backend/service/application/runtime/resource_pool.py) `BoundedResourcePool` | 数量限制、闲置淘汰和 lease 延迟关闭 | 没有字节预算，factory 在锁内，lease 有串行访问锁；不能直接当无等待的共享点云缓存 |
| [preview/lifetime.py](../../backend/service/application/workflows/preview/lifetime.py)、[graph_executor.py](../../backend/service/application/workflows/graph_executor.py) | Preview 图片句柄引用、图消费计数、分支和输出交接 | 普通 Runtime 不自动拥有该图片生命周期；复用图消费计算，扩展类型和两种执行入口，不复制图执行器 |
| [preview/buffers.py](../../backend/service/application/workflows/preview/buffers.py)、[preview/pool.py](../../backend/service/application/workflows/preview/pool.py) | Preview 独立短期 SharedMemory、reservation、退出后回收 | 复用有界显示交付；不能把图片的输入倍数估算或 WS 入口当点云峰值预算 |
| [output_delivery.py](../../backend/service/application/workflows/trigger_sources/output_delivery.py) | 清理前准备附件及所有权，当前附件类型限图片 | 扩展有界三维证据/文件结果，不把完整云默认塞入 value/JSON |
| [.NET writer](../../sdks/dotnet/src/Amvar.Vision/SharedMemory/ExternalLocalBufferWriter.cs)、[multipart 请求](../../sdks/dotnet/src/Amvar.Vision/Http/Requests/WorkflowRuntimeMultipartInvokeRequest.cs) | 外部映射 byte[]/Stream/直接填充及文件流上传 | 复用写入机制，新增类型描述与校验；不经过 Bitmap、像素转换或整文件 ReadAllBytes |

[mmap_primitives.py](../../backend/service/infrastructure/ipc/mmap_primitives.py) 已有 Windows byte-range lock 和 Linux 64-bit `F_OFD_SETLK`，不回退到 `lockf`。Windows/WSL 的既有验证记录见 [运行时修复结果](runtime-repair-results-20261015.md)，不能将历史图片/IPC 回归当成点云或 Ubuntu .NET SDK 验收。仓库当前 .NET 工程目标为 .NET Framework 4.7.2 x64；本设计不把它宣称为 Ubuntu SDK。WSL 的三维验证先覆盖 Python/backend 和协议夹具。

### 10.4 两种输入收敛到同一资源

以下为 M1 的设计约束，当前尚未实现：

```text
文件 → 既有 HTTP/文件资产入口 → 不可变 file-ref → 执行器显式解析
                                                        ↓
同机数组 → 类型描述 PREPARE → LocalBuffer 写入 → 原子交接 → point-cloud-ref
                                                        ↓
                     本次执行的只读 owner → ROI/索引/算法 → 数值与有界证据
                                                        ↓
                            配方显式 Save → 持久文件资产（可选）
```

- 文件节点接收 `file-ref.v1`，解析后输出 `point-cloud-ref.v1`；二进制入口直接提供相同的三维类型。文件不是 BufferRef，内存点云也不伪装成 image-ref。两种入口在图模板中明确绑定，不靠 MIME 猜测分支。
- 1 GB 在本设计中按十进制明确为 `1_000_000_000` 字节；GiB 专指 `2^30` 字节。文件限实际提交的整份文件，二进制限所有数组块与对齐填充的合计。描述消息有独立的小容量限制，不计作可绕过载荷上限的第二数据通道。协议/schema 中使用字节数，不使用模糊字符串。
- 文件接收阶段校验 App/binding、总量、文件数和磁盘预算；无 Content-Length、虚假长度、分块请求、重复 binding、取消和断连也必须受限。复用框架解析器与现有上传辅助层，不手写第二套 multipart 解析器。当前 `max_part_size` 控制字段上限不能当文件上限。
- 上传产生的 spool、暂存文件、不可变临时资产及解析后数组分开记账。当前一次性 `request.form()` 后检查不足以证明接收阶段有界，M1 必须补齐并验证；文件上限不能限制恶意 header 声称的点数或解析后的膨胀量。
- 文件只在执行器内解析。首批 PLY/PCD/XYZ 按 11.2 的格式、编码及字段能力逐项验证；不自动打开压缩包、外链或任意服务器路径。PCD 内部 binary_compressed 与任意归档解包不同，必须校验其声明解压量并计入预算。其他格式仅在对应契约与验证完成后扩展同一入口。
- Preview 的 [InputBegin](../../backend/contracts/workflows/preview_session.py) 当前为 64 MiB；不为 1 GB 原始云扩大该 WebSocket 通道。大型文件经 HTTP 受控资产进入 Preview，补项目/session/run 归属与清理；WS 继续承担控制与有界显示数据。
- 同机数组走现有 local-shared-memory Trigger 扩展。当前 `WorkflowTriggerPrepareV1.image` 为图片专用，须新增显式版本化的类型请求，不能通过可选 image 字段/metadata 兼容旧语义。图片与 event-only 请求保持原义；不新增图片协议的点云降级分支。
- ZeroMQ 当前是图片/小参数链路，本范围不增加点云帧，不调高其 MAXMSGSIZE/HWM。文件 HTTP 原有远程能力不变，同机数组不承诺跨主机共享 mmap。
- 数据面三维描述、新 payload、App contract、Trigger 能力、schema 生成物、SDK、前端和导入导出必须同批更新。若 arena descriptor/byte layout 未变，不虚构新的底层 ABI；上层新增格式与能力显式版本化，缺能力直接拒绝，不按图片尝试解析。

点云资源的物理位置与逻辑类型分离，不能为了统一类型强制所有输入再复制进 LocalBuffer：

| 来源/产物 | 物理数据与 owner | 图内/跨进程约束 |
| --- | --- | --- |
| 文件解析结果 | 执行 worker 的数组，或经格式验证后的只读文件映射；本次 scope 持有 | 节点同进程传逻辑引用，不传整数组；磁盘原文件与解析数组分别计费 |
| 同机二进制输入 | 现有 Broker 的 extent，runtime receipt + worker 的 guarded borrow | worker 控制消息只传定位/布局；worker 内节点共享同一 owner |
| ROI/局部视图 | 源 owner 加索引或范围描述 | 保留源依赖，派生索引单独计费；不是新 Broker 租约 |
| 新坐标/属性/原生库副本 | worker 的独立数组/库对象，绑定来源与参数版本 | 在现有 scope 下登记预算与关闭；不得静默缓存到下次运行 |
| 保存/显示输出 | 显式持久资产，或已有交付边界的有界证据资源 | 先完成交接再释放源，不能将执行期句柄写进持久结果 |

运行内私有数组不是跨进程 ABI，也不是新的 transport。一个 1 GB 文件解析后可大于 1 GB，此时按 worker 内存预算决定是否执行，不强行套用单个 LocalBuffer 分配上限。只读二进制文件映射也必须先验证布局适用，ASCII 仍需解析。当前图的普通节点计算沿用同一 worker 执行边界；如未来确需把派生完整数组移交另一进程，必须明确使用现有受控传输及容量交接，不能把本次进程内 handle 直接序列化，也不增加自动溢出/落盘降级。

### 10.5 完整二进制布局设计

控制描述与数据分离。每次一个完整载荷，使用一个 extent，extent 内按数组块存储；不按每点/每属性另分配租约。它是交付格式，不要求所有几何库使用同一内部数组结构。下表为拟定字段语义，尚未注册公共 schema。

| 字段组 | 设计与校验 |
| --- | --- |
| 格式身份 | 独立格式版本、point count、content length；点数为正整数，字节长度精确匹配，禁止 bool/浮点隐式转整数 |
| 坐标 | 必选 `positions`，连续 `N×3`，明确 little-endian float32 或 float64；保存源精度，不允许 object、指针或隐式 dtype |
| 属性 | 独立连续块，如 normals 为 `N×3` 浮点，colors 为 `N×3` uint8 RGB，intensity 为声明类型的 `N×1`；可选数值标量使用名称、类型、分量与单位，不自动解释为距离 |
| 块描述 | `name`、`semantic`、`dtype`、`components`、`count`、`offset_bytes`、`byte_length`；offset 相对载荷起点，按标量宽度对齐，块排序且不重叠；名称唯一，count 与 N 一致 |
| 有效性 | 可选 `N×1` uint8 validity，值限 0/1；坐标非有限值始终无效，不因 validity=1 变成实测；保留行号，不用零坐标替代缺测。派生插值/外推来源由派生契约另记 |
| 空间语义 | 源长度单位及来源、源 frame ID；无法确认单位时只允许原坐标查看，物理测量返回明确无效原因。坐标手性/轴定义必须显式，不按文件名推断 |
| 身份 | 服务生成 run/resource 身份，调用方 observation 标识只作为有界来源元数据；不允许调用方指定其他运行的 owner、文件路径或任意内存地址 |
| 定位与权限 | 从既有分配结果取得 arena/descriptor/epoch/generation/offset/length；由平台内部保存 ownership receipt，公开定位信息不等于释放或转移权限 |

约束如下：

1. v1 设计采用紧密连续的各属性块，不支持负 stride、任意行间隙、重叠字段或外部指针。调用方 AoS 结构体、非连续切片或其他字节序必须通过显式 SDK 适配，转换成本计入调用方；不能猜测编译器 padding。
2. 在分配前检查 `N × components × itemsize`、`offset + length`、累计字节和控制描述容量。Python 的大整数不免除跨语言有界整数检查；每一步不得超出载荷和协议字段范围。未知 dtype/格式版本拒绝；未知属性只有符合已定义数值标量语义时保留，否则拒绝，不静默丢字段。
3. 首块 offset 为 0，其后只有对齐所需填充，填充写零，最后一块末尾等于 content length。描述字段数量和名称长度必须受控制消息 schema 上限约束；不得通过描述区内联大数组。
4. 例如 N=2 的 float32 XYZ 占 `[0,24)`，float32 intensity 占 `[24,32)`，uint8 validity 占 `[32,34)`，总长 34 字节。该例只验证布局，不是算法测试真值。
5. PREPARE 固定描述和摘要，REQUEST 只提交对应分配身份；禁止写完后换 dtype、单位、点数或布局。描述摘要绑定 schema 内容，不等于数据内容摘要。内容摘要在接收/规范化扫描中计算并保留，不能每个节点重复扫描整份数据。
6. 写入 view 在 REQUEST 前必须关闭。发布后调用方不得持有可写别名继续修改；Worker 使用只读借用。该协议依赖受信任同机 SDK/进程遵守所有权，不提供针对同一操作系统用户恶意重映射写入的安全隔离承诺。
7. 整份输入为空属于输入错误；合法输入经 ROI 后为空属于测量缺测，可生成 INVALID，不能混同协议损坏或任务执行失败。

已有 .NET writer 的 byte[] 路径仍需要从调用方数组复制到 mmap；直接填充回调可让生产者直接写目标 Span，回调返回后不再持有 Span。两者均支持，不宣称所有输入零拷贝。NumPy/原生库要求连续 double 数据时，必要转换要显式登记，不能以接口名含 mmap 免计内存。

### 10.6 跨进程所有权与失败补偿

复用现有 PREPARE/REQUEST/RESPONSE/ACK、admission、owner token、epoch/generation 和条件释放。下表是三维适配必须维持的语义，不是新增状态机：

| 阶段 | 当前所有者与访问 | 成功后交接 | 失败/取消责任 |
| --- | --- | --- | --- |
| PREPARE 前 | 尚无载荷 | 校验描述、route/source 和执行提交容量，再分配 | 拒绝即结束，不排队、不提前泄漏 extent |
| 外部写入 | 调用方拥有 writer guard；服务保存写入 receipt | 精确长度写完、关闭 view/guard，然后 REQUEST | 断连或 deadline 后按当前 receipt 回收；活动 writer 不得被强制覆写 |
| REQUEST 准入 | 仍是写入阶段 owner | 既有 Runtime 按实际部署实例容量准入；Broker 原子发布 ACTIVE 并转移到 runtime owner | 准入失败释放写入 receipt；交接失败不得凭假定的新 owner 释放 |
| 提交执行器 | runtime receipt，数据已只读发布 | 只把定位、布局、身份和必要内部凭据交给 worker | 提交失败补偿 runtime receipt、admission 和 source permit；不能再用旧 writer receipt |
| 节点执行 | 运行 owner 保有借用；节点只读，分支持逻辑引用 | ROI/切片持源 owner；写结果产生独立资源 | 取消先停止产生新借用；不可中断原生调用交给现有 timeout/整组停止机制 |
| 输出准备 | 运行仍持有全部未交接数据 | 完成数值、有限证据及显式保存；需要 ACK 的附件转移到交付 owner | 保存失败按该输出的任务错误处理，不悄悄丢原始数据再宣称保存成功 |
| 运行清理 | 关闭全部数组借用与映射 | 依赖归零后条件释放；证据按交付/结果生命周期存活 | 无法关闭则保留失败资源归属，阻止相关 worker 复用，进入既有恢复边界 |
| ACK/超时/进程退出 | 交付 owner 或故障清理 owner | 确认不再被使用后释放，归还真实已释放预算 | 重复/晚 ACK、旧 generation/token 不能释放新租约；崩溃后先确认进程组结束再收敛 |

同一 TriggerSource 的既有 in-flight permit、执行器容量和资源预算是独立限制，不等于模型实例数。纯测量 Workflow 不增加模型容量限制，但仍不能绕过机器资源和现有 source/executor 容量。`BoundedWorkflowTriggerExecutor` 的提交前准入继续保留，不新增等待队列。

同一运行多个节点/分支共享数据时，不反复转移 Broker owner，不把单一释放凭据复制成多个独立所有者。由运行内对象管理借用与派生依赖；跨进程采用既有 IPC 交接和受保护读取。当前 `reader_guard_slots=64` 是读取保护槽数，不是 64 并发业务承诺；应共享 owner 的一次借用，不为每个视图消耗一个 slot。

### 10.7 数组、映射和图的释放顺序

[direct_mmap_reader.py](../../backend/service/application/local_buffers/direct_mmap_reader.py) 的 `acquire_buffer_ref_view` 提供受 guard 保护的借用；`read_buffer_ref` 会复制成 bytes。`read_owned_buffer_ref_view`/arena `read_owned_view` 的无持续 reader guard 路径只适用于其受控 owner 使用方式，不能直接用于任意点云 NumPy 别名。

点云 owner 必须把 guarded borrow 保留到最后一个数组、原生适配器和派生视图释放；禁止在短 `with` 中构造 ndarray，退出 guard 后把 ndarray 留给后续节点。ROI 索引也占内存，索引视图必须持有源；变换输出与源、缓存索引与建索引源都需要明确依赖。节点参数/运行结果不可持久保存进程内句柄。

正常清理的依赖顺序：

1. 停止新借用，完成或取消仍在执行的节点，冻结需保留的输出集合。
2. 显式保存的数据发布为独立持久引用；有限显示证据转给既有 Preview/结果交付 owner。未转移的运行句柄不得出现在响应或数据库。
3. 释放原生适配器、派生数组/索引、节点及分支持有的别名，再释放底层 readonly view 和 reader guard。
4. 关闭映射/文件句柄，最后释放租约或删除本次运行拥有的临时资产，归还对应预算。已有持久资产只解除借用，不删除；调用方原始路径从不由运行清理。

实现时须在现有执行清理边界表达依赖顺序，不能简单把全局 `finally` 两行交换后认为所有资源都安全。现有 `snapshot_execution.py` 先执行登记的文件/lease 清理，再关闭 scope；若照搬接入点云文件映射，可能先删文件或先请求回收底层块。新分配也必须纳入异常保护区，不能在 `try` 外建大资源后依赖不会执行的 `finally`。

`ResourceScope.close()` 当前先标 closed 并清空登记，再执行 closer，因此“再次调用 scope.close”不会重试失败映射。设计要求在现有 scope/worker 生命周期内保留失败 owner 和清理证据，关闭失败不能提前归还字节预算或宣布 worker 可恢复；复用现有进程组终止/确认与 Broker quarantine 规则，不新建故障回收服务，也不以 GC 或 `unlink` 成功代替不再使用的证明。

图内释放复用 `PreviewLifetimes`/`PreviewOutputScope` 的消费者计算，支持三维类型并覆盖 Preview 和普通 Runtime。ForEach、Parallel、别名、子图输出和隐式选择必须计入；对于无法证明消费完毕的受信任自定义节点，保守持有到本次 scope 结束并计入峰值，不允许隐藏跨运行保存。不得复制一套图执行器，也不把图片 registry 改成无限制任意对象仓库。

### 10.8 容量、内存与磁盘预算

最低机器 RAM、期望并发数和时限仍为未确定，以下是预算定义，不是默认配置或验收通过结论。

| 预算项 | 计算/核对方式 | 配置与负责边界 |
| --- | --- | --- |
| 提交载荷 B | 文件实收字节，或二进制所有块/填充总和；B ≤ 1 GB | 点云输入契约、binding、SDK 与前端一致 |
| LocalBuffer 容量 C | 当前 buddy 以 1 MiB 为最小块，按可容纳 B 的二次幂分配；按 extent 容量而非有效长度预留 | 既有 Broker 部署配置和分配器，不为每节点独建 arena |
| 解析/转换 | 解析器工作区 + 源坐标 + 必要 dtype/单位/布局转换 + 属性 | 解析/算法适配器成本声明，由执行准入和节点分配点核对 |
| 派生与工作区 | ROI 索引、mask、空间索引、法向、拟合/配准临时内存、原生库内部副本 | 按方法与 N 计算上界，选库后测证；无证据不标支持 1 GB 该算法 |
| 共享与缓存 | 相同物理数组按 owner 只计一次，多个逻辑引用不重复计费；独立副本必须计费 | 运行内 owner；默认不保留跨运行完整输入，跨运行缓存另需显式字节/失效策略 |
| 显示/结果 | LOD、标注、证据数组、HTTP/SDK 交付缓冲和浏览器/WebGL | 既有 Preview/输出交付与前端配置；独立预算，不能借用原始云无限保活 |
| 临时磁盘 | multipart spool + 不可变暂存 + 解析派生文件；阶段重叠取实际同时存在量 | 既有上传/ObjectStore 与运行 owner；显式保存另计持久配额 |
| 原生线程/时间 | 实际运行数 × 算法线程配置，节点安全点/不可中断函数最大区间 | 既有 worker 配置、节点 timeout 和 Runtime deadline；不照搬 SDK 的图片默认超时 |

预算按生命周期峰值而非把所有节点的终态数组简单相加：

```text
单次计算内存峰值 = max_t(本次唯一存活数据块 + 索引 + 工作区 + 交付缓冲)
主机需求 = 平台基线 + 所有活动调用私有峰值 + 共享常驻页 + 有界缓存 + 安全余量
磁盘需求 = max_t(spool + 暂存原文件 + 派生文件) + 显式持久资产
```

共享 mmap 的容量不等于 RSS；跨进程 RSS 求和可能重复计入共享页。验收需同时看各进程私有内存、共享驻留、主机可用内存、文件缓存、arena 使用和磁盘，不能只看 Python 对象字节数或 `tracemalloc`。调用方已有 byte[] 也计入同机容量评估，不能因在 SDK 外就忽略。

仅作算术示例：约 1 GB 的纯 XYZ float32 最多容纳 83,333,333 点；一份同点数 float64 XYZ 另需约 2 GB，一份 uint32 全索引约 333 MB，一字节 mask 约 83 MB。这还不包含解析、邻域索引或算法临时区，且 float64 转换不能恢复源 float32 已丢失的精度。ASCII 文件的点数与文件长度无固定比例，不能套用此例。

当前默认 2 GiB arena 中，一份接近 1 GB 的输入占 1 GiB extent；两份会占满 arena，尚未考虑已有图片、输出或碎片。这不是“两并发”设计，也不代表总空闲 1 GiB 就一定有可分配的连续 buddy 块。不能为通过演示而静默扩大 arena、增加第二 Broker、溢出到备用数据面或降低测量分辨率；资源不足即时拒绝并说明所需/可用容量。发行/现场可在容量验收后显式配置既有 Broker，不把当前默认 2 GiB 写成所有部署的产品容量承诺。

准入分两层：PREPARE/上传预留输入与接收资源；REQUEST/运行开始前由既有 Runtime 准入统一核对执行工作区及模型容量。多 worker 不能各自读取一次系统空闲 RAM 就都认领同一预算。资源配额由服务配置管理，算法提供成本声明，worker 按授权额度使用；节点分配前还要检查实际需求。未知或不可界定峰值的方法不得宣称全容量可执行，不能用业务等待队列隐藏不足。

现有 `ResourceScope` 不是预算器，`BoundedResourcePool` 不是字节缓存。优先复用运行内不可变 owner；如确需跨运行复用标准资产索引，再在既有资源池边界补字节成本、只读并发和失效政策，不复制 CloudCache/MemoryManager。大解析不放在 `get_or_create` 的全局锁内；移除锁之前也必须证明底层资源支持并发读取。所有预算只在真实释放或已确认进程退出后归还。

### 10.9 保存、结果和前端生命周期

用户已确认默认不自动保留完整点云。此处不把“使用受控临时文件”误写成“每次持久保存”：

| 数据 | 运行中 | 调用结束后 |
| --- | --- | --- |
| 本次上传的原文件/解析临时文件 | 本次调用拥有，受控引用 | 关闭借用/映射后清理；显式保存成功则保留对应独立资产 |
| 原本已登记的文件资产/配方参考 | 只借用其不可变版本 | 按原资产生命周期保留，不因一次调用结束删除 |
| 同机输入数组和未保存派生云 | 本次租约/owner 管理 | 无借用后释放；默认不生成长期原始云文件 |
| 数值、规则、质量和方法信息 | 同 observation/run/config 关联 | 经既有结果能力保留，字段/记录量受限；不包含瞬时指针或租约凭据 |
| 显示证据、特征及尺寸标注 | 生成有限采样/支持域/端点证据 | 独立有界资产或结果附件；预算与保留期按结果策略，不能保活完整原云 |
| 显式 Save 输出 | 在原资源仍有效时写入、摘要校验、原子发布 | 持久 file-ref/资源版本，纳入既有项目访问、删除依赖和导入导出 |

保存配置必须明确选择“原始输入”或“某节点处理后的点云”，不能用一个模糊开关悄悄改变内容。已确认采用平台无损资产，并另提供 PLY/PCD/XYZ 显式交换导出；文件原始保存保留原字节，内存输入及派生云保留布局、精度、单位、坐标和全部受支持属性，见 10.11。失败不返回伪造成功引用，部分产物按现有原子发布规则清理。

浏览器不下载/解析 1 GB 完整点云。显示 LOD 的精度和采样标识必须可辨，正式测量只用完整或显式配置的数据。运行结束且原始云未保存时，允许查看数值/有界证据，不能承诺任意原精度拾取、重新拟合或全云复算；界面明确源数据未保留，需要重新输入或打开显式保存资产。不能把这个状态当作本次测量 INVALID。

Preview 在交互期间可按 session 预算持有源；其关闭、取消、过期和进程退出必须清理。任务/项目/文件/节点切换时，旧加载、旧拾取和旧证据回调不能覆盖新对象；卸载后不得重新建立连接。复用现有请求代次与订阅模式，并释放 geometry/material/texture/worker/URL/监听。证据超预算应显式报告交付状态，不能悄悄替换测量数据或把未交付内容标为完整结果。

### 10.10 验证设计与本轮结论

以下现有测试只读核对，未执行：[mmap arena](../../tests/test_local_buffer_mmap_arena.py)、[external lease](../../tests/test_local_buffer_external_leases.py)、[publication recovery](../../tests/test_local_buffer_publication_recovery.py)、[mailbox supervisor](../../tests/test_workflow_trigger_mailbox_supervisor.py)、[ResourceScope](../../tests/test_workflow_resource_scope.py)、[Preview lifetime](../../tests/test_workflow_preview_lifetime.py)。它们提供故障注入和断言位置，不代表点云已经通过。

| 后续验证组 | 必须覆盖 | 通过证据 |
| --- | --- | --- |
| 布局/解码 | 文件与二进制同一物理数据；float32/64；字段乱序、单位、未知类型、截断、重叠、stride、整数溢出、NaN/Inf、空输入 | 独立夹具、逐字段期望值及一致的有效性；不以被测解析器生成真值 |
| 容量/接收 | 1 GB 边界与超限；虚假长度、chunked、header 点数膨胀；磁盘/arena 不足、碎片和图片同时占用 | 尽早拒绝、无隐式队列、无临时残留；先测小型边界逻辑，最终另做真实 1 GB 输入 |
| 所有权/停止 | writer 崩溃、REQUEST 准入失败、交接/提交失败、活动 reader 超时、scope 关闭失败、Broker/worker 重启、旧 token/ACK | 不读已回收内存，不释放新 generation；借用未关闭不能恢复；整组结束后预算收敛 |
| 图与别名 | 多节点共享、ROI 索引、Parallel/ForEach、子图输出、原生库借用、预览与 Runtime | 最后消费者后释放；取消仍遵守依赖顺序，不为分支复制全量输入 |
| 保存/交付 | 默认不保留、显式原始/派生保存、保存失败、晚响应、附件 ACK 丢失、既有资产借用 | 数值/证据可读，瞬时引用不出运行边界；没有误删调用方或既有资产 |
| 前端 | 大文件上传/取消、单位变更、旧请求晚返回、卸载、LOD 与原精度区分、源未保留 | 页面行为与真实资源一致，不自动重连，不用显示样本计算正式量值 |
| 资源/平台 | Windows x64 和 WSL Ubuntu x64；解析/原生复制/索引实际峰值，句柄/线程/文件/浏览器资源 | 逐配置报告；源代码读过不等于容量、SDK 或工业精度认证 |

M0 确定了复用和扩展位置、两条数据链路、二进制布局、所有权/释放、预算公式、保存与验证设计；逐字段和节点规格见第 5、7 节，后续条件见 15.5。M1 已按后续授权验证 I/O；索引成本、正式 schema 和节点链路仍未验证。未确定的设备内存、并发和时限阻止默认容量承诺及相应性能验收，不推翻已收口的设计。

### 10.11 无损保存与 PLY 交换导出

已确认平台无损保存，不以 PLY/PCD/XYZ 等交换格式替代内部完整持久格式。存储复用现有 ObjectStore、项目授权、资源不可变版本与原子提交，不新建 CloudAssetManager/资产数据库/保存服务。无损指已接收数据的 dtype、字节、字段和语义可还原，不代表传感器没有误差，也不代表 ASCII 转换后的数值能还原原文本。

| 保存对象 | 必须保留 | 不得替代 |
| --- | --- | --- |
| 文件原始输入 | 原文件精确字节/长度/SHA-256、原文件名展示信息、格式、单位与坐标确认、来源 | 不能拿重新写出的交换文件冒充原文件；原始保存不强制再保存一份全量解析副本 |
| 同机内存原始输入 | 校验后的字段描述、输入 data.bin 原字节及摘要、单位/坐标与有效性定义 | SDK 已做的 AoS/端序转换须留来源；不能声称保存了转换前未知内存布局 |
| 派生点云 | 独立物化的所有坐标/属性、dtype、validity/sample_origin、单位/坐标、父内容摘要与方法/参数，必要的源索引 | 不保存跨运行 ndarray/view/lease；不能只存 ROI 索引而默认源永久存在 |
| 数值/有界证据 | 结果与方法/参数、有限显示点/特征/端点、源是否保存及持久引用 | 不包含全量源，不保活 runtime owner，不伪称可原精度重算 |

持久内容格式拟定 `amvision.point-cloud-asset.v1`，是既有计量资源服务的新内容类型，不是独立资源系统。平台内部使用 manifest 和二进制对象，不做 pickle、object dtype 或每点 JSON。资源外层需显式升级 `amvision.measurement-resource.v1`：原二维内容的定义不改，新增 point-cloud 分支，通用 ResourceReference 的 kind/schema/消费者同批更新；不在 `image_object_key` 塞入点云。旧资源的读取历史和审核重发按 8.6，正式版本转换另交迁移方案，不留新旧运行分支。

| 资产 manifest 字段 | 规格 |
| --- | --- |
| `format_id`、`kind`、`representation` | 固定格式与 point-cloud；representation=file-original 或 array-blocks，互斥字段 |
| `source` | file/local-array/derived；原始文件格式及源摘要，或父资源/内容摘要列表；不含操作系统路径和内存 token |
| `spatial`、`provenance` | 第 5 节定义；保留单位确认来源、坐标、方法版本和参数正文/可解析的冻结引用 |
| `point_count`、`fields` | array-blocks 必填，使用 5.5 的块格式；file-original 只记录已核对的格式元信息，不能仅凭文件声明保证解析成功 |
| `blobs` | 受控名称、角色、byte_length、sha256；仅允许当前格式定义的 original/data/indices，禁任意 URI/绝对路径/外链；array-blocks 的 data_length 与字段末尾一致 |
| `source_field_names` | 规范字段名到原始字段名的可逆映射；原始名受 manifest 字节限额约束，不作文件路径 |
| `parent_assets` | 已保存父资产的完整 ResourceReference；未保存来源只留内容摘要和 source_retained=false，不伪造可访问引用 |

资产身份沿用 project_id/resource_id/version/sha256，名称、创建者/时间属于服务文档，不进入可迁移内容摘要。内容摘要计算采用现有 canonical JSON 规则，包含 blob 摘要、长度及布局；blob 实际内容逐块验证。平台生成对象键，数据写完并验证后最后提交 version.json；中断只能留下可识别的未提交暂存，不能出现成功引用或可读半成品。所有大文件按有界块写/算 hash；输入的来源 hash 在本次运行只生成一次，不在每个节点重算。

对派生空点云可保存合法空数组描述，但作为新的 Workflow 输入仍按入口空载荷规则拒绝；其存在用于追溯缺测，不把空数据当有效可测工件。保存不自动保留全部父链；需要完整复算时配方显式保存原始及必要依赖。不同方法版本的相同显示不能覆盖同一版本。

交换导出是独立动作：PLY 路径规划 binary_little_endian PLY 1.0，坐标 float32/64 按源精度；PCD 显式选择已验证编码与字段；XYZ 显式选择列定义与文本精度。字段、来源、单位或空间信息不能表示时不能静默丢弃，允许显式选择交换字段并列出遗漏，否则拒绝不完整导出。平台完整归档仍用无损资产。交换文件不保证第三方理解单位/坐标说明，重新输入仍须明确确认；原始文件下载与重新导出不同。各格式读写及精度限制按 11.2 验收，不以库默认参数定义项目语义。

### 10.12 既有资源服务的扩展和容量边界

已核对 [MeasurementResourceService](../../backend/service/application/workflows/documents/measurement_resources.py) 和 [API](../../backend/service/api/rest/v1/routes/workflows/measurement_resources.py)：现有内容只有二维标定/模板，resource document 最大 4 MiB、图片 64 MiB、导入包 68 MiB；导出用 BytesIO，导入持有整包 bytes。不可仅扩大这些常量处理 1 GB 点云，必须在原服务/API 扩展流式文件与 blob 路径。配置引用收集目前只认识 calibration_resource/template_resource；需要同步三维 asset 引用及发布/删除检查。

复用既有版本、tombstone、路径写协调和项目生命周期。`PreparedMeasurementResources` 已有按字节限制的二维准备缓存，不能声称仓库没有字节缓存再新建一套；三维只读借用/源依赖/索引预算在既有资源边界扩展，耗时解析和索引不得在全局缓存锁内执行。运行临时云不自动塞入跨调用缓存。

导出包继续采用可检查的 ZIP_STORED 容器，服务端以有界流/受控临时文件交付，不拼接整包 bytes；导入按允许成员、重复路径、路径穿越、实际字节、总解码量、hash 和磁盘预算验证，拒绝压缩炸弹/未知成员/外链。manifest 保持小容量，不能把点数组放进去；大于现有 4 MiB 元信息需求先评审，不自动提高。

两个容量不能混淆：Workflow 输入的数据文件或二进制载荷上限已定为 1,000,000,000 字节；后台无损资源包还含 manifest/ZIP 开销及可选追溯 blob。已确认资产包采用独立、显式配置的大小限额，数值待定，不改变 Workflow 输入上限。未配置时不默许无限上传，也不假定 1 GB 数组能装入 1 GB ZIP；本地已存在资产的借用仍校验实际数据、解析峰值与运行预算，不借引用绕过验收范围。

失败路径验证覆盖写入前拒绝、写入中取消/磁盘满、hash 错误、最后提交失败、重复导入、跨项目身份重映射、资源仍被草稿/发布使用时删除、源已释放后保存、不同 generation 清理。完整文件读回校验不等于允许在请求线程解析/拟合。

### 10.13 M1 两入口、持久引用及全部读取方

#### 10.13.1 文件与同机数组入口

| 边界 | 完整输入/处理规则 | 扩展现有位置与失败清理 |
| --- | --- | --- |
| 文件公开 binding | 沿 `file-ref.v1`，必填 transport_kind=storage、storage_ref=object-store、object_key、file_name、media_type、content_length、checksum_algorithm=sha256、checksum、immutable_version；metadata 可选但不是三维字段的可信来源 | 真实字段来自 [core_catalog.py](../../backend/nodes/core_catalog.py)。不另建 point-cloud-file DTO；长度需大于 0 且不超过 1,000,000,000，引用仍核对项目/快照/hash |
| HTTP/SDK 文件上传 | 既有 multipart → 不可变 ObjectStore 快照 → 相同 binding；分块接收、累计限额、临时盘预算、实际长度/hash；不可依赖 Content-Length 自报值 | [uploads.py](../../backend/service/api/rest/v1/routes/workflow_runtime_support/uploads.py) 扩展接收中保护；失败清理本次暂存，不删除调用方源文件。上传暂存与配方 save-cloud 持久资产严格分开 |
| Preview 大文件 | 同一个文件输入/快照语义，不把 1 GB 放入 JSON/Base64，也不按 SharedMemory → bytes → 暂存文件整块复制 | 已核对 [preview/worker.py](../../backend/service/application/workflows/preview/worker.py) 当前确有整块 `bytes(memory.buf[:byte_length])` 路径；M1 在原 Preview 输入管理中增加有界文件交接，不只是提高限额，不新增 Preview Runtime |
| 同机二进制数组 | 5.5 的 descriptor 与 10.5 的连续分块布局；SDK 拿到 PREPARE 的受控可写租约后完整写入，REQUEST 只引用已冻结分配身份，不携带可变二次布局 | 扩展既有 LocalBuffer/共享邮箱状态机和 .NET writer，不改成图片，不经过磁盘 PLY；数据块总长度含对齐填充不超过 1,000,000,000，控制信封另受既有 64 KiB 限制 |
| REQUEST 准入与身份 | 校验 binding、发布输入类型、连接/调用身份、分配 generation/epoch、descriptor 和载荷摘要、writer 完成状态；原子交接成功后调用方不可再修改。返回云由 worker 生成本次身份 | 准入拒绝/断连/取消按原 lease 状态归还；owner 探测失败不猜成无人持有。具体顺序沿 10.6，不能让旧 ACK/迟到请求释放新代资源 |
| App Entry/前端 | file binding → read-cloud；新类型化数组 binding → point-cloud-ref。浏览器不是 mmap 客户端，不能为 SDK-only binding 显示 JSON 编辑框或伪造 BufferRef | App Contract 必须准确公开 transports；App Mode 对仅同机数组输入显示“由同机调用方提供”及不支持手动提交原因，不隐式改投文件。需要两种人工/SDK 调用配方时以明确 binding/模板表达，不按输入名猜类型 |
| 准入与回收 | 所有点云入口先进行服务与执行资源准入，纯云图不增加模型实例数限制；调用模型才沿实际 Deployment 容量。预算不足立即拒绝，不排队 | 文件、映射、数组别名、索引、显示副本分别登记 owner。取消/异常关闭别名和 guard 后才释放底层；清理失败隔离现有 worker，恢复须通过原准入 |

文件调用和数组调用不是两套业务 API，也不要求一个 binding 同时接受两个不相容 payload；Catalog 类型、App Contract、公开 binding、SDK、Preview/Runtime 输入校验必须同批扩展。已发布图用哪种输入由其冻结契约决定，不能在运行时偷偷转换。数据在到达 worker 后均成为同一种不可变云，后续五节点不关心传输方式。

#### 10.13.2 持久引用与资产内容

`measurement-resource-ref.v1` 是 M1 新注册的公开 payload 名，不另建 Reference 类或在引用中塞 manifest。其 JSON 正文直接复用现有 ResourceReference 的五字段：project_id/resource_id 为 Identifier，version 为 1..2147483647 整数，sha256 为小写 64 位十六进制，kind 为 point-cloud。无格式字段、文件路径、最新版本别名或运行句柄。现有 ResourceReference.kind 只有二维两类，M1 需在原类型与实际消费者中显式增加新 kind，不能宣称已经支持。

现有 `MeasurementResourceContent` 升为显式 `amvision.measurement-resource.v1` 时，kind 对应一个且仅一个内容分支：planar-calibration → calibration，localization-template → template，point-cloud → point_cloud；无关分支禁止携带值。document 的 reference/name/content/created_at/created_by 与既有服务保持职责一致，二维 image_object_key 不能充当云数据块。仅在需要输出 v2 内容的路径进行升级，历史文件与引用不原地改写；受影响发布按 8.6 审核重发，不为新 kind 强制全量迁移。

point_cloud 内容复用 10.11 的 `amvision.point-cloud-asset.v1`；将原先“按分支”约定补齐如下。所有分支拒绝未知字段，数组长度/偏移算术不得溢出；未定容量参数不能解释为无限。

| 字段/分支 | 必填与互斥规则 |
| --- | --- |
| 公共 | format_id、kind=point-cloud、representation、source、spatial、provenance、blobs、source_field_names、parent_assets；source/provenance 采用下述持久分支，不能保留可执行 runtime ref |
| `representation=file-original` | 必须一个 role=original 的 blob、original_format=ply/pcd/xyz、original_file_name 非空文件名、profile_id/profile_version；保存原字节。原文件 point_count/fields 仅在已完整核验时同时写入，不将推测 header 当校验成功；保存节点原件来自已成功 read-cloud 的来源 |
| `representation=array-blocks` | 必填 point_count、fields（5.5 物理布局）、content_length、source_metadata；必须一个 role=data 的 data.bin；可选 role=indices 的 source-indices.bin，不能包含 role=original。derived 子集物化独立块，不依赖父映射 |
| `blobs[]` | role、name、content_length、sha256；name 只允许上述受控成员名，name/role 唯一，content_length 为非负整数且与实际流一致；无 URL、链接或任意嵌套路径。original 成员名固定 original.bin，真实格式来自 original_format 而非临时扩展名 |
| `source_field_names[]` | `{name:规范字段名,source_names:原属性名或列标签数组}`；规范名唯一，分量映射可逆，不在此藏未保存的属性。平台源无外部字段名时保留空数组 |
| `source_metadata` | array-blocks 必填，file-original 可选的已核验信息；null 或严格 PCD 分支 `{format:pcd,width,height,viewpoint,organized,source_spatial}`。width/height 为正整数且乘积等于点数，organized 为 bool 且等于 height>1，viewpoint 为有限 tx/ty/tz/qw/qx/qy/qz 七值，source_spatial 为该源姿态所属的原始 5.6 空间声明；单位归一/变换后不能贴用当前空间解释原 VIEWPOINT。保留源值，不据此自动变换。过滤破坏组织或零点时该分支为 null，并在 provenance 记录，不伪造 height=1 代表保留 |
| `parent_assets` | 完整 ResourceReference 数组，去重且禁止自指/循环；派生资产 source_retained=true 必须有真实可访问的全部原始来源资产，原件本身则由当前已提交 blob 证明。未存父仅记录内容/方法摘要与 source_retained=false，不能制造不存在的引用 |
| `indices` 元信息 | 有 indices blob 时附 dtype=uint32/uint64、count、source_point_count 和 source 身份；count 等于当前点数，每值小于 source_point_count。当前数据独立存在，即使父未保存也可读取；索引不授予父数据访问权 |

PCD metadata 是需要补齐的内容，不把三维有效性 mask 当作 organized cloud 的行列结构。输入 descriptor 可选携带相同 source_metadata 时必须走新点云业务 schema 和摘要，不能塞进既有图片字段；没有该字段按无组织信息处理，不推断传感器姿态。11.2.8 已规定由 pypcd4 修复路径完整获取/写回，M1 仍须验证；元数据契约不能替代解析能力证明。

持久 source 严格分支：file 含 kind、file_name、content_length、content_sha256、profile_id/profile_version、source_observation_id；local-array 含 kind、content_sha256、descriptor_sha256、source_observation_id；derived 只含 kind，父来源由 provenance/parent_assets 表达。source_observation_id 必填但可 null；其他摘要/长度/ID 采用既有严格约束。provenance 含 `method:5.11 方法对象或 null`、`parents:数组`、`source_retained:bool`；原始输入 method=null、parents 为空，派生 method 非空、parents 非空。每个 parent 为 `{content_sha256,reference:ResourceReference或null}`，reference 非空时摘要必须对应其资源内容，未保存时摘要来自冻结的源内容描述；不得把不同 hash 算法混作同一身份。本轮不新增来源查询服务，未保留的父仅供审计，不能解析为活资源。

归档数据块 hash 基于实际字节，资源 sha256 使用既有资源版本摘要规则并覆盖规范内容中的 blob 描述；资源版本和单个文件的 checksum 不混用。平台保存的原始浮点 NaN 位模式及属性字节不得因 JSON 转换改变；规范 metadata 的 JSON 禁止 NaN。固定成员名与读取器所需扩展名分开：必要临时路径由受控 worker 根据已验证格式形成，不能相信调用方文件名选择解码器。

#### 10.13.3 逐字段生产与消费核对

| 契约 | 生产方 → 全部 M1 读取方 | 必须同批覆盖的校验/异常 |
| --- | --- | --- |
| file-ref.v1 | 上传/导出服务 → input validator、read-cloud、原件保存、SDK/下载 | 既有九个必填字段、项目与真实 checksum；Preview 不能偷换成可变路径 |
| point-cloud-buffer.v1 | SDK → 同机 mailbox/Broker 入站适配 → worker | 字段布局/大小、source_metadata、generation 与所有权；拒绝和晚返回释放 |
| point-cloud-ref.v1 | read-cloud/数组入站/预处理 → 六节点、Scope、图消费计数 | ready/unavailable、空云、run/observation/frame/unit、只读借用；不公开跨请求调用 |
| measurement-resource-ref.v1 / ResourceReference | 资源服务 → 参数编辑/执行准备、read/save/export、发布依赖收集、资源导入导出与删除检查、结果链接 | 五字段身份、kind、版本/hash、受控项目与不可变依赖；所有读方纳入原服务升级，不只修改 Pydantic literal |
| point-cloud-asset.v1 / resource.v2 | save/资源导入 → 流式导出、版本服务、执行准备、发布验证 | 原件/数组互斥、source_metadata、全部 blob 与摘要、原子提交、未知成员拒绝及受影响旧资源升级 |
| point-cloud-preview.v1 | preview 节点/现有捕获 → 显示适配、共享 Three.js viewer、App Mode、显式结果证据保存 | 新类型识别、精确字段/大小、晚返回、所有资源释放；显示失败不篡改业务结果 |
| filter/export summary | 对应节点 → 现有 Value/Table Preview、显式 App 输出、结果记录 | 数字/null 与状态一致、完整字段集合、不能把执行状态当产品状态 |

M1 审计对照本表逐个核查 schema、公开能力、SDK、前端、引用收集和清理；不把“后端节点能运行”当作整个入口/显示/保存已完成。新增公开 payload 与 source_metadata 均为待实施契约，本轮没有修改当前任何 v1 API。

## 11. 依赖与发行准备

下表保留 M0 的候选和排除清单，不是完整三维安装 lock。M0 当时仅核对仓库约束、公开元数据与源码；后续 I/O 安装、native import 和测试见 M1 实施记录，几何栈完整 ABI 尚未验收。不得静默降级 NumPy、PyTorch 或推理依赖。

| 依赖 | 使用范围 | 准备要求 |
| --- | --- | --- |
| NumPy/SciPy/OpenCV | 现有数组、空间查询、优化、栅格和二维图像算法 | 复用仓库约束；确认原生线程与数值行为 |
| Open3D | 点云预处理、几何与配准基础库，不承担本方案的严格 PLY/PCD/XYZ 入口 | 核定 0.20.0 上游 wheel；M1 求解与双平台验收后锁定，不修改其 C/C++ 实现 |
| trimesh | 受控修复版本承担 PLY；网格/场景、拓扑、截面仍沿原有职责 | 基于 5.1.1，仅修改 Python PLY I/O 与对应测试/API；不改几何算法，不安装全部 extras，不设失败换库路径 |
| pypcd4 | 受控修复版本承担 PCD ASCII/binary/binary_compressed 读写 | 基于 1.5.1，保留公开元数据与结构化数组；修复规格见 11.2.8，不直接启用原版 |
| python-neo-lzf | pypcd4 的 LZF 压缩/解压依赖 | 0.3.5 上游有 CPython 3.12 Windows/Ubuntu x64 wheel；不修改原生代码，不自行实现压缩器，发行前验包/许可/ABI |
| plyfile（排除） | 仅可作为公开格式行为参考 | 用户确认排除生产候选；GPL-3.0-or-later 未经本项目发行许可评审，不等于 GPL 禁止商用 |
| tifffile | 深度/高度 TIFF 与元数据 | 按实际输入格式验证 dtype、字节序和多页处理 |
| imagecodecs | 所声明 TIFF 压缩格式 | 按需引入，不安装全部可选功能当默认前提 |
| three / @types/three | Vue 三维查看器 | 本地构建、版本配套、无 CDN；ECharts 复用既有依赖 |
| cadquery-ocp / OCCT | STEP/BRep CAD 导入与几何计算 | CAD 可选能力；检查 Windows/Linux wheel、传递依赖、几何精度和许可证，不默认安装整个 CAD 编辑器 |
| 厂商 3D SDK | 对应 Camera provider | 根据具体型号确认平台支持、DLL/so、驱动、许可和部署要求；不把二维 SDK 假定为该 3D 相机 SDK |
| Matplotlib | 离线算法验证或明确的静态报告适配 | 不作为交互查看器或每请求启动的绘图进程；字体不能硬编码 Windows 路径 |

依赖栈确定为 trimesh + Open3D，二者按职责协作，不重复实现同一几何算法或按异常轮流尝试解析。trimesh 基础安装仅硬依赖 NumPy；Open3D 自带原生实现由上游 wheel 提供，不等于本项目新增 C/C++ 源码、编译链或手工 ctypes 绑定。取消此前 RPly 独立原生适配设计，meshio 不纳入依赖。现阶段不引入 Open3D-ML、训练框架或 GPU 运行时作为普通测量前提。版本更新频率仅是维护风险信息，不能替代字段、精度和生命周期验收。

准备顺序：在 conda amvision 环境盘点 → 解析候选依赖但不改环境 → 核对 Python/ABI/NumPy 和原生库 → Windows/WSL 安装与算法隔离验证 → 锁定版本和哈希 → 验证 bundled Python → 按 release profile 组装。发布代码从源目录生成，不直接修改 release 产物。

CPU 基础链路须无 CUDA 也可执行。厂商驱动和不可随包分发的依赖单独列明；Python、前端资源和运行库按既有离线发行规则交付，不依赖现场系统 Python/Node。

### 11.1 固定版本、许可证与发行事实

2026-10-21 本次核对固定到以下发行 tag 及提交，不再用 main/“latest”作为代码证据；它们是 M1 待验证候选，不是已经安装、可直接上线的依赖锁。

| 候选 | 源码身份 | 已核实的发行边界 |
| --- | --- | --- |
| Open3D 0.20.0 | v0.20.0，b6c5e196384ad71e75b6e6f9c5da22d046221f1d | MIT；CPython 3.12 Windows amd64 与 Linux manylinux_2_35_x86_64 wheel 存在；Linux wheel 要求 glibc 2.35+，不能沿用先前 0.19 的 2.31 要求 |
| trimesh 5.1.1 | 5.1.1，dc8490c825c382d2d58b5bd87ecacc74790ead27 | MIT；py3-none-any wheel，硬依赖 NumPy；可选网格算法依赖按实际功能逐项申报，不整体引入 easy/all extras |
| 仓库已有依赖 | requirements.txt / requirements_cpu.txt | NumPy >=2.2,<3、SciPy >=1.17,<2、OpenCV >=4.11,<5，Torch 2.12.1；范围清单不是求解 lock，不证明新增原生库兼容 |
| three | 先前 registry 查阅为 0.186.1，MIT，当前未引入 | M1 显示实施时核定 three/@types/three 与 TypeScript/Vite 的固定版本；本次未锁前端依赖 |

发行身份来源：[Open3D tag](https://github.com/isl-org/Open3D/tree/b6c5e196384ad71e75b6e6f9c5da22d046221f1d)、[trimesh tag](https://github.com/mikedh/trimesh/tree/dc8490c825c382d2d58b5bd87ecacc74790ead27)、[Open3D 0.20.0 PyPI](https://pypi.org/project/open3d/0.20.0/)、[trimesh 5.1.1 PyPI](https://pypi.org/project/trimesh/5.1.1/)、[Open3D LICENSE](https://github.com/isl-org/Open3D/blob/v0.20.0/LICENSE)、[trimesh LICENSE](https://github.com/mikedh/trimesh/blob/5.1.1/LICENSE.md)。

已核对 PyPI 公布的 wheel SHA-256，后续下载仍需实际核验，不能把网页摘要当本机已验包：

| wheel | 公布 SHA-256 |
| --- | --- |
| open3d-0.20.0-cp312-cp312-win_amd64.whl | 60010f21d44f13557ba007893bc13a69827faa4dc49eedd923d1397096c20d92 |
| open3d-0.20.0-cp312-cp312-manylinux_2_35_x86_64.whl | f5cc6106d9c0c41beb8160aa99c2b663e7f08588a598ec7d464391a4cfe684d6 |
| trimesh-5.1.1-py3-none-any.whl | c5be85a3e31e9ff749f9b0aecc204e37a2cf7cca4e92cd066bb5f3d3c1127765 |

Open3D 仅用于 CPU 几何，不启用 Open3D-ML、Torch 扩展或自动 CUDA。不能因仅使用几何就 --no-deps 跳过发行依赖。M2 已在隔离 Windows/WSL 环境安装并导入上述两个官方摘要对应的 wheel，原生验收见实施记录；未修改主开发 Python。Ubuntu 24.04 本机 ldd 检出缺少 libusb-1.0.so.0，测试使用官方 libusb-1.0-0 2:1.0.27-1 包解压到临时目录并显式设置本次 LD_LIBRARY_PATH，不修改系统。生产 Ubuntu 必须声明该系统依赖并在目标镜像检查全部 ldd 依赖，不能将本次单机结果当完整发行认证。完整传递依赖锁定、NOTICE 和 bundled profile 仍须正式发行验收；不降级现有模型依赖来迁就。

### 11.2 多格式 I/O 的具体源码核对

trimesh + Open3D 几何选型保持不变。2026-10-22 最终确认允许本项目维护 trimesh/pypcd4 的受控 Python I/O 修复版本，不向原仓库提交；这取代此前“不维护 fork”的限制，但不允许自建 RPly/C/C++ 扩展、运行时 monkey patch、调用私有原生符号或另写解析器。11.2.1–11.2.7 记录原版源码，不代表修复版已实现；最终路线见 11.2.8。必须区分库存在读写入口、修复方案确定、实际测试通过三件事。

#### 11.2.1 核对入口与文件

| 编号 | 固定版本公开入口与源码 | 核对内容 |
| --- | --- | --- |
| O1 | Open3D 0.20.0 open3d.t.io.read_point_cloud/write_point_cloud；[Python binding](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/pybind/t/io/class_io.cpp) | 参数、布尔返回/异常边界；不使用 legacy fallback |
| O2 | [PointCloudIO.cpp](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/open3d/t/io/PointCloudIO.cpp) | 按格式分派；未覆盖的写路径可能转 legacy，平台必须显式 allowlist |
| O3 | [FilePLY.cpp](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/open3d/t/io/file_format/FilePLY.cpp) | 字段映射、预分配、失败后对象、write 返回检查 |
| O4 | [FilePCD.cpp](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/open3d/t/io/file_format/FilePCD.cpp) | ASCII/binary/compressed、dtype、COUNT、rgba、组织/姿态与 writer |
| O5 | [FileTXT.cpp](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/open3d/t/io/file_format/FileTXT.cpp) | XYZ/XYZN/XYZRGB/XYZI 的精度与行处理 |
| T1 | trimesh 5.1.1 exchange.ply.load_ply/export_ply；[ply.py](https://github.com/mikedh/trimesh/blob/5.1.1/trimesh/exchange/ply.py) | ASCII/binary 完整性、属性与写出精度 |
| T2 | exchange.xyz.load_xyz/export_xyz；[xyz.py](https://github.com/mikedh/trimesh/blob/5.1.1/trimesh/exchange/xyz.py) | 整体读取、列推断、逐行边界和字段处理 |
| T3 | load_scene/load_mesh；[load.py](https://github.com/mikedh/trimesh/blob/5.1.1/trimesh/exchange/load.py) | 明确对象类型、加载器注册；没有 PCD 加载器，不能作为 PCD 失败后的替代 |

Open3D 的 Python read binding 调用底层 ReadPointCloud 后直接返回对象，没有检查返回 bool；write binding 返回底层 bool。这个事实本身不等于每次读取都错，但证明不能单凭“不抛异常且有点数”识别全部失败。不得通过进程全局日志/标准输出抓 warning 来建立正确性保证。

#### 11.2.2 逐格式结论与反例验收

下表是静态源码证据及由此形成的验收案例，**不是已运行测试结果**。没有一个条目因存在函数就自动成为生产支持能力。

| 版本/格式与方向 | 已核对的行为 | 本项目准入与独立用例 |
| --- | --- | --- |
| Open3D PLY 读取，ASCII/二进制 | O3 在 ply_read 前按声明点数分配 Empty tensor；失败路径返回 false 但未清空点数组，O1 丢弃 bool；不支持 dtype 有警告后跳过路径，普通点云不承载面/list 等全部元素；特定 3DGS 属性还存在 regroup/scale exp 路径 | 仅比较非空/shape/header 不足；构造声明 N 点但中途截断、坏 token、附加 element/property；特殊属性不能误作原样标量。无法可靠识别时阻塞，不发布部分云 |
| Open3D PLY 写入 | O3 writer 类型分支为 UInt8/UInt16/Int32/Float32/Float64；逐项 ply_write 和最后 ply_close 的返回未用于形成最终成功值 | true 不能代替完整性；磁盘满/短写/关闭失败，float64 小差异及所选属性逐字段核对；未支持 dtype 拒绝，不静默 cast |
| Open3D PCD ASCII 读取 | O4 遇短行可 continue；EOF 后未核对实际记录数达到 POINTS；数值转换未检查 token 全部消费；预分配点数不能证明实际读满 | 截断/少行、混合列数、数字后垃圾字符必须拒绝。不能只补一个返回 bool 检查就称修好 |
| Open3D PCD binary 读取 | 固定记录短读时有 Clear+false 路径；但公共 Python 接口仍无独立成功状态 | 不能把 PLY 部分对象问题直接套到此路径；需证明 header/实际字节/类型/字段一一对应、无多余记录，才可确定严格 profile |
| Open3D PCD binary_compressed | 按压缩头大小分配，校验解压器返回长度；文件数据读取路径未见与 POINTS×完整字段跨度的充分一致性检查 | 在分配前核对声明解码量/容量/算术及完整布局；解压失败、伪大长度、错 COUNT 等独立案例；不能只按压缩文件小于 1 GB 放行 |
| Open3D PCD 字段/空间 | 自定义字段按 N×1；rgba 解出 RGB，未保留 alpha；normal dtype 使用 position dtype；writer 自定义属性非 N×1 会跳过，HEIGHT=1、VIEWPOINT 默认 | COUNT>1、alpha、混合坐标/法线 dtype、组织/姿态不能宣称无损；需显式保留映射及 10.13 元数据或拒绝。ASCII Int64 使用 strtol，Windows long 宽度导致的风险还需双平台反例验证，当前不称已实测 |
| Open3D XYZ 等文本读写 | O5 固定 Float32 和 %f 读取，固定分量匹配未检查尾部多余列；writer 使用 float 指针及固定小数文本 | float64 小差异不能保存；即使输入为 float32，严格列数/尾部垃圾也不能靠当前接口保证。此路由不满足既定严格规格 |
| trimesh PLY ASCII 读取 | T1 整体读文本、拆行并逐行 np.fromstring；没有可直接依赖的全文件严格词法/额外行保证 | 1 GB 峰值不可假定有界；坏行、额外记录/列和非法 token 须独立检查；不把原有大量临时对象复制成平台解析方案 |
| trimesh PLY binary 读取 | T1 有声明字节数与剩余文件大小一致性检查；list 处理存在按首记录长度建立布局的路径 | 可作为固定标量二进制的进一步核定对象，不能推广为任意 list 完整支持；公开返回字段与源属性完整映射仍需证明，不能依赖 _ply_raw 私有约定作为稳定公开契约 |
| trimesh PLY 写入 | T1 坐标和法线明确打包为 <f4，返回整份 bytes | 对当前 float32 样本，binary 输出不存在强制窄化这一障碍；不适合作为所有输入的通用 writer，外部声明 float64 时不能使用。字段完整性、短写及整份 bytes 峰值仍需独立核对 |
| trimesh XYZ 读取 | T2 从首行推断列数，再对全文件 token reshape；不逐行检查列数；按列数决定颜色，其他属性不完整保留 | 不满足本项目明确列语义和严格行边界；有两行各少/多一列但总 token 数仍整除的反例 |
| trimesh PCD | T3 注册中无对应 loader | 不可用；不做失败转 trimesh 的兼容分支 |

字段可表达性、读取完成、写出完整和资源峰值是独立条件。保留原文件能提供原件追溯，但不能证明解析到规范数组的每个字段完整。PLY writer 的 float64 能力和读取者的失败检测也必须分别证明，不用“同库能读回”掩盖同一个静默错误。

#### 11.2.3 已确认的职责调整

2026-10-21 已确认：保持 trimesh + Open3D，XYZ 复用仓库已有 NumPy，允许按源码证据调整 I/O 职责。2026-10-22 先批准宽松许可专用 I/O 评审，再明确允许本项目受控修复，无需提交上游。以下保留原版源码证据；后续获授权的 M1 实施不改变几何栈、精度、输入范围与无降级规则。

| 对象/操作 | 定稿职责与当前状态 |
| --- | --- |
| 点云几何 | Open3D + 既有 NumPy/SciPy；不因文件入口缺口改用近似算法 |
| 网格/场景、拓扑与截面 | trimesh；对应阶段用明确 load_scene/load_mesh 与 process=False；不能隐式合并/修复 |
| XYZ 及明确列定义的变体 | 已批准使用 NumPy loadtxt/savetxt，具体规格见 11.2.5；不用 Open3D 的 Float32 文本路径 |
| 同机数组、平台无损资产 | 复用 LocalBuffer/Scope、资源版本与规范二进制数组，不经交换格式往返 |
| PLY/PCD | 分别使用 trimesh/pypcd4 受控修复版本；原版缺口见 11.2.4/11.2.7，已确认的修复责任、启用门禁见 11.2.8。不转交 Open3D 兜底 |

节点仍只有 read-cloud/export-cloud 一对，文件/数组均进入相同点云契约；不因扩展名增加包、资源服务、后台任务或第二套 Workflow。使用不支持的字段时必须在分配/解码前明确拒绝，不能先丢弃再称完整；现有 ASCII PLY 样本是必须覆盖的验收输入，不能因拒绝所有文件就宣称严格模式完成。

#### 11.2.4 本次 PLY/PCD 核定结果

本次核对固定版本公开接口的组合可行性，不安装/试跑。当前样本的 float32 已足够作为保存和传递类型；以下问题不能用整云转 float64 解决。先按失败类型列出实际缺口，后列通用属性边界。

| 故障或正常情况 | 固定源码与静态结论 | 平台必须采取的行为 |
| --- | --- | --- |
| 当前正常 ASCII PLY，XYZ float32 | O3 可按 Float32 分配；T1 ASCII 按属性声明 cast 后组成 vertices。文本解析的临时 double 不要求平台保留 double 云 | 按原文件读取，接收结果为 N×3 float32；不能以未要求 float64 为由拒绝。真实全文件读取尚未执行 |
| PLY 声明 3 点，仅 2 个完整数据行 | O3:261–269 先按 3 点分配，313–318 失败返回 false，O1:139–142 未传递该状态；T1:886–909 可只转换切片实际获得的 2 行，不对声明长度作相等校验 | 整次输入失败，无 cloud 引用；O3 的数组 shape 不能作已读满证明，T1 需要可靠的源声明元数据而非调用方猜点数 |
| PLY 行中截断、最后一个字段损坏 | O3 即使底层报错仍有上述状态丢失；T1 的坏 token 行为还依赖最终锁定的 NumPy 版本，不能只凭存在 np.fromstring 宣称全部拒绝 | 失败定位至少含文件/读取阶段，库提供时带字段/记录位置；未提供精确位置时不伪造行号 |
| PLY 多行或每行多一个合法数字 | T1:886 按声明记录切片，817–855 按已声明列取值，没有整份正文行数及每行列数终结检查 | 额外非空记录/字段不当作成功；两个库的 XYZ 值相同也不能证明无遗漏 |
| PCD ASCII 缺行/短行 | O4:531–558 短行 continue，结束后不核对 idx==POINTS；点数组已按 POINTS 预分配 | 坏行不能跳过后成功；不能由预分配长度或有限值比例推断完整性 |
| PCD ASCII 非法数字或数字后缀 | O4:341–350 调用 strtof/strtod 但不核对 end；如数字后附非数字字符的情况缺少完整 token 判据 | 非法 token 为格式失败，不变成零、NaN 或普通测量无效点；合法 NaN/Inf 则按有效性规则保留，由 filter-valid 显式处理 |
| 二进制截断 | T1:1013–1020 已检查声明布局与剩余字节相等；O4:561–567 固定记录短读 Clear+false | 保留这些有效检查，不笼统宣称所有路径都返回部分云；它们不自动覆盖 ASCII 或全部字段映射 |
| 附加字段遗漏 | O3:228–233 可跳过不支持属性；O4 的 COUNT、rgba、法向 dtype 处理与源声明不完全等价；T1 完整属性在内部 metadata._ply_raw | 必须取得读取器的完整源字段目录再与结果核对；不能仅拿输出字段与用户选择交叉核对后宣称未丢源字段 |

上表为源码推导和待执行反例，不是本轮动态复现。完整性检查要覆盖当前 float32 样本的同结构坏文件；不需要先支持所有网格/list 或未声明的未来字段，超出已声明能力的文件明确拒绝即可。

| 源码位置 | 新确认的行为 | 结论 |
| --- | --- | --- |
| trimesh 5.1.1 ply.py:69–134、543–745 | public load_ply 返回几何构造参数；完整 element/property/data 存入明确标为 internal 的 metadata._ply_raw，公开结果没有完整的原字段元数据契约 | 不能把私有返回约定包装成本项目稳定格式合同；公开 header-only 接口也未在所核对入口找到 |
| 同文件 :858–909、817–855 | ASCII 先逐行 np.fromstring（默认 float64），再按声明 dtype 转换；按元素声明长度切片，未对整份数据实施严格行/列终结检查 | 不仅是坏 token 的问题；额外列/记录不能只靠 shape 检出。扩展 int64/uint64 超过 float64 精确整数范围时可能在 cast 之前失真，不能据此承诺所有原字段无损 |
| Open3D 0.20.0 FilePCD.cpp:932–940 | ASCII writer 的 float 与 double 均用 %.10g | 对 float32，10 位有效数字不是精度不足的证据；对外部声明 double 的任意值不保证往返。此限制只约束该类型/编码，不是当前 PLY 样本需要 float64 的理由 |
| 同文件 :990–1151、1192–1220 | 数据写入路径存在不检查 fwrite 返回的分支，最终 fclose 返回也未用于成功判定 | write=true 不能覆盖短写/关闭失败；必须有独立、严格的写后验收才能发布下载引用 |
| Open3D FilePLY.cpp:133–172、175–335 | 属性映射、分配和读取耦合，失败状态未通过 Python read 返回；特殊名称可能参与 3DGS 语义处理 | 读取普通 XYZ 成功不能推出任意属性原样保留；需要完整字段元数据与完成判据，不能用数量/有限值抽查代替 |

上述位置均在 11.2.1 的固定版本源码链接内。Open3D 网站 release API 页面本次仍标为 0.19.0，不能拿移动文档页代替 v0.20.0 binding 源码。trimesh [公开 PLY API](https://trimesh.org/trimesh.exchange.ply.html)没有可打开全部严格语义的 strict 参数；不能凭 **kwargs 猜测存在未公开开关。

| 所需能力 | 可以保留的方向 | 当前无法冻结的具体部分 |
| --- | --- | --- |
| PLY ASCII 读取，包含现有样本 | 成熟 PLY 读取器负责 header、dtype、元素及数值；平台只做契约、预算、所有权与结果核对 | 当前两库未提供足以证明完整读取、原字段完整和分配前资源计划的公开组合；只补读后点数不够 |
| PLY binary LE/BE 读取 | 逐字段、声明/实际长度和端序核对；保留 float32/64 及全部被接收属性 | trimesh 的严格长度检查是有利事实，但不等于 header/所有属性的公共读取契约成立；不能靠 _parse_header/_ply_raw 完成新接口 |
| PLY 写出 | Open3D tensor binary little-endian 可保留 float32/64，作为通用候选；trimesh binary 对纯 float32 并非因精度被否定，但不为它增加平行 writer | 仍需完整字段表达范围和独立严格读回/短写校验；当前样本只验证 float32，double 使用独立声明用例 |
| PCD ASCII 读取/写入 | 成熟 PCD 处理器保留 FIELDS/SIZE/TYPE/COUNT、组织结构和 VIEWPOINT | 当前 ASCII 读取完成/词法不满足；输出精度另按声明 dtype 核定，不能把 float64 限制扩成 float32 不可用；NumPy 不是 PCD header 处理器 |
| PCD binary/compressed | 对声明布局与实际字节/解压量在分配前核定，再完整读写 | 公共点云对象未保留全部字段/组织元数据；COUNT、rgba、normal dtype 等限制未消除，写后检查也未闭合 |

“不自写解析器”边界保持明确：长度/hash/预算、结果 shape/dtype/字段集合、引用身份和资源释放属于平台校验；识别 PLY element/property/list 或 PCD FIELDS/COUNT/DATA 并自行计算字节布局、解码正文/压缩流，属于格式解析。不能把后一类代码改名为 guard、validator 或 NumPy adapter 来绕过约定。XYZ 已批准使用 NumPy，不表示获准手写 PLY/PCD 头部再接 NumPy。

不能采用的绕行：固定 skiprows=8 只读当前 PLY；先转 XYZ 导致字段/元数据丢失；截获全局日志把 warning 当返回状态；两库均未覆盖的同一错误只因“双读一致”就算通过；仅比较重新导出文件的 hash；读写失败后换库/格式继续成功。

以上结论仅针对未修改的上游版本，不宣称所有第三方实现都做不到。它们现在是 11.2.8 受控修复的输入，不再要求无限更换候选后才能开始实施。M0 的设计准入与 M1 的实际功能验收分开：路线已确认，原版仍不能直接开启严格文件能力；不重新设计六节点、Workflow 或发布系统，也不把未知现场容量、误差预算变成本轮新增设计障碍。

#### 11.2.5 XYZ / NumPy 定稿规格

已有 requirements 的 NumPy 范围为 >=2.2,<3；本次对照 [NumPy 2.2 loadtxt](https://numpy.org/doc/2.2/reference/generated/numpy.loadtxt.html)、[savetxt](https://numpy.org/doc/2.2/reference/generated/numpy.savetxt.html)和 [v2.2.0 源码](https://github.com/numpy/numpy/blob/v2.2.0/numpy/lib/_npyio_impl.py)核定接口，不升级/锁定 NumPy，也不声称当前实际安装就是 2.2.0。最终发行 lock 的实际版本须在 M1 重新执行这些用例。

| 项目 | 冻结的设计规格 |
| --- | --- |
| profile 与方向 | xyz-whitespace、xyzn-whitespace、xyzi-whitespace、xyzrgb-whitespace，profile_version=1，均为拟实现读/写 profile，不是已注册 Catalog。profile_id 只选择列语义，不固定全云 float64，也不由列数推断 |
| 列布局 | XYZ 恰好 X/Y/Z 三列；XYZN 恰好 X/Y/Z/NX/NY/NZ 六列；XYZI 恰好 X/Y/Z/I 四列；XYZRGB 恰好 X/Y/Z/R/G/B 六列。names/semantic/field_mapping 必须与 profile 一致，其他列拒绝而不是忽略 |
| 编码与行规则 | 使用已打开的受控 ASCII 文本流，不把路径字符串交给 NumPy 自动解压/下载；以 ASCII 空格/tab 分列，LF/CRLF 均可，空白行允许但不计点；不含 header、注释、引号、分组千位符或逗号小数。comments=None、delimiter=None、quotechar=None、usecols=None；不设跳坏行或自定义数值 converters |
| 完整读取 | loadtxt 按有界行块读取，ndmin=2；临时解析块可使用 float64，写入规范数组后释放，不因此形成整云 float64 副本。逐块核对列数和总非空记录数，任何解析异常使整个输入失败；必须读到真实 EOF。平台只限制行/块字节与累计数据量，不自写数字解析 |
| 精度/属性 | XYZ 无内置 dtype 声明，复用 file_options.field_mapping 的 dtype 显式指定 XYZ、法向和强度为 float32 或 float64，不增加另一套精度参数或从小数位数猜测。规范数组按该声明保存；有限值超出目标范围明确失败。颜色额外检查有限、整数、0..255 后才无损转 uint8；法向不自动归一，非有限数按有效性规则保留。PLY/PCD 的文件声明不能被此配置覆盖 |
| 写出 | NumPy savetxt 对 float32 列使用 %.9g、float64 列使用 %.17g，颜色列使用整数格式；这是数值往返格式，不是测量显示小数位。分块写已打开的临时文本流，保持点序、属性及当前单位，无隐藏归一/坐标变换。flush/close/存储发布异常均失败；完成后逐块按原 dtype 读回比较再提交 file-ref |
| 特殊浮点 | 有限 float32/64 的目标是在各自声明 dtype 下数值往返一致，负零符号单独核对；NaN/Inf 的类别和有效性不能变成零。文本不保证 NaN payload 位模式，完整位模式由平台无损资产保存，不能称 XYZ 为无损归档 |
| 字段选择 | 源云存在本 profile 无法表达的属性时，只有既有显式字段选择及 omissions 摘要允许导出子集；未显式选择则拒绝。输入绝不静默忽略附加列；任意带 int64 属性的文本不归入上述浮点 profile |
| 预算与取消 | 单次原始载荷 1 GB 规则不变，临时盘、行字节、块大小与规范数组预算来自显式运行策略，数值不猜；块间检查取消，不反复拼接全量数组、不产生新线程池/等待队列 |
| 单位与空间 | 仍使用 file_options.spatial；XYZ 文本不包含完整单位/坐标定义，重新导入必须明确确认，导出沿既有空间缺失告知；不从文件名/值域猜单位 |

M1 验证：空输入、单点、多块边界、CRLF/LF、空白行、缺列/多列/每行不等列、错误 token、注释/逗号/非法编码、超行长/超累计限额、声明 float32/64 的独立往返/范围/负零用例、NaN/Inf、RGB 边界/非整数/NaN、写入/关闭失败、最后一块取消、Preview/Runtime/SDK 的字段一致性。验证规范数组真实 dtype，不只看三维视图是否显示。没有安装/运行证据前，这些 profile 状态是“设计就绪、实现与验证未开始”。

#### 11.2.6 ASCII PLY 样本与严格验收的必要条件

2026-10-21 只读确认了现有文件的大小与前 16 行：文件 479,677,235 字节，头部声明 format ascii 1.0、element vertex 14745099、property float x/y/z，没有在头部声明颜色或附加字段。2026-10-22 沿用这份证据，明确该输入的规范 XYZ 为 float32，不按文本的小数位数改变 dtype。未重新扫描全部记录、未重新计算 hash、未执行读取器，因此不能把“头部声明点数”写成“本轮已完整读取点数”。既有完整报告和摘要仍按第 12 节标为历史证据。

| 验收集合 | 必须证明 |
| --- | --- |
| 原始样本 | 按原 ASCII PLY 文件直接输入；完整核对声明/实际点数、XYZ float32 类型、按声明类型解析的逐值与点序、边界及原文件未改变；不预先转 XYZ/binary PLY，不截成四位小数，不为读取/保存/传递常驻升为 float64 |
| 同结构反例 | 声明点数多/少、整行或行中截断、最后一行损坏、额外列/记录、重复/缺失属性、缺 end_header；不得返回“看似合理”的部分云 |
| 无损与通用性 | 增加已声明的 float64 小差异、颜色、法向、标量和整数边界；每个被接收字段逐项对应。超出契约的 list/mesh/属性明确拒绝，不能悄悄只取 XYZ |
| PCD 独立集合 | ASCII/binary/compressed 分别测试 COUNT、组织信息、VIEWPOINT、RGBA、混合 dtype、解压声明与实际不符，不能用 PLY 测试替代 |
| 输出可靠性 | 源值与独立期望比较；writer 完成标志、实际文件完整性、读回结果三个条件分别核对；磁盘满/短写/关闭失败不得生成成功引用 |
| 双平台与资源 | Windows/WSL Ubuntu 使用相同 profile 语义；按输入大小、峰值、临时磁盘、取消/终止回收验证，不填未经确认的运行时限与预算 |

这些是 M1 功能启用的证明要求，不是待实现的自定义解析算法。G1 的实现来源已由 11.2.8 定稿；真实样本与反例在修复后验证，不把尚未执行的用例写成已通过。接口/契约设计就绪不等于实际文件处理已可用。

#### 11.2.7 获准后的专用 I/O 候选评审

2026-10-22 评审宽松许可的成熟 I/O 依赖，几何栈仍为 trimesh + Open3D。下表保留三个候选的原版核对结果，不修改环境、不下载发行包、不把搜索结果当采用结论；未重新引入已排除的 RPly 自建适配、meshio 或 plyfile。最终采用的是 11.2.8 的受控修复路线，不是下表原版直接可用。

| 固定候选 | 许可、维护与发行证据 | 源码结论与选择状态 |
| --- | --- | --- |
| pypcd4 1.5.1 | BSD-3-Clause；2026-10-05 发布 py3-none-any wheel；依赖 NumPy、Pydantic、python-neo-lzf，后者的双平台原生发行与完整依赖许可尚未验收 | PCD 专用，公开 MetaData 与 pc_data 能表达 FIELDS/SIZE/TYPE/COUNT、VIEWPOINT 和组织信息，方向比几何对象直接 I/O 合适。但当前版本的完成/头部/压缩检查仍有缺口，不能直接冻结为严格读取器 |
| pyvista-miniply 0.5.2 | MIT；2026-09-03 发布；有 CPython 3.12 abi3 Windows x64 / manylinux x64 wheel；硬依赖 NumPy，PyVista 为可选 | Python read 返回坐标、三角形、法向、UV、颜色五组，不返回任意属性及完整源目录，无 PLY writer。XYZ/法向固定 float32，完成错误未完整传递；不选作本项目通用严格 PLY 入口。其原名 pyminiply 0.2.3 不作为当前版本结论 |
| pyntcloud 0.3.1 | MIT；本次 PyPI 所列最新发行仍为 2022-07-31，纯 Python wheel；读取依赖 pandas/NumPy | PLY reader 未核对实际记录数与 points_size；额外字段/元素处理及 writer 类型声明存在缺口，不能补齐现有库的完整性保证。未仅因发布时间较早就否定，而是按源码缺口不采用 |

发行与许可证来源：[pypcd4 1.5.1](https://pypi.org/project/pypcd4/1.5.1/)、[许可证](https://github.com/MapIV/pypcd4/blob/v1.5.1/LICENSE.txt)、[依赖声明](https://github.com/MapIV/pypcd4/blob/v1.5.1/pyproject.toml)；[pyvista-miniply 0.5.2](https://pypi.org/project/pyvista-miniply/0.5.2/)、[项目声明](https://github.com/pyvista/pyvista-miniply/blob/v0.5.2/pyproject.toml)；[pyntcloud 0.3.1](https://pypi.org/project/pyntcloud/0.3.1/)、[许可证](https://github.com/daavoo/pyntcloud/blob/v0.3.1/LICENSE.md)。这些是上游发布事实，不是本机安装/ABI/性能验收。

源码定位及不能直接采用的原因：

| 源码 | 已核定事实 | 平台校验能补什么、不能补什么 |
| --- | --- | --- |
| [pypcd4 v1.5.1 pypcd4.py](https://github.com/MapIV/pypcd4/blob/v1.5.1/src/pypcd4/pypcd4.py)，75–169、214–276 | 公开 metadata 保留布局；ASCII 用 loadtxt，binary 按声明长度读取，但构造函数不核对实际条数，from_fileobj 最后 seek(0)；parse_header 对不匹配行跳过、重复键覆盖 | 对公开 metadata 的字段数、dtype、COUNT、width×height 和实际数组行数可做平台校验；但丢失的头部重复/坏 token 证据与正文终点不能仅从返回对象恢复。无需复制解析器，需成熟入口提供严格完成信息 |
| 同文件 224–239、930–975 | compressed 校验解压返回长度，却未据完整布局拒绝多余解压数据；ASCII writer 使用固定 %.10f；压缩失败自动递归改为 binary | float32 的极小非零值也可能被固定小数位写成零，此处不是只讨论 float64。禁止未经声明改编码；compressed writer 当前不能直接启用，binary writer 可继续核对但不代表读取链路已通过 |
| [pyvista-miniply v0.5.2 wrapper.cpp](https://github.com/pyvista/pyvista-miniply/blob/v0.5.2/src/wrapper.cpp)，LoadPLY | 只提取固定几组属性，positions/normals 是 float；load_element 失败未统一转异常，最终 gotVerts 失败检查被注释，提取返回值未形成完整完成判据 | 对当前 XYZ float32 不存在必要升精度问题；仍不能检测被遗漏的任意标量，或证明整个源内容完整。不能因为 miniply C++ 有更丰富接口就假称 Python binding 已提供 |
| [pyntcloud v0.3.1 ply.py](https://github.com/daavoo/pyntcloud/blob/v0.3.1/pyntcloud/io/ply.py)，129–170、239–263 | ASCII read_csv 不核对 points_size；binary fromfile 不检查返回条数；writer 按 dtype 名首字母写 property，不能区分 float32/64 或不同整数宽度 | 返回数组检查不能补回未公开的声明条数/完整布局；writer 有声明与数据类型不一致风险，不能作为独立严格读回的依据 |

固定源码文件身份：pypcd4.py blob SHA `908067cf1cf67b4512b1ad5357466f92bb7e8760`；pyvista-miniply wrapper.cpp blob SHA `60e90cc9b0a4d4b74f39c5df7f02548f49a1954a`；pyntcloud ply.py blob SHA `6deda6ed3221043f60c81ab42a70b09e9075ef67`。平台不复制其解析函数，也不依赖内部字段建立公开契约；获准的源码修改集中在受控依赖版本内。

**原版评审结论：未发现上述原版可直接满足全部要求；这不是生态中不存在可用实现的证明。最终不再扩大候选清单，而是按已确认的 11.2.8 修复成熟路径。** 补查的 meshio++ 也不能直接替代：固定提交 `75d770d7ac68fd756f1cb31469d4857906ab7920` 的 [PLY reader](https://github.com/loumalouomega/meshioplusplus/blob/75d770d7ac68fd756f1cb31469d4857906ab7920/src/cpp/src/formats/ply.cpp) 第 338–349 行按已声明字段取 token，未检查行末多余 token；不因为项目近期活跃就选入。该补查不是采用 meshio 或新 C++ I/O 栈。自行编写解析器、修改原生绑定、重新采用被排除依赖或缩减格式范围仍需另行确认。

#### 11.2.8 最终确认的严格 I/O 修复路线

2026-10-22 确认：允许在本项目使用受控修复版本，**不需要向原仓库提交**。方案是修复成熟 Python I/O 库，不是在平台内另写 PLY/PCD 解析器。以下保留设计职责；原版实测、已实现和未完成项分别记录于 [M1 I/O 实施记录](3d-metrology-m1-io.md)。

| 唯一职责 | 基线与范围 | 不做什么 |
| --- | --- | --- |
| PLY | trimesh 5.1.1 的 exchange.ply；修复读取、类型化属性接口、写出与相应用例 | 不修改网格/几何算法；不经 Trimesh 对象自动合并点、修复网格或重新计算法向；不转 Open3D 读取 |
| PCD | pypcd4 1.5.1 的 MetaData、PointCloud 读写；复用 NumPy 和上游 LZF | 不新增第二套 PCD parser、压缩器或自动改编码；不把 COUNT、rgba、VIEWPOINT 简化掉 |
| XYZ | 11.2.5 的现有 NumPy 路线 | 不增加另一项依赖或偷偷推断列/精度 |
| 平台适配 | 现有 worker 内调用固定依赖 API，将字段映射为第 5/10 节规范数组；核对预算、输出和所有权 | 不将解析器复制进 backend/custom_nodes；不建 I/O 服务、队列、进程或另一套资源管理 |

**依赖内的修复规格：** 以下是获准后 M1 必须实现的 API 能力，不是声称上游已有这些函数或参数。沿现有读写接口扩展必要的严格检查、头部检查和分块能力；不预先制造一套通用格式插件框架。

| 范围 | 精确修复责任 | 可核对的完成条件 |
| --- | --- | --- |
| PLY 头部与源字段 | 在原 parser 中校验完整关键字/版本/类型/计数、元素与属性唯一性、属性归属、必需终止；不得先覆盖重复属性再检查。提供公开只读描述：编码/端序、正文偏移、有序元素/条数/属性及原 dtype；预算确认前不分配整云 | 缺 end_header、重复/错误属性、无效/负计数、未知类型、额外头部 token 均拒绝；所有源元素与字段可见，平台不读取 _ply_raw 或调用 _parse_header |
| PLY ASCII | 在既有读取路径使用 NumPy 的类型化文本读取，按有界块消费；去掉逐点 Python 数组列表和全文件字符串拆分。保持每条记录的完整列数，严格数值转换、目标类型范围、声明记录数及真实 EOF；不先统一转 float64 再转换整数属性 | 当前 14,745,099 点 XYZ float32 样本直接输入；缺行、短行、多列、多行、非法 token/后缀、整数/浮点越界分别失败；合法 NaN/Inf 与格式错误分开。保留全部受支持字段、顺序和 dtype |
| PLY binary | 保留原有声明/实际长度核对，扩展公开元数据与分块读取；按照原 parser 给出的布局处理 LE/BE；计数乘积和预算先检查 | 整条/半条截断、尾随字节、错端序声明、字段数量不符有确定结果；不推广首记录 list 长度为全部记录长度 |
| PLY 写出 | 修复原 writer 的坐标/法向固定 f4、整份 bytes 返回路径；明确类型化属性、目标端序和受控流写入；按源 dtype 写出 ASCII/binary。ASCII float32 使用足够往返的 9 位有效数字、float64 17 位，整数不经浮点中转 | 不再把外部 double 窄化为 float；当前样本仍 f32；颜色、法向、标量逐字段保留；短写、flush/close 失败不能返回成功 |
| PCD 头部与数组 | 在原 parse_header 中拒绝重复键、未知/坏行及多余 token；完整校验 FIELDS/SIZE/TYPE/COUNT、唯一名称、合法类型宽度、POINTS=WIDTH×HEIGHT、VIEWPOINT。公开头部检查、正文偏移及原字段到 COUNT 展平列的映射；排除名称冲突 | 字段目录在解码前可用；保留组织/姿态，不因重命名或 COUNT 展平静默覆盖数据；平台检查现成 metadata，不重新实现 PCD 头部语法 |
| PCD ASCII/binary | ASCII 沿 NumPy loadtxt，关闭隐式注释/跳坏行，精确列数、数值类型/范围、记录数与 EOF；binary 先核对完整布局和实际正文长度，再按块读取；去掉读取完成后无条件 seek(0) 的证据丢失 | 缺行/整行截断、少列/多列、坏数字、额外记录/字节都失败；COUNT>1、混合 dtype、RGBA 与组织信息不丢失，不能用 shape 正确代替读满证明 |
| PCD 压缩 | 仍由上游 LZF 解码；在调用前比对压缩头、文件实际长度、完整字段布局推导量、预算；解压后精确长度相等并完整消费所有列块。本次 Windows/Ubuntu x64 profile 明确 little-endian 前缀，不依赖 struct 原生格式，也不声称 PCD 头部有端序字段 | 声明长度溢出、压缩/解压短读、额外压缩字节、解压量与字段布局不等均拒绝。解压通常需要整块目标，预算必须计入，不虚称流式/零复制 |
| PCD 写出 | 修复固定 %.10f 和压缩失败自动切 binary；ASCII 按 dtype 保证数值往返，binary 保留原始字段字节。原 FIELDS/COUNT、WIDTH/HEIGHT/VIEWPOINT 在仍有效时完整写回 | 显式 compressed 无法生成时报告失败，不换格式；浮点小值不写成零，组织/姿态不自动变默认。压缩临时峰值计费，参数不能绕过容量限制 |

M1 点云 profile 仍只接受已声明可表示的点属性，不要求支持任意 mesh/list；成熟 parser 必须报告它们，不能忽略后仅接收 XYZ。未被第 5 节支持的类型、异构坐标 dtype 或字段语义明确拒绝；受支持的新增标量不丢弃。PCD 库保留 COUNT 原始分组和 RGBA 打包属性，不等于平台已支持任意向量/颜色布局：无法按 5.5/7.4 显式无损映射的输入整份拒绝，不能仅取前三分量或丢 alpha；不得在本轮悄悄扩大数组契约。该规则不缩小已确认的文件编码或当前 ASCII 样本范围。颜色、法向和 3DGS 风格属性名只作显式字段映射，不在 I/O 自动归一、exp 或改值。文本 NaN payload 位模式不作交换保证，平台无损资产仍保留位模式。

读写事务沿既有资源流程：不可变文件快照 → 依赖头部检查 → 字段/预算准入 → 完整解码到暂态 owner → 全部验证成功后交付 cloud。中途解析出的块不能对下游可见，任何错误释放本次资源。导出为受控临时对象 → 确认写完并关闭 → 严格读回与源数组逐块比较 → ObjectStore 提交。不能只比较同库读写后的 hash；独立手工期望/预先核定的二进制夹具在测试中覆盖公共错误，运行时以导出前数组为比较源。异常包含文件身份、方向/阶段、库实际提供的字段/记录/偏移，不伪造定位；损坏输入是执行失败，不是测量 INVALID。

**受控依赖与发行约束：**

1. 每个依赖只保留一个可安装版本。基线 tag/commit、补丁提交、修复说明、许可证、测试结果和最终 wheel SHA-256 共同标识修复版；使用可区分上游的本地版本号，不能伪装为未修改的 5.1.1/1.5.1。本轮不填写尚不存在的 wheel hash。
2. 源修改仅限这些 I/O 模块、必要公开接口/类型和测试。按普通依赖构建并锁 wheel；不直接改 conda/site-packages，不在启动时打补丁，不用 projectsrc 作为运行时依赖，也不复制成第二个解析包。依赖构建材料与应用源码/发布产物分开，后续复用现有依赖准备和 assembler/profile，不新建三维安装器。
3. Open3D 使用上游原版。pypcd4 的 python-neo-lzf 采用上游 wheel，不修改其 C 源；[0.3.5 发行文件](https://pypi.org/project/python-neo-lzf/0.3.5/)已列 CPython 3.12 Windows amd64 和 manylinux x86_64，许可证列 BSD-3-Clause。[源码 LICENSE](https://github.com/FledgeXu/python-neo-lzf/blob/main/LICENSE) 包含 binding BSD 三条款和 liblzf 的 BSD/GPL 二选一条款，发行采用 BSD 路径并保留对应声明；所阅 LICENSE blob 为 `fd7a9980ce9bd70b0370e1ce8a22c9531db8ce01`。网页和源码证据不等于已下载验包，M1 必须核对实际 wheel 内容、全部传递依赖与 ABI。
4. conda 开发、bundled Python、Windows/WSL 使用相同修复来源；不能开发态装修复版、发行态由 requirements 自动拉回上游原版。沿既有依赖身份/发布执行检查记录实际包版本与内容摘要；新增节点不使无关旧 Workflow 失效。
5. 后续升级需逐项重审修复与格式回归，不按版本更高自动替换。无需提交上游或等待其合并；也不承诺上游未来会修复。本项目保留维护责任，不保留运行时双版本兼容或失败降级。

**M1.1 的有限执行顺序与验收：**

| 顺序 | 实施与验证 | 通过后才允许 |
| --- | --- | --- |
| I1 冻结回归夹具 | 按 11.2.6 构造独立期望；把原版缺口逐个变成反例，记录原版实际结果；保留现有完整 ASCII PLY 样本 | 开始受控修复，不以本轮静态分析冒充已复现 |
| I2 修复 PLY | 先公开完整头部/属性与严格结束语义，再修 ASCII 分块、binary、writer；每项修复后对应回归和审计 | Windows/WSL 小夹具都通过后，用原始样本完整读取，核对 f32/点数/值/序及释放 |
| I3 修复 PCD | 头部和 COUNT/元数据 → ASCII/binary → compressed → writer；按同一严格规则验证 | 全部编码、混合字段、组织/姿态、写失败和压缩异常通过后冻结版本 |
| I4 依赖和资源验证 | 构建修复 wheel，核对实际依赖/许可证；在双平台记录解析、写后重读、LZF 的真实峰值、取消及终止回收 | 按已确认运行策略配置容量；未知数值不填默认值，不追加队列或降精度 |
| I5 接入六节点 | read-cloud 与 export-cloud 共用唯一适配；接既有 Scope/Resource/ObjectStore、Catalog、Preview/Runtime 和错误显示 | 按 14.1 继续同机数组、单位/有效性、显示、保存及组合验证；未通过的 profile 不在 UI 显示可用 |

**收口判断：成熟实现来源、受控修改许可、修复责任和验证步骤均已明确，M0 的 G1 可以作为设计项关闭，进入 M1 的方案已具备。不能宣称“已有未经修改即可落地的严格库”，也不能宣称 M1 已完成。** 本节明确的 NumPy 读取接口调整属于成熟库组合内的修复；若实施必须改写成自研格式/数值解析算法、自建原生扩展或更改已确认格式/精度范围，则在该变更处停止确认，不扩大授权。

### 11.3 开发与发行矩阵

| 目标 | 当前机制/证据 | 三维交付必须补齐 |
| --- | --- | --- |
| Windows x64 conda | 基于已确认解释器的隔离 venv 已验证 I/O；原环境未改动 | 完整几何依赖、节点数组/算法及 Scope 资源释放；不影响现有模型链路 |
| WSL Ubuntu x64 源码 | Python 3.12.3 隔离 venv 已验证 I/O 与完整样本 | 几何库、节点映射和完整发行仍待验收；WSL 通过不等于所有 Linux 发行版通过 |
| Windows CPU bundled | release_assembly 支持 windows/x64/cpu，使用 requirements_cpu.txt | 离线 Python、3D 依赖/DLL/许可证、禁用包行为及前端资源验证 |
| Windows NVIDIA bundled | 支持 windows/x64/nvidia，使用 requirements.txt | CPU 三维与既有 CUDA/TRT 共存；不自动启用 Open3D-ML/CUDA |
| Ubuntu CPU/NVIDIA bundled | profile 文件存在，但 release_assembly 的受支持目标仅有两项 Windows；Ubuntu profile 也未配置同样的 requirements_file | 不能宣称 Ubuntu 离线发行已实现；在原 assembler/profile 扩展支持并独立验收，不新建三维打包器 |
| macOS/ARM | 不在本轮目标 | 不写入当前兼容或验收声明 |

真实源码：[release_assembly.py](../../backend/maintenance/release_assembly.py)、[release_runtime_validation.py](../../backend/maintenance/release_runtime_validation.py)、[release profiles](../../runtimes/manifests/release-profiles)。assemble-release 不等于安装完整 Python 依赖，保留的已有 Python 与 placeholder-empty 必须区别；不能通过文件夹存在声称可运行。现有许可证复制也不能替代新增第三方依赖的 NOTICE 清单。

最低交付核对项：直接及传递依赖版本/hash/许可证、wheel tag/系统库、离线安装来源、原生线程控制、禁用可选包不拖垮平台、源目录构建前端、Windows/WSL 两入口生命周期测试。CAD/TIFF/厂商 SDK 属于后续能力，既不强装，也不声明首批已支持。

## 12. 真实样本与参考证据

本节是通用回归样本的来源和语义说明，不是某客户的生产配方。原始数据及探索产物不提交到仓库，不因文档引用而获得公开分发许可。目录仅帮助开发人员找到已有证据，运行时代码不得依赖这些本机路径。

### 12.1 来源与已确认事实

- 需求来源会话：`查看3D点云软件`，ID `6ad6c37b-4338-83e9-b4d6-5185431a9db6`；`检查锂电点云并设计测量`，ID `01a15c55-9096-7ab3-9899-bee6bb9eece0`。
- 原数据开发位置：`W:\doc\项目\锂电测量检测\资料\3d轮廓`，文件 `1-1_0.ply` 和 `1-1_0.bin`。
- 探索产物位置：`C:\Users\tanga\Documents\Codex\2026-10-21\referenced-chatgpt-conversation-this-is-an\outputs`。重要文件包括 `measurement_config.json`、`measurements.json`、`dimensions.json`、`标注测量端点.json`、`标注核对说明.txt`、最终含高度总图与侧视图。
- CloudCompare 的本机开发位置为 `D:\software\CloudCompare`，仅用于既有对照，不成为安装/运行前提。
- 用户已确认单位 mm，相机型号 MV-DP3120-01P，带孔底板为载物台面；不需要再次把单位列为该样本未知项。
- 用户定义本样本 t 为工件普通表面到台面的高度，H 为突起/钢片相对邻近基体的高度，Z 为钢片到台面的高度。t 的现场“厚度”名称依赖支撑关系，不推广为任何单面点云都可测材料厚度。

既有报告记录以下源摘要；本次文档整理读取其记录，没有重新计算原始文件哈希：

| 文件 | 字节数 | 报告记录 SHA-256 |
| --- | ---: | --- |
| `1-1_0.ply` | 479677235 | `ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b` |
| `1-1_0.bin` | 235922432 | `208ca451f70130631f1f90b218a3c01dbecbe107b24baba0d670ac53735392c5` |

PLY 头部和抽样已核对为 ASCII、14745099 个 XYZ float 点，无 RGB。既有完整报告记录 BIN/PLY XYZ 相同，BIN 另有等于原始 Z 的标量；原始 Z 不是已消除台面倾斜的相对高度。

报告记录 4950 个扫描 Y 位置，典型 X/Y 步距约 0.03 mm；每行点数不同且存在间断。该值是采样信息，不是测量准确度。Z 的数值格点规律也不能替代相机精度证明。台面拟合倾角约 0.996127°，拟合内点 RMS 约 0.014046 mm，同样不等于不确定度。

### 12.2 样本要求与当前参考值

工件有 6 个突起组、12 个钢片和 2 个目标半圆槽。必须能查看逐片 L/W/H/Z、6 个邻近基体 ROI 的 t、整体尺寸和半圆槽直径，并直接核对点云中的端点、边界与方向。6 组结果不能替代 12 片独立结果。

最终细化报告的整体可见投影包络为约 132.832 × 48.141 mm；台面 X/Y 方向跨度为约 83.464 × 113.039 mm，两者不是同一测量定义。先前 133.064 × 48.244 mm 为已被细化结果替代的粗包络，不可混作同一版本的预期值。

S1/S2 半圆槽拟合直径约 20.146/20.170 mm，默认使用 h=0.25 mm 等高边界；此前约 2 mm 的 H1–H3 是其他小开口。S2 仅有部分圆弧支持，说明中记录约 91° 缺口；结果记录实际拟合角扇区 63/160，不能把扇区数直接当连续圆弧跨度。改变边缘阈值时，报告中的直径范围约为 S1 20.00–20.33、S2 20.15–20.22 mm。

以下逐片结果从最终 `measurements.json` 读取并四舍五入，仅用于追踪定义及界面，不作为未经标定的准确度真值：

| 样本特征 | L/mm | W/mm | H/mm | Z/mm |
| --- | ---: | ---: | ---: | ---: |
| A_top_L | 7.916 | 6.987 | 1.121 | 1.569 |
| A_top_R | 7.886 | 6.927 | 1.101 | 1.514 |
| A_bottom_L | 8.128 | 7.015 | 1.133 | 1.689 |
| A_bottom_R | 8.168 | 7.021 | 1.148 | 1.666 |
| B_top_L | 7.947 | 6.969 | 1.195 | 1.688 |
| B_top_R | 7.947 | 7.012 | 1.146 | 1.637 |
| B_bottom_L | 8.232 | 7.032 | 1.168 | 1.592 |
| B_bottom_R | 8.251 | 7.035 | 1.130 | 1.550 |
| C_top_L | 7.947 | 7.016 | 1.201 | 1.695 |
| C_top_R | 7.923 | 7.111 | 1.169 | 1.720 |
| C_bottom_L | 8.190 | 7.093 | 1.179 | 1.668 |
| C_bottom_R | 8.040 | 7.141 | 1.250 | 1.795 |

邻近基体 t 约为 A_top 0.457、A_bottom 0.516、B_top 0.471、B_bottom 0.441、C_top 0.536、C_bottom 0.533 mm。H 在钢片中心对拟合基体求差，t 在邻近 ROI 取中位数，位置不同，不能强制 H+t=Z。右下组两片的 Z 差约 0.127 mm，单组平均会遮蔽该差异。

参考图中的钢片 L/W 为带圆角的可见投影包络，不证明缺测后的完整实体尺寸。尺寸辅助线的外移仅为排版；实际端点保存在单独证据文件。高度侧视图横纵比例不同，需要明确显示，不能从图片比例反算尺寸。

### 12.3 从样本脚本提取的防错要求

- `pointcloud_measure.py` 固定检测 12 区域，再按源坐标排序两两配对；通用实现必须替换为模板驱动的特征身份和配对，不照搬这些常量。
- `semicircle_dimensions.py` 固定两个槽 ROI、初始位置和筛选范围；这些只能转为样本模板参数。
- `plane_height_at_xy` 在源 XY 求平面点再投影到基准高度；正式“沿基准法向”的两面间距必须按第 6 节另行定义和验证，不能直接视为等价。
- 报告、绘图、文件读取、特征和算法混合的脚本不能整体搬进 handler。需要提取可独立验证的算法，采用正式契约和资源管理。
- 空洞、扫描缺点和部分圆弧必须作为回归输入，不能只保留完整区域。
- 探索报告记录过合成算法测试通过、源文件未改动；这些是历史证据，不代表新节点已测试、标准件已标定或跨平台已验收。

### 12.4 样本使用方式

M0 建立显式的本地资产配置与摘要核对规则，不把 C/W/D 盘路径写入测试默认值。缺少真实样本时，普通单元测试可以报告未运行该资产用例，但正式真实数据验收必须阻塞，不能以 skip 计为通过。

新算法若改变测量定义，必须解释差异并建立独立解析真值，不能为了复现报告的小数位保留方向错误或边界偏差。真实图纸公差、参考仪器、重复扫描与采集标定未提供，当前不能作产品合格结论。

## 13. 完整验证矩阵

| 领域 | 必测场景 | 通过条件 |
| --- | --- | --- |
| 解析 | ASCII/二进制、字节序、字段重排、截断、极端数量、非有限数、路径与容量 | 明确接受/拒绝；无越界、无静默丢字段、无失控分配 |
| 单位/坐标 | mm/m 转换、变换组合/逆、手性、法向反转、跨帧错接 | 同物理量一致；不合法组合提前拒绝 |
| 定位/基准 | 任意平移旋转、倾斜台面、近竖直平面、次基准缺失、对称多解 | 不依赖源 Z/屏幕方向；未约束姿态不能伪装有效 |
| 高度 | 倾斜且不平行的两面、不同评价位置、近乎平行测量线、局部外推 | 与解析交点一致；方向/位置误用被捕获 |
| 身份 | 候选顺序打乱、不同特征数量、缺失、多余、歧义及错误分组 | 稳定 ID；必检不因缺失而消失 |
| 几何 | 直线/圆/圆柱、短弧、大缺口、退化点集、噪声/异常、边缘圆角 | 方法内误差达预定界限；不可辨识时 INVALID |
| 形状/体积 | 非平面、局部凸起、开网格、多层高度、CAD 离散误差 | 不把残差冒充标准指标，不猜闭合体积 |
| 规则 | 限值端点、量纲不匹配、必检为空、无效与超差混合 | OK/NG/INVALID 和详细项一致；错误不伪装 NG |
| 界面 | 端点与数值联动、标签移动、坐标变换、LOD 拾取、色标/裁剪 | 标注不改变计算，实际支持与外推可区分 |
| 生命周期 | 切换任务/节点/数据、晚响应、卸载、重连、取消、timeout、恢复 | 无串对象、旧订阅、旧资源和旧 generation 回写 |
| 资产发布 | 内容冻结、导入导出、缺资源、摘要不符、引用删除 | 可复算、可追溯；不依赖开发机绝对路径 |
| 工程资源 | 大点云、重复局部查询、缓存淘汰、线程、文件/mmap/WebGL 释放 | 与冻结预算对照；无无界增长、无隐式队列 |
| 平台 | Windows/WSL Ubuntu、CPU、bundled Python、禁用包/缺可选依赖 | 支持矩阵清楚，无关流程不受影响 |
| 计量准确度 | 可追溯标准件、重复扫描、多姿态和现场环境 | 独立误差/重复性/不确定度报告；不以单次拟合代替 |

合成数据应有独立解析真值；不能用被测函数生成“真值”后再验证自身。原始样本、另一类真实工件及标准几何共同防止过拟合当前 PLY。改变阈值和采样分辨率的敏感性试验独立记录，不自行放宽通过门槛。

本阶段不重启此前模型/小图 P99 追查，不重复运行无关长稳。后续三维性能和资源验收须限定数据、并发、环境、预算和时长；需要长稳时另行确认，自动执行不超过已约定的一小时，长时间现场验证由使用方安排。

## 14. 以节点和算法为主线的实施阶段

阶段按可操作的测量能力组织，不按“依赖 → 契约 → 准入 → 生命周期”等平台事项组织。下表和各小节定义交付范围，不是当前可用能力清单；已完成的 M1/M2 内部实现及验收以第 1 节链接的实施记录为准。

| 阶段 | 本阶段可交付的功能 | 直接复用 | 必要扩展 | 完成证据 |
| --- | --- | --- | --- | --- |
| M0 设计确认 | 节点、算法定义、操作步骤、数据和测试规格 | 现有源码和架构文档 | 仅文档；剩余条件见 15.5 | 设计自洽、复用有依据、未定项有明确影响阶段 |
| M1 点云输入、处理与查看 | 文件/数组输入，单位和有效性处理，三维查看，保存/导出 | 文件服务、LocalBuffer、Scope、Catalog、Preview、App Mode | 点云类型、读写节点、显示节点与共享 viewer | 两入口得到一致数据；读回无损；异常/取消后释放；前端可操作 |
| M2 ROI、基准与定位 | 裁剪、平面拟合、基准坐标和刚性变换 | M1 点云、已有参数编辑/Preview 和执行机制 | 4 个几何节点、ROI/基准编辑控件 | 独立几何真值；坐标/失败传播；图上配置与实际执行一致 |
| M3 常用尺寸与判定交付 | 高度/高差、长宽/间距、圆孔，公差和三态结果 | NumericTable、Check Limits、Result Record、交付节点、发布管理 | 8 个特征/测量节点；受影响规则和显示字段升级 | F1–F7、正式 Runtime、结果读取方一致；旧发布按影响审核 |
| M4 高级几何测量 | 圆柱/截面/圆角、形状/缺陷、面积/体积及几何关系 | M1–M3 的算法、特征和证据体系 | 每种方法的完整定义、算法和参数 UI | 每种方法独立真值、退化条件和误差依据 |
| M5 新输入与参考比较 | 标定深度/高度/轮廓输入，参考云/网格/CAD 偏差 | 同一数据入口、资源、Workflow | 对应类型、转换与比较方法 | 标定/距离定义/许可及代表性输入验证 |
| M6 现场交付与离线发行 | 已有 App 导入导出携带三维资源，结果报告/集成，双平台发行 | 版本/Runtime/Trigger、ObjectStore、assembler/profile | 三维资源搬运与依赖打包；实际缺失的平台目标支持 | 离线部署、引用可读、版本可追溯；不是首次实现发布 |
| M7 冻结候选验收 | 冻结本批已交付功能的组合、资源、性能及准确度证据 | 现有测试工具和运行管理 | 本批三维用例 | 证据与限制分别报告；结束清理本任务资源 |

顺序为 M0 → M1 → M2 → M3；M4/M5 按确认需求推进，不用未知 CAD/厂商 SDK 阻塞首批。M6/M7 对每批已声明功能执行，不要求完成全部未来算法才允许首批交付，也不能用首批通过声称 M4/M5 已完成。

### 14.1 M1：点云输入、基础处理、查看、保存

目标是能在现有 Workflow 中建立“输入 → 单位处理 → 有效点过滤 → 三维查看”，并显式接保存/导出分支。M1 就交付真实节点，不只做平台基础设施。

| 步骤/节点 | 实现内容与算法 | 复用与扩展 | 前端操作 | 验证 |
| --- | --- | --- | --- | --- |
| M1.1 读取文件 read-cloud | 先执行 11.2.8 的 PLY/PCD 受控修复与回归，再接文件节点；XYZ 沿 NumPy；校验完整性、字段、单位/坐标与预算 | 复用文件快照/ObjectStore/worker；扩展点云引用与库适配，不另写解析器 | 文件选择、格式和字段摘要、单位确认；错误定位到文件/字段 | 原版缺口反例、现有完整 ASCII PLY、各编码和字段、双平台/资源；未通过前不列可用 |
| M1.2 同机数组输入 | 按第 10 节布局交接只读坐标/属性；后续算法不区分文件来源 | 复用 Broker、PREPARE/REQUEST/ACK、App Contract 和 Python/.NET SDK；不另建入口服务 | App 显示已发布输入类型；浏览器文件表单不冒充可写 mmap 的客户端 | 与文件相同独立真值；重复/过期 token、交接失败、writer/worker 退出与图片路径回归 |
| M1.3 normalize-units / filter-valid | 显式单位换算、有限值/掩码/声明哨兵过滤，保留源索引 | 复用 NumPy 与资源作用域；扩展数组借用、派生 owner 和清理失败保留 | 显示前后单位、点数、移除原因；不隐藏去噪或降采样 | 单位等价、零坐标保留、空云、属性对齐；分支借用/取消/停止无悬空引用 |
| M1.4 cloud-preview | 生成有界显示点与属性，不修改计算点云；交接前脱离原始运行句柄 | 新增一个三维显示节点及 viewer；复用 ui.preview、完成后交接、显示槽与观察连接 | 旋转/平移、标准视图、复位、单位/坐标、颜色与色标；图中打开共享查看区 | 显示数值/范围可核对；视角不改算法；旧请求、卸载、显存与显示过期测试 |
| M1.5 save-cloud / export-cloud | 原文件原样保存；内存/派生平台无损保存；显式交换导出 | 扩展现有计量资源服务、流式 ObjectStore 和引用检查；不新增资产系统 | 明确原始/派生和目标格式；列出字段/精度差异；成功后给受控下载引用 | 逐字节/逐字段读回；取消、磁盘满、hash 错、原云已释放、重复导入及资源被引用 |
| M1.6 本阶段交付 | 上述节点接入实际 Catalog、Preview、现有发布与 Runtime | 注册与代码同时交付；禁用新包不能影响其他节点 | 编辑、监视、App Mode 共用显示；文件动作可完成且可取消 | Windows/WSL 两入口、保存重读、发布启动及有界显示组合验证 |

依赖确认、必要字段类型、资源责任和测试夹具随这些节点实现，不独立交付一个“3D 平台”。15.5 的 M0 设计项已收口；明确获准实施后，M1.1 先完成受控 I/O 修复、隔离验证和依赖锁定，不直接把原版读取函数接成可用节点。尚不需要网格算法时只使用 trimesh 的 PLY 路径，不调用其网格算法，更不强装 CAD/厂商 extras。

M1 不提前改变 Check Limits 或 Result Record 的公开语义；点云有效性是点数据质量，不是产品 OK/NG。资源格式确需升级时，在 M1.5 同批完成受影响引用和迁移保护。发布新包沿用已有机制，不要求无关 App 重发。

### 14.2 M2：ROI、基准平面与坐标定位

| 步骤/节点 | 实现内容与算法 | 复用与扩展 | 前端操作 | 验证 |
| --- | --- | --- | --- | --- |
| M2.1 crop-roi | 按物理坐标和明确闭边界裁剪，输出源索引子集 | 复用 M1 只读云；扩展 roi3d 和受控参数编辑器 | 图形选区与数值中心/尺寸/方向同步；显示 ROI 所属坐标系 | 边界、旋转、空域、单位/frame 不一致；取消编辑不改参数 |
| M2.2 fit-plane | 正交 SVD；稳健方法显式 RANSAC 后内点重拟合 | NumPy/SciPy/Open3D 按确定方法复用；一个共享实现供节点和工具使用 | 选择区域、方法与法向；显示支持点、剔除点、残差及方向 | 已知旋转/近竖直面、外点、共线/少点、法向翻转；真值不调用被测拟合器 |
| M2.3 build-frame | 基准面、原点、面内轴/次基准建立完整工件坐标系 | 复用特征 ID 与 pose3d；不把平面自动当完整姿态 | 逐项选基准，图中显示原点和轴；缺约束时指出缺哪项 | 次基准缺失、平行、矛盾、多解不能给单位矩阵冒充成功 |
| M2.4 transform-cloud | 显式刚性变换位置/法向，保留标量属性 | 共享矩阵计算和资源借用；不隐式缩放/镜像 | 明确源/目标坐标系和变换结果，视角旋转不改变数据 | 组合/逆变换、长度不变、属性保留；失败不得复用上次矩阵 |

本阶段只输出几何有效性、质量和证据，不以缺少最终公差判定阻止几何算法开发。Preview 与正式 Runtime 使用同一套节点；成功 → 失败 → 成功的连续输入必须逐次隔离，不残留上一工件的基准。

### 14.3 M3：常用尺寸、公差与结果交付

高度/高差可先于轮廓算法完成，不要求所有特征算法完成后才出现第一项可用尺寸。

逐节点输入、算法、质量/失败、前端交互、复用源码和实施验收见 [M3 尺寸测量节点设计](3d-metrology-m3.md)。M3.1 两节点、M3.2 三节点、M3.3 三个尺寸节点已内部实现，分别见[高度记录](3d-metrology-m3-height.md)、[边界记录](3d-metrology-m3-boundary.md)、[尺寸设计](3d-metrology-m3-dimensions.md)和[本批验收](3d-metrology-m33-acceptance.md)。M3.4 公开三态和 M3.5 含最终规则的正式配方仍待交付。有序边界沿原 CloudRuntime 扩展，不新建 Workflow 或发布版本管理；生产节点仍未启用。

| 步骤/节点 | 实现内容与算法 | 复用与扩展 | 前端操作 | 验证 |
| --- | --- | --- | --- | --- |
| M3.1 height-query / measure-step | 指定位置的局部平面与方向交点；显式区分方向面差和 ROI 统计差 | 复用 M2 基准和拟合、NumericTable；扩展尺寸证据 | 输入/拾取查询位置；选择参考/目标 ROI；显示实际测量线、符号、单位和方法 | 无支持、多层、方向平行、非平行面位置效应、交换变号；不切换到最近点算法 |
| M3.2 extract-boundary / fit-line / fit-circle | 明确投影/截面/等值边界；有序段；TLS 直线、几何圆拟合 | 复用共享几何与坐标；扩展有序边界和稳定特征选择 | 点选/列表选同一特征；显示支持段、开闭轮廓、拟合与实测边 | 凹形、多孔、缺扫、短弧、非共面和多候选；凸包不能冒充真实轮廓 |
| M3.3 measure-extents / measure-edge-pair / measure-hole | 轴向跨度/包络、指定两边距离、孔圆心与直径 | 调共享算法，不调用其他 handler；共享证据、数值和质量 | 选择尺寸定义、评价面/方向/边/孔；表格与尺寸标注联动 | 包络与拟合边距分别验证；非平行位置依赖、遮挡、孔支持不足、缺测 item_id 完整 |
| M3.4 既有规则和记录升级 | 在原 Check Limits/Result Record 实现 OK/NG/INVALID；按 8.4 真值表，不新建三维判定器 | 复用 NumericTable/LimitRule 与交付节点；同时更新实际读取变更字段的模块 | 复用限值编辑表；显示合格/超差/无法判定及原因，缺测不是 0 | 缺必检、空必检、optional、混合状态；UI/SDK/PLC/DB/记录一致；既有二维调用回归 |
| M3.5 F1–F7 与正式调用 | 形成可复用配方，连接既有预览、发布、Runtime 和交付 | 不复制 Workflow、App Mode、协议连接与版本服务 | 工程师预览审核发布；现场按公开输入运行并查看结果 | Preview/正式运行一致，任务切换/晚返回、默认不保存原云、显式保存后复算 |

M3.4 改变的是共享公开结果语义，必须在新语义启用前落实第 8.6 节的影响盘点、执行检查与审核重发，生产者和结果读取方同批交付。不能把升级保护拖到 M6；也不能把 M3.4 写成 M1 所有算法开发的前置条件。当前不实施旧版兼容分支、不把旧 NG 猜改成 INVALID。

### 14.4 M4：高级几何与表面测量

| 功能组 | 算法与交付内容 | 复用/扩展 | 界面与验证 |
| --- | --- | --- | --- |
| 圆柱、截面、圆弧与圆角 | 明确支持域、拟合目标、轴和半径、截面方向与曲率定义 | 复用特征/拟合/证据；网格截面按需要调用 trimesh | 显式选择截面/特征；解析圆柱/圆弧、部分覆盖、病态数据独立验证 |
| 几何关系 | 点线/点面距离、边到孔中心、角度与相应符号/位置定义 | 复用已拟合特征和 NumericTable，不为每种工件做新节点 | 两对象点选与列表同步；空间/投影距离分别标识，退化关系拒绝 |
| 平面度、平行度、翘曲 | 每种正式评价方法定义评价域、目标函数、约束、收敛与保证 | 复用基准和支持点；扩展实际缺少的评价算法 | 显示评价域、残差/公差带及方法；不能以 RMS 冒充最小区域结果 |
| 凸起、凹坑、崩边 | 相对参考的差分、有效覆盖、区域连接与特征量 | 复用云/高度/边界；增加明确缺陷算法 | 支持区、缺测区、缺陷区分开；缺测不自动算缺陷 |
| 面积与体积 | 投影面积/表面积、基准积分/闭合网格体积分开 | 按对象复用 NumPy/Open3D/trimesh，不隐藏表面修复 | 显示参考与封闭条件；独立真值、采样敏感性、自交/缺口/朝向异常验证 |

去噪、重采样、自动配准若成为公开能力，必须另补该方法规格、参数与准确度影响后作为显式节点接入，不能藏在读取/拟合中。高级方法未实现时不显示为可用选项。

### 14.5 M5：新输入和参考比较

| 功能组 | 实现什么 | 复用/扩展 | 前端与验证 |
| --- | --- | --- | --- |
| 深度图/高度图/扫描轮廓 | 带标定/步距/缺测信息转为明确物理几何 | 复用点云后续链路；新增对应输入类型和转换节点 | 展示标定/单位/轴和覆盖；比例、内外参、缺行/倒序真值验证 |
| 参考云/网格/CAD 比较 | 基准对齐与最佳拟合分开；距离、符号、覆盖和离散误差明确 | 复用资源和定位；CAD 依赖与格式另行确认 | 参考选择、偏差色谱、超差区及覆盖不足；不宣称所有 CAD 支持 |
| 外部采集系统 | 使用已完成文件/同机数组输入，每次提交完整数据 | 复用 SDK；确有直连需求再设计受信任自定义节点 | 不默认新增实时点流或厂商常驻服务；通用链路不依赖相机 SDK |

### 14.6 M6：现场交付与离线发行

| 步骤 | 实现或核验什么 | 复用什么 | 如何验证 |
| --- | --- | --- | --- |
| 配方搬运 | 现有 App 导出导入携带三维持久资源、字段/单位和引用映射 | AppVersion、资源版本、ObjectStore、Runtime 选版/启停页面 | 新环境导入、资源缺失/版本失配明确拒绝；不使用开发机绝对路径 |
| 结果交付 | 在既有输出节点落实现场映射；按确认需求补报告/SPC 输出 | HTTP/PLC/DB/文件节点及统一结果来源 | 量值、判定、执行、交付失败分别呈现；SPC 不把 null 当 0；外部系统另行签收 |
| 离线发行 | 三维依赖与前端随现有 profile 打包；补齐实际缺失的 Ubuntu assembler 支持 | 现有 conda/bundled Python、assembler/profile，不新增三维发布器 | Windows CPU/NVIDIA 与 WSL Ubuntu 源码/离线包分开验证；无 CDN/系统 Python/Node 前提 |

M6 是本批交付验证，不是首次实现发布、运行或结果交付。M1–M3 每个对外功能已经必须接通对应已有链路。

### 14.7 M7：冻结本批候选验收

1. 固定提交、依赖、输入摘要、配方和运行配置，明确本批声明支持的节点/格式；未完成算法不计入支持范围。
2. 执行后端、前端、SDK、原有图片/模型共存和发布恢复组合回归；不重复改造或验证无关系统。
3. 在明确硬件、算法和数据条件下测试包含 1 GB 输入的内存、线程、映射、磁盘、取消和延迟；不增加等待队列、不以显示降采样替代算法精度，不复跑旧模型 P99。
4. 数学真值、真实样本、标准件/重复扫描分别报告；缺少溯源依据不能宣称现场计量精度通过。
5. 获准后持续运行不超过一小时；更长验证由现场安排。结束停止本任务服务并清理本任务临时产物。

### 14.8 每个节点的交付与审计顺序

1. 先写清节点输入、方法、参数、输出、失败和独立期望值，确认没有现成同义算法或平台功能可直接复用。
2. 实现共享算法及薄 handler；同步必要的类型、资源访问、取消、参数控件和显示，不先注册空壳。
3. 验证算法正常/退化结果，再验证 Workflow 接线、资源释放和界面操作；共享类型变更覆盖所有实际读取方。
4. 审计精度、缺测、单位、隐藏拷贝、发布影响和晚返回；只重跑修复影响的用例，不机械重复全部性能/长稳。
5. 留存该节点/阶段的版本、配置、验证结果和限制；功能未通过不标可用。未知 timeout/预算不能用任意默认值补齐注册。

## 15. M0 收口结果与进入实施的条件

### 15.1 本轮 M0 收口的设计与停止条件

本轮以代码事实重排了工作内容，不重新审计整个仓库，也不重新选择依赖栈。以下是设计结论，不是代码完成状态。

| 事项 | 收口决定 | 对应章节/后续位置 |
| --- | --- | --- |
| 节点与平台关系 | 新增 3D Metrology 算法包，不重复实现节点目录、Workflow、AppVersion、Runtime、进程组或协议连接 | 3.1、14；全部阶段遵守 |
| 算法开始时机 | M1 实现读写/单位/有效性/显示，M2 实现基准几何，M3 实现尺寸；不是九项平台重建之后才开始算法 | 7.2、14.1–14.3 |
| 三态的实施位置 | 是测量判定，不是任务状态；M3.4 在原规则和结果模块同批更新实际读取方 | 8.4–8.6；新语义启用前完成发布保护 |
| 前端使用方式 | 工程师沿现有画布/检查区/Preview 配方；现场沿同一发布的 App Mode 输入和看结果 | 9.5–9.8；不新建角色/页面设计器/连接 |
| 大数据传递 | 文件与同机数组汇入同一云引用；数据面与图资源释放按已有机制扩展 | 10.4–10.9；M1 随节点实现 |
| 保存与升级 | 原文件保留字节，内存/派生无损资产；仅对确需变化的内容/引用设计新版本与审核重发 | 10.11–10.12、8.6；不是整个项目数据迁移 |
| 验证节奏 | 每个节点的算法、接口、UI、异常和释放同批验证；双平台按阶段覆盖 | 14.8；最终冻结候选才做资源/性能验收 |

G1 的原版缺口见 11.2.4/11.2.7，已确认的解法为 11.2.8 受控 Python I/O 修复版本，仅在本项目使用、不提交上游。XYZ/NumPy 职责及源 dtype / 局部计算边界不变。G2 已在 7.4/9.9/10.13 明确字段、端口、显示、两入口、持久引用及全部读取方。M0 设计收口后，实际修复、安装与验证属于 M1，不再把它们列为“尚未找到方案”；也不把设计收口写成格式已可用。不重新通读整个项目、不自行改选 RPly、不缩小样本覆盖。

已有资源与发布入口继续复用：[app_version_service.py](../../backend/service/application/workflows/app_version_service.py) 形成发布依赖，[node_pack_lifecycle.py](../../backend/nodes/node_pack_lifecycle.py) 已有包内容摘要，[runtime/lifecycle.py](../../backend/service/application/workflows/runtime/lifecycle.py) 与 worker 负责启动身份。需要核对的是实际加载代码和冻结要求的一致性，不是新增版本管理器。实现身份的逐字段细化只在改变相关发布依赖时完成，不据此扩大成全仓库哈希系统。

资源格式升级使用既有版本和项目协调入口：盘点确受影响引用 → 备份 → 新建内容版本并校验 → 显式映射草稿引用 → 审核重发 → 启动验证。失败不留下成功引用，重试识别已提交版本，历史文件和结果不覆盖；新加三维类型不自动要求迁移全部二维资源。若确需数据库结构变化再附正式迁移，不预设必须修改数据库表。

清理设计仍以 10.7 为准：复用 Scope/worker 的关闭与失败归属，不另建故障回收器；一次清理失败不能仅再次 close 就宣称释放成功。这是接入大数组别名时需要落实的责任，不据此宣称现有所有节点不可用。

M0 完成标准是实现规格明确而不是提前完成实现/安装/性能测试。首批节点的数学定义与失败行为均须可验证；严格字段按即将实施阶段完成，M4/M5 未定方法不能阻塞 M1。当前真实未完成项和对应停止点只在 15.5 维护。

### 15.2 M0 必须交付的内容

以下是完整产出要求，不是全部完成清单；本轮进度见 15.5。设计结论补充在本基线对应章节，不另建平行规划；进入实现后，正式 schema、节点定义和测试以源码为唯一机器可执行来源，文档只保留语义与链接。

| 工作项 | 具体交付物 | 验收方式 |
| --- | --- | --- |
| D1 模块归属 | 现有入口、调用方向、拟新增模块、资源 owner 和消费者清单 | 每个复用结论有真实文件/符号；不得以目录存在推断能力已实现 |
| D2 数据契约 | 首批引用、坐标、ROI、几何、证据的逐字段规格，合法/非法示例及版本策略 | 所有单位、身份、缺测、数组布局和跨运行行为均有明确解释 |
| D3 节点规格 | ID、capabilities、端口、参数、依赖、取消、输出与失败原因；实际版本/timeout 的配置责任和启用条件 | 首批七项功能可由规格组成完整 Workflow，不需要隐含脚本；不在 M0 伪造发布版本或超时值 |
| D4 规则变更 | Check Limits 的状态真值表、布尔放行语义、消费者清单及显式迁移方案 | 混合 NG/INVALID、缺失必检、空集合和旧发布版本均有确定行为 |
| D5 验证资产 | 解析几何生成规则、独立期望值、真实样本配置/摘要、异常案例和缺失资产策略 | 测试真值不调用被测算法；现场准确度缺口单独标记 |
| D6 依赖与发布 | 候选版本/API、传递依赖与许可证核对、平台/ABI 验证方案、发行 profile 影响 | 不降级既有模型依赖；必要与可选边界明确；安装/ABI 实测属于获准后的 M1，不伪装已通过 |
| D7 前端与资源 | 工作流交互顺序、状态/操作表、证据联动、释放表及资源预算项 | 每种晚返回、切换、卸载和取消都有负责清理的对象 |
| D8 实施与回归 | 按模块的变更顺序、迁移检查、测试分组和阶段完成证据要求 | 无重复运行时、无隐藏队列、无工件专用常量；未通过项不标完成 |

资源预算至少包含文件大小、点数、单次解析峰值、派生数组/索引缓存、浏览器点数与显存、原生线程数和单次取消等待上限。M0 给出各参数来源及配置归属，数值需要代表性数据和目标设备验证，不能把当前机器的空闲容量直接写成产品默认值。

### 15.3 首批实现的模块边界

| 层级 | 实现归属与职责 | 不得承担的职责 |
| --- | --- | --- |
| 公共契约 | `backend/contracts/workflows/` 中独立三维契约模块；复用 NumericTable 的观测和数值身份 | import Open3D、解析大文件、持有设备或进程连接 |
| 平台服务 | 既有 Workflow/文件资源应用服务中扩展三维资产校验、版本和访问控制；API 只做请求与任务边界 | 在请求线程直接拟合、将原始数组内联到响应、为三维重建调度器 |
| 执行资源 | 复用 `ResourceScope` 和既有 Preview/Workflow 执行边界，明确只读持有、借用及派生数据释放 | 把当前 scope 误当通用数组传输协议，绕过 owner/取消/停止边界 |
| 算法包 | `custom_nodes/metrology3d_nodes/shared/` 按输入、几何、配准、测量和质量拆分；目录为拟新增 | 固定产品数量、写平台状态、直接操作前端或 PLC |
| 节点适配 | 新包 manifest、分类及薄 handler；将正式契约转换为共享算法输入输出 | handler 互相调用、复制算法、统一吞异常后返回零值 |
| 通用规则 | Core Rule、数值契约及其现有消费者统一版本化 | 在三维包中重复实现公差引擎或把 INVALID 当有效 NG |
| 前端 | 既有 Workflow 编辑/预览/结果入口和共享三维组件 | 按每个工件新增页面、按屏幕像素保存测量 ROI、重新计算正式量值 |
| 测试与发行 | 复用仓库 Python、前端、集成测试及 profile 机制；新增前端测试放在 `tests/frontend/` | 将一次性脚本、`.tmp/` 或手改 release 目录作为交付物 |

包内目录只是责任划分，不要求为每种几何创建一套 manager/service。M0 应核对现有 helper 后决定具体文件，避免先按规划生成大量空类。公共层只抽取确实跨包的语义，不把算法包整体提升进平台核心。

### 15.4 首批七项功能的端到端验收设计

以下场景在 M0 冻结规格，在 M1–M3 按依赖实现并验证。每个场景都包含后端结果、前端操作和失败行为，不以“单个函数能返回数字”作为完成。

| 场景 | 操作与输入 | 必须观察到的结果 | 必须拒绝或解释的情况 |
| --- | --- | --- | --- |
| F1 导入与单位 | 受控 PLY/PCD/XYZ 资产分别进入同一 Workflow，查看字段或列并确认源单位 | 原始资产不变、规范化数据可追溯、预览单位清楚；与同机数组入口的独立真值一致，重开仍绑定同一内容版本 | 未知单位、截断、错误字段、解压超预算、XYZ 列歧义；更换文件后不得复用旧确认 |
| F2 基准 ROI | 选择台面 ROI、拟合参考平面，配置法向和所需次基准 | 支持点、剔除点、残差和坐标方向可核对；平面成立与完整坐标系成立分别表达 | 点数不足、退化、缺少平面内轴约束；不能自动补成完整工件姿态 |
| F3 指定位置高度 | 在明确坐标系中输入/拾取 XY，选择测量方向和局部表面方法 | 表中量值、测量线、表面交点、基准点和支持范围一致 | 查询落在空洞/支持域外、方向近乎平行、多个表面未消歧 |
| F4 双 ROI 高差 | 选择两处表面并指定同位置方向距离或独立统计差 | 输出方法、位置、符号与质量证据；交换参考/目标时行为符合定义 | 不同方法不得只用同一“高差”名称掩盖；不支持处不能补零 |
| F5 轮廓长宽 | 定位后选择包络或拟合边方法，确定评价面/轴 | 长宽与真实端点联动，旋转工件后相应物理尺寸保持一致 | 缺边、可见轮廓不足、投影与图纸定义不同；不得冒充完整实体尺寸 |
| F6 孔与圆弧 | 提取目标边缘，指定截面、内外轮廓与拟合条件 | 圆心、直径、支持弧、缺口和拟合质量可同时查看 | 小 RMS 但短弧病态、多个候选、边缘定义变化；不得自动选择任意孔 |
| F7 公差与交付 | 给稳定 item_id 配置必检、单位和上下限，发布并读取结果 | OK/NG/INVALID、逐项原因、布尔放行与表格/协议输出一致；发布后资源冻结 | 必检缺失、单位不匹配、无效与超差混合、资源缺失；执行错误单独传播 |

相同规格应覆盖 Preview 与正式 Workflow 运行，不能只让预览可用。文件型三维输入复用既有 HTTP/文件资源路径；完整二进制点云只要求同机调用，复用 LocalBuffer 底层，类型和所有权扩展按第 10 节审查后形成正式契约。连续实时流及 ZeroMQ 点云传输不在本轮范围，不宣称当前图片 LocalBuffer 已支持点云数据。

前端操作状态至少区分未选择数据、读取中、待确认单位、可编辑、计算中、结果有效、测量无效、执行失败和已取消。它们是界面设计状态，不直接新增后台任务枚举；须映射既有任务与结果状态。修改数据/坐标/方法后旧结果可以保留作明确标识的历史查看，但不能作为当前结果判定或发布。重新计算、取消和返回编辑须复用现有动作与取消机制。

### 15.5 进入 M1 的剩余条件与后续验收限制

已确认的产品范围不再反复询问：每次完整输入；文件与同机数组；原始载荷上限 1,000,000,000 字节；默认不保存原云；平台无损保存与显式 PLY/PCD/XYZ 导出；trimesh + Open3D；不自建原生解析器；资产包独立限额；仅受影响旧发布审核重发。当前状态如下。

| 设计项 | 本轮结论 | 还缺什么、影响哪一步 |
| --- | --- | --- |
| 功能与复用边界 | 已明确 18 个拟定首批节点，现有规则/记录不复制；阶段均列出实现、复用、扩展、UI 和验证 | 代码和用例尚未实现，不把待实现列为新的架构疑问 |
| 输入、数组与资源责任 | 第 5/10 节逐字段、二进制、owner/借用/交接/释放与 10.13 全部读取方已核对；Preview 大文件整块复制需在原入口扩展 | 实际映射/复制/清理行为在 M1 验证；不把设计规格写成现有点云能力 |
| 精度与数据量 | 当前样本 float32 保存/传递，外部文件按声明；算法按需局部 float64；取消整云强制提升和 XYZ 固定 f64 profile | 不是未决项，也不是当前样本的 M1 障碍；按实际 dtype 验证及计费，不承诺四位小数等于统一现场精度 |
| 几何与测量语义 | 第 6/7/8 节已有独立定义、退化条件、质量和真值方案 | M2/M3 各节点实现前补齐该方法参数合法域；不要求 CAD 等未来算法先定稿 |
| 判定与读取结果的模块 | 真值表、原规则扩展位置、读取方清单和受影响发布策略已明确 | M3.4 之前完成实际影响盘点、实现身份细节和同批变更；不是 M1 数据算法前置重构 |
| 前端操作与归属 | 9.9 已给显示正文、精度/预算、只读/编辑边界和生命周期；复用现有观察连接与共享查看器 | 真实可用性/WebGL 尚未实现验证，不能把设计审计当浏览器验收 |
| 依赖与格式 | 受控 I/O 修复已构建，Windows/WSL 格式回归及完整样本通过；Open3D 几何、XYZ/NumPy 不变 | 节点事务、完整离线依赖与 bundled profile 仍待接入验收；不采用原版代替修复版 |
| 双平台与真实计量 | I/O 验证和资源观测已执行，不是三维生产发行或计量验收 | 现场容量和溯源数据仍分别约束对应验收 |

**M0 已收口，M1 已按后续授权开始。I/O 修复及双平台验证已落地；原版不能直接用于严格入口，I/O 通过也不等于六节点、资源事务或生产测量已验收。无需重新遍历候选库。**

| 编号 | 必须补齐的内容 | 完成证据与停止条件 |
| --- | --- | --- |
| G1 确定版本的文件读写方案 | **M0 设计通过，M1 I/O 基础已实现并实测通过**；版本、hash 和证据见实施记录 | 完整依赖发行及节点 owner/事务仍需验收；约 480 MB 样本不是 1 GB 全算法容量承诺 |
| G2 M1 六节点与两入口 | **六节点、资源 API 与固定资产发布、同机 Trigger/.NET SDK、Preview 大文件上传和资源/三维组件已接通**；最新进度见[真实发布运行验收](3d-metrology-m1-published.md)。源行号与原始总点数已覆盖跨资产恢复；完整样本已通过真实发布版本与 Runtime 准入，Windows 使用 .NET、Ubuntu 使用独立协议客户端，覆盖切版、异常退出、停止恢复与资源回收 | 格式能力实现与 UI 同步启用；复用节点、Workflow、资源、发布和进程管理，生产包仍隐藏且不填写未知 timeout/容量 |

I/O 隔离安装、native import、库峰值和 wheel 身份已见实施记录；正式 schema、节点所有权和完整发行仍属后续 M1 工作。验证失败不能默许换库/降级。

以下是功能启用或现场验收前的条件，不与 G1/G2 混为一谈；已答“未确定”的参数不重复索取，也不填样本常量。

| 参数或工作 | 最迟确定/验证的位置 | 当前未定时允许和禁止的事 |
| --- | --- | --- |
| manifest timeout、kill grace | 对应节点实际注册/运行前 | 可完成字段和算法设计；不能复制其他包数值或注册空包。数值需运行策略与受控验证依据 |
| 数组/解码/索引、原生线程和临时盘预算 | M1 相应分配/执行能力开放前，后续算法增加成本声明 | 可确定计费和释放责任；不能承诺 1 GB 全算法/任意并发，也不能用隐藏队列或降精度兜底 |
| 显示点数/字节/显存、证据保留期 | M1 cloud-preview / 持久证据启用前 | UI 设计可完成；不能把未定视作无限，不能发送完整 1 GB 云到浏览器 |
| 资产包独立上限与资源升级影响 | M1.5 导入/导出开放前 | Workflow 输入上限不变；不自动覆盖旧资源或迁移所有数据库 |
| 共享规则升级与实现身份校验 | M3.4 新判定语义启用前；M1 若改变旧资源/发布语义则提前到对应步骤 | 不阻塞不改变旧语义的算法开发；受影响旧发布必须保护，不能仅前端禁用 |
| 外部 PLC/MES/数据库映射 | 对应正式外发前 | 仓库内契约可测；外部消费者未签收不能宣称现场交付通过 |
| 最低 RAM、目标并发/节拍、延迟指标 | 相关容量/性能验收前 | 不阻塞数学真值和单节点开发；不作工业节拍或固定并发承诺 |
| 图纸、公差、标准件和重复扫描 | 现场准确度与产品放行验收前 | 可做独立几何测试；合成真值不能代替真实计量溯源 |
| Ubuntu bundled 组装支持 | Ubuntu 离线发行前 | WSL 源码验证与离线发布分开；复用原 assembler，不造三维打包器 |

M1 实施已获后续授权。I/O 基础完成不等于节点已可用；未迁移或删除数据，未启动本任务服务，也未执行 P99/长稳。

2026-10-22 后续确认：先完成内部实现并用显式测试配置验证，生产节点启用等待 timeout 和容量数值，不自行填写默认值。Ubuntu 运行数据使用原生文件系统，源码和只读输入样本仍可位于 Windows 盘，不迁移现有数据。实现与验证进度统一记录在[输入适配记录](3d-metrology-m1-input.md)，不将内部 helper 通过等同于六节点、Trigger、SDK 或页面完成。

### 15.6 本轮文档审计记录

源码基点为 `945872933f75f9f07954978fcd8fdaf00fb4dcc8`，本次核对日期 2026-10-22。工作区变更仍限文档，保留此前已有修改；没有改动运行时代码、依赖清单、锁文件、数据或生成 Catalog。

M0 历史审计沿用已确认精度边界，定稿 11.2.8，并纠正旧选型状态；禁止运行时 monkey patch、自建 C/C++ 和自写解析器的边界不变。当时仅核对 LZF 发行元数据和源码许可、PLY 头部/大小，没有完整读取证据。后续 M1 的实际验包、完整样本读取和双平台结果已单独记录，不覆盖或混淆原版证据。

契约交叉审计补齐了此前未定的六节点参数、固定资源输入、资源五字段引用、PCD 组织信息、原件/派生保存、显示正文及两入口交接。核对到 Preview 当前整块文件复制与资源服务整包 bytes 路径，明确在原边界流式扩展。修正文档中的 read/save 端口简表，使其与详细规格一致；unavailable 的空身份不再被显示规格当成真实资源。没有建立另一套节点、Workflow、版本管理、进程、缓存或显示连接。

此前已核对前端的受控参数编辑、参数输入绑定、Preview 显示、App Mode 与发布入口；三维 renderer 尚不存在。本轮未重新访问业务页面，不把文档设计记成三维 UI 已实现或浏览器验收通过。

M0 历史文档审计核对了本基线、ADR 与目录入口；当时 9 份相关文档的 189 个本地链接、表格、标题、围栏和行尾空白检查通过，git diff --check 通过。当时没有应用/算法测试证据，也没有任务临时文件。后续 M1 I/O 的实现、测试和清理结果以独立实施记录为准；未知现场容量仍不能被填成运行默认值。

## 16. 当前待确认项与风险

| 项目 | 当前事实与处理 |
| --- | --- |
| 图纸公差、节拍与准确度目标 | 当前未提供通用目标；按模板/场景分别约定，不写一个全行业默认门槛 |
| 标准件与重复扫描 | 当前样本未标定，需补独立准确度与重复性证据 |
| 相机实际采集接入 | 型号已知，但 SDK 版本、Linux 支持和部署授权未核实；不阻塞文件型测量 |
| 深度/轮廓样本 | 需要带元数据的代表性输入，不能从 XYZ 文件猜其相机原始格式 |
| CAD 输入范围 | 首先明确 STEP/BRep 与网格比较范围；不宣称支持所有 CAD 格式 |
| 点云调用与规模 | 已确认逐次完整点云、文件与同机内存二进制数组；载荷最大 1 GB，不是运行内存上限；M1 已扩展同机 Trigger/.NET 点云链路并验证，不做连续流或跨机二进制传输；生产容量仍待批准 |
| 保存策略 | 默认不自动保留完整点云；文件原样、内存/派生平台无损保存，另提供显式 PLY/PCD/XYZ 交换导出；资产包独立限额数值待定；不能承诺未保存源的原精度复算 |
| 规则/资源升级 | M1 点云资源 v2、保存与固定发布引用已有实现；共享 limit-check.v2/Result Record 三态升级尚未实现，留 M3.4。同批验证执行身份及启动/切换/恢复准入；受影响旧发布只读、审核重发，不重建版本管理或本轮改数据 |
| 多格式与算法依赖 | 受控 PLY/PCD、NumPy XYZ 及 Open3D 几何的开发态双平台验证见 M1/M2 记录，包含完整样本、字段与精度。不自建原生扩展；生产原生峰值、完整离线依赖及双平台 bundled 发行未验收 |
| 三维测量交互 | M3.1 已补支持分类/残差、候选查询和测量结果联动；M3.2 已接边界/特征选择和有限拟合区间。精确量值须显式 Preview 重算，不新增常驻原云服务；未保存原云的历史结果不可重测 |
| 有序边界资源 | M3.2 已扩展原 CloudRuntime；有序源点保留最初行号，生成顶点单独记录源边/面及权重，同批更新保存/恢复与显示，不假造原始行号 |
| 容量与时间验收 | 最低 RAM、期望并发和单次时限未确定；预算公式已给出，默认值、库峰值与真实性能未验证 |
| 完整形状公差 | 标准适用条件、评价算法和收敛保证需要逐方法核定，不以名字代表合规 |
| 数据与标注一致性 | 原结果已发生粗/细算法版本变化；正式实现必须绑定方法、参数、证据版本 |

风险控制不能依赖一份 PLY 上“数值看起来正常”。必须用旋转、近竖直基准、缺特征、多解、短弧和资源中断等用例主动验证边界。

## 17. 参考资料与维护

外部资料用于算法和依赖核对，不是本项目运行时契约；本次整理查证日期为 2026-10-21：

- [Open3D 安装与平台支持](https://www.open3d.org/docs/release/getting_started.html)、[0.19 的 Python 3.12/NumPy 2 支持](https://www.open3d.org/news/open3d-v0-19-is-out-with-new-features-and-more-gpu-support/)、[点云算法](https://www.open3d.org/docs/release/tutorial/geometry/pointcloud.html)。
- [plyfile 格式与内存映射](https://python-plyfile.readthedocs.io/en/latest/usage.html)、[tifffile](https://pypi.org/project/tifffile/)。
- [Three.js PLYLoader](https://threejs.org/docs/pages/PLYLoader.html)。生产大数据查看不能仅凭存在 loader 就全量下载解析。
- [OCCT STEP](https://dev.opencascade.org/doc/overview/html/occt_user_guides__step.html)、[cadquery-ocp 分发](https://pypi.org/project/cadquery-ocp/7.9.3.1/)。
- [CloudCompare 标量显示](https://www.cloudcompare.org/doc/wiki/index.php?title=Entity_properties)。显示范围和颜色范围不同，不是算法数据筛选。
- CloudCompare 源码：[PLY 读取](https://github.com/CloudCompare/CloudCompare/blob/master/libs/qCC_io/src/PlyFilter.cpp)、[LOD](https://github.com/CloudCompare/CloudCompare/blob/master/libs/qCC_db/include/ccPointCloudLOD.h)、[LOD 生命周期](https://github.com/CloudCompare/CloudCompare/blob/master/libs/qCC_db/src/ccPointCloudLOD.cpp)、[主程序许可证说明](https://github.com/CloudCompare/CloudCompare/blob/master/README.md)。
- CCCoreLib 源码：[坐标容器](https://github.com/CloudCompare/CCCoreLib/blob/master/include/PointCloudTpl.h)、[索引子集](https://github.com/CloudCompare/CCCoreLib/blob/master/include/ReferenceCloud.h)、[空间索引](https://github.com/CloudCompare/CCCoreLib/blob/master/include/DgmOctree.h)、[局部几何](https://github.com/CloudCompare/CCCoreLib/blob/master/include/Neighbourhood.h)、[组件与许可证](https://github.com/CloudCompare/CCCoreLib/blob/master/README.md)。
- [CloudCompare 坐标平移与缩放](https://www.cloudcompare.org/doc/wiki/index.php/Global_Shift_and_Scale)。存储精度选择需要结合坐标范围，不能只看文件格式。
- [VM3D V2.2.0 官方手册](https://pinfo.hikrobotics.com/hkws/unzip/20240919112534_17943_doc/search.html)。第 7.3 节区分点云、点云扩展信息、包围盒等类型；模块目录不能证明未公开的内部内存实现。
- HALCON 24.11：[读取对象](https://www.mvtec.com/doc/halcon/2411/en/read_object_model_3d.html)、[准备派生数据](https://www.mvtec.com/doc/halcon/2411/en/prepare_object_model_3d.html)、[释放对象](https://www.mvtec.com/doc/halcon/2411/en/clear_object_model_3d.html)。只参考公开接口行为，不推断内部存储布局。
- [平行度](https://www.keyence.com/ss/products/measure-sys/gd-and-t/orientation-tolerance/parallelism.jsp)、[平面度](https://www.keyence.com/ss/products/measure-sys/gd-and-t/form-tolerance/flatness.jsp)。厂商教育资料不替代具体标准及现场验收。
- [NIST 过程能力](https://www.itl.nist.gov/div898/handbook/pmc/section1/pmc16.htm)。SPC 需要样本、稳定性与统计前提，单件 OK/NG 不是过程能力。

维护规则：阶段状态随实际交付更新，算法/契约变化同步测试；同一细节不再新增平行方案。待实现内容不写入当前能力手册。全部交付后，将稳定架构、格式、API、节点使用与验收分别归入既有专题，保留 ADR，合并并移除本实施基线中的过期计划；本地探索产物不作为正式运行依赖。
