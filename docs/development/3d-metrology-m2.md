# 3D Metrology M2 几何节点实施记录

更新：2026-10-23。依据[实施基线](3d-metrology.md)，承接 [M1 发布运行验收](3d-metrology-m1-published.md)。

## 已确认边界

- M2 实现 crop-roi、fit-plane、build-frame、transform-cloud，不重建 Workflow、发布、进程或点云所有权系统，生产节点仍不启用。
- M2 几何质量复用现有 `check_limits` 的逐项 `valid/passed/reason`，不将二态总摘要当产品判定。全平台 `limit-check.v2`、Result Record、PLC 及发布升级留在 M3.4；M2 不提前发布该格式，也不另写限值比较器。
- build-frame 支持显式锚点投影和三基准面交点两种原点。锚点模式的 X 来自显式方向或次基准面交线；三面模式主面确定 Z、次面确定 X、第三面只约束原点。方向必须明确，不用质心或单位矩阵补缺。
- 源精度、原始行号和原始总点数沿 M1；局部几何计算使用 float64，不对存储数据四舍五入。
- 已确认几何 support 直接复用现有只读 CloudReference 子集，不新增独立 indices 资源、registry 或 owner。
- crop-roi 来源为 `source.kind=parameters/input` 显式二选一；截面带依赖的有限 ROI 保存在 `source.bounds`。无覆盖优先级、自动补边界或兼容分支。

## 节点规格

| 节点 | 参数与输出 | 质量和失败 | 前端交互 |
| --- | --- | --- | --- |
| crop-roi | 带 frame/unit 的 box、cylinder、section-band；保留内部闭集；输出索引子集和计数 | 不匹配的坐标/单位拒绝；无效位置不得悄悄当外部点；合法空域为 ready 空云；缺测透传 | 同一参数草稿承载数值和三维控件，应用/取消分离；尺寸、坐标和方向可见 |
| fit-plane | 显式 feature_id、法向正方向、SVD 或 RANSAC 后 SVD 重拟合；显式质量规则 | 少点、共线、法向符号不可辨识及质量不足输出无效特征；坏输入/取消/超时不伪装缺测 | 基本区显示方法与法向，质量规则不得自动填数；显示支持、残差和无效原因 |
| build-frame | 主/次/第三面按稳定 ID 选取，两种显式原点模式；输出 pose 和 found | 缺特征、约束不足、平行、病态、方向歧义分别记录；无效时 transform=null | 模式选择决定必填项；按输入面 ID 选择，不取列表第一项；展示原点、轴与源/目标 |
| transform-cloud | 同 run/observation、source/target/unit 一致的 pose；输出新云 | 只接受 SE(3)，禁止缩放/镜像；位置变换、法向只旋转、其他属性保留；失败位姿输出 unavailable | 明确 target_from_source；相机操作不修改数据矩阵；缺测不显示上一次坐标 |

所有算法门槛、RANSAC 参数和允许误差均由显式配方配置；测试可以使用明确的独立配置，但不产生生产默认值。矩阵/单位向量的浮点合法性检查不是产品公差。几何结果、质量证据与显示数据必须核对同次 observation，禁止跨运行叠加。

## 复用与扩展

- 裁剪复用 `CloudRuntime.register_subset`、`CloudView.source_indices`、预算和 Scope；不复制全部属性，不另建 Broker。
- 变换复用 `register_derived` 和数组 owner；源数据保持只读。派生方法追溯需记录位姿身份及实际变换，不仅保存一个脱离语义的矩阵。
- 拟合复用 NumPy 线性代数及 Open3D 稳健平面候选，正式支持和质量在原精度点上核对；显示采样不参与拟合。
- 特征、ROI、位姿采用独立严格契约；仅实现并注册本阶段实际可执行的分支。
- 已补齐 M1 filter-valid / normalize-units 的 unavailable 分支；即使缺测，也先拒绝错 run 和已知单位冲突，不借用不存在的数组或生成假文件。
- 沿现有 Vue 参数控件、Preview 和 Three.js renderer 扩展，不新增应用入口、独立编辑器或第二套草稿状态。

## 验证顺序

1. 每节点先验证严格 schema、成功/失败/取消、资源归零，再接 handler/Catalog。
2. 独立解析真值覆盖旋转/竖直面、边界、外点、共线、基准交点、刚体逆变换、法向和标量字段；不得用被测算法生成真值。
3. 连续成功、失败、成功及错 run/observation/frame/unit 组合验证，不残留旧特征或位姿。
4. 前端覆盖应用/取消、任务与数据切换、晚返回、卸载及 renderer 释放；三维坐标只来自实际显示数据，不冒充原精度点拾取。
5. 完整既有 ASCII PLY 在 Windows 和 WSL Ubuntu 原生运行目录验证；样本未标定，只证明处理和一致性，不声称工业精度合格。
6. 真实节点组合沿现有发布/Runtime 机制用显式测试配置验收，节点仍隐藏；不重复 P99/长稳测试，不填写生产预算。

## 当前进度

**四节点和三维参数/结果交互已接通，生产仍不可发现、不可启用。** 内部包现有 10 个真实节点、6 个三维 payload 契约。工程验证与生产验收分别记录，不把完整样本跑通当工业计量精度证明。

| 部分 | 实现与实测 | 尚未完成 |
| --- | --- | --- |
| crop-roi | 有向盒、有限圆柱、有界截面带；闭边界、稳定索引、循环/错坐标拒绝；真实端口与 ROI 图形/数值草稿 | 现场配方和生产容量 |
| fit-plane | 分块中心化 QR/SVD；真实 Open3D 候选与正交重拟合；方法/质量编辑和显示 | 生产原生资源门禁、离线依赖及发行 profile |
| build-frame | 两种显式原点、多来源特征端口、基准稳定 ID、质量/方向编辑及坐标轴显示 | 现场基准与质量阈值 |
| transform-cloud | 同身份、SE(3)、法向旋转、标量保留、持久方法；位姿端口与源/目标显示 | 现场数值准确度验收 |
| M1 回归 | 文件读写、资源 v2、六节点执行、Preview、不可启用边界通过 | 生产参数仍待批准 |

### 算法与审计记录

- 核心计算分别在包内 `shared/crop_roi.py`、`fit_plane.py`、`build_frame.py`、`transform_cloud.py`，未修改 Workflow 执行器、App 发布、Trigger/SDK、进程管理或训练/推理链路。
- SVD 使用局部 float64，分块中心化 QR 避免对大偏移坐标直接累积平方矩阵；最后对三列 R 做 SVD。输出点字段仍保持源 dtype。
- 平面质量要求配方明确支持点数、切向跨度比、法向分离、RMS 和最大残差。建坐标要求轴夹角正弦、X/Z 方向对齐下限；三面模式另要求条件数上限。代码不填写这些生产数值。
- 质量计算只调用现有 `check_limits`。内部结果保存逐项 `valid/passed/reason`；校验指标正文、规则身份及参数一致性。`usable` 不是产品 OK/NG。
- 稳健分支只复用 Open3D 候选支持点，再进行本项目正交重拟合。Open3D 0.20.0 的候选末次拟合并不是该正交 SVD 路径，不能直接用其返回平面作为本节点最终几何。源码见 [SegmentPlane](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/open3d/geometry/PointCloudSegmentation.cpp) 与 [Python 绑定](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/pybind/geometry/pointcloud.cpp)。
- 复核修正 RANSAC 工作对象估算：TBB 候选各自收集内点索引，不能只计一份；当前按所有候选可能并存及目标平台 vector 扩容计入准入检查。不设置全局 RNG、不新增任务队列。该估算不包含线程栈、分配器等全部 RSS，不能解释为进程硬内存限制；原生峰值仍待实测。
- 三面线性相关、方向歧义或质量失败不交付旧矩阵。缺测变换只产生目标 frame 的 unavailable 声明，不分配数组。
- 原生候选入口的中心化与 SVD 路径一致，有限坐标相减溢出明确抛错，禁止将 Inf 送入 Open3D；回归确认不新增保留数组。该检查不改变正常值计算、产品公差或源 dtype。
- 变换保留原始 PCD 的源视点追溯，不把旧视点伪装成新坐标视点。既有导出规则对不一致的源空间仍拒绝；本批未新增视点换算能力。
- 刚体矩阵/单位向量的结构容差沿既有二维刚体契约的 `1e-8` 量级；不是位置误差预算、图纸公差或扩大 ROI 的 epsilon。

### 公开契约与接入边界

DTO 覆盖 ROI 联合类型、几何质量、平面观测、位姿和刚体矩阵，拒绝额外字段、非有限值、镜像、尺度及身份错配。本批收口结果：

1. support 已确认沿用只读 CloudReference 子集，保留最初行号及原始总数，不建第二个 owner/registry。Features 增加显式 run_id，与全部支持一致；Pose 的支持顺序与主/次/第三基准对应。
2. method 的 parameters、parameters_sha256、quality_policy 独立且严格；参数摘要只覆盖正文，配置仍用原参数模型校验，不复制另一套规则。删除旧平铺字段，不保留过渡解析。
3. transform3d.v1 使用 matrix（列向量 target_from_source）。provenance 保存 FrameBuildMethod、完整质量与实际 PlaneEvidence；后者包含原平面、方法、质量及支持内容身份。不携运行访问引用，source_retained=false 不声称已保存源数组。Pose 本身仍为本次运行观测，不能直接当历史访问凭据。
4. 几何消费者通过已有 check_limits 复核完整逐项结果。计数、比例、残差、单位和策略交叉验证；不能同时改数值和 passed 字段绕过比较器。
5. 审计补齐随机支持身份：RANSAC 同参数、同点数可能选出不同子集，PlaneSupportMethod 记录实际父逻辑索引的 LE 字节摘要；不新增索引对象。空支持摘要为 SHA256(empty)，退化仍输出无效特征。实际原始行号读取未改变。
6. crop 的 ROI 参数/输入选择、build-frame 多来源端口、found:boolean.v1 和同观测显示附件已接入。未改 Workflow 通用 value.v1 参数绑定机制。

### 上批算法与原生验证（2026-10-22）

上一批非原生组合回归为 Windows/WSL 各 227 项。本批扩充公开契约和原生用例，最终组合回归为 Windows 361 项、WSL 361 项，另有每平台两个完整样本用例。WSL 同一命令合计 363 项通过；Windows 组合与完整样本分开执行。

组合范围：`test_metrology3d_{crop,plane,frame,transform,public_contracts,preprocess,preview,activation_boundary}.py`、`test_point_cloud_{contracts,runtime,assets}.py`，受控 PLY/PCD 读写，以及 `integration/metrology3d` 的 file_read、asset_export、geometry_assets、nodes、geometry_native、geometry_native_process。包含 M1 六节点真实 GraphExecutor、派生变换保存/关闭/恢复/导出和生产隐藏边界；不包含尚未接入的 M2 四节点 Workflow 或前端交互。

原生单独复验命令（先使用核定依赖的测试 Python；Ubuntu 数据目录必须在原生文件系统）：

```text
python -m pytest -q tests/integration/metrology3d/test_geometry_native.py tests/integration/metrology3d/test_geometry_native_process.py --basetemp=<native-test-directory>
python -m pytest -q -s tests/integration/metrology3d/test_geometry_full_sample.py --cloud-sample=<sample.ply> --basetemp=<native-full-directory>
```

本批短资源观测：Windows 20 次调用 RSS 从 117,628,928 到 118,886,400 字节（后者也是最大值），线程从 32 到 45；Ubuntu 从 258,736,128 到 258,895,872 字节，线程从 33 到 40。每次 Scope 归零、结束后进程归属为空。线程增长与这些短记录本身不足以证明泄漏或长期稳定；没有套用旧 P99/长稳门禁，也没有修改线程池或等待策略。

再次审计：canonical JSON 仅移动到无环的基础契约模块，序列化规则未变；几何方法与质量拆分不反向依赖服务层；算法只复用既有 check_limits、CloudRuntime 和进程监督器。未改训练、推理、模型网络或部署准入。新增索引摘要对已有连续缓冲计算，不复制全量点数据；新增质量复核在有界规则上执行。Ruff 与 diff whitespace 检查通过。过程中新增摘要的空数组 cast 错误已由组合测试发现并修复，退化及空支持回归已通过；不能用早先失败批次代替最终结果。

完整样本单独使用 `tests/integration/metrology3d/test_geometry_full_sample.py`：

- 原文件 479,677,235 字节，14,745,099 点，SHA256 `ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b`。
- float32 位置数组摘要 `956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6`，未转为整云 float64。
- 两平台全量读取、有效点过滤、包围盒闭集裁剪、SVD、锚点坐标及刚体变换通过。全部 14,745,099 点保留；逐块核对原始行号、dtype 与逆变换误差界。
- 最终样本处理观测：Windows SVD 27.813 秒、RANSAC-SVD 28.812 秒；Ubuntu SVD 16.622 秒、RANSAC-SVD 18.660 秒。不是受控性能门禁或跨平台性能结论。结束前数组计费分别为 471,843,168 / 530,823,564 字节，Scope 关闭后归零。
- Ubuntu 对象存储、数据库及测试临时文件均位于原生文件系统；源码和原样本仍在 Windows 挂载盘。
- 样本无可追溯尺寸标定，显式测试 mm/右手及质量阈值仅用于链路验证，不证明工业计量精度。
- 派生变换的资源 v2 保存、关闭原运行、恢复新运行、PCD 导出及 uint64/法向保真另有回归；原始运行引用不获得新运行访问权限。

### 原生依赖与验收

两平台 Open3D 0.20.0 wheel 已按[基线](3d-metrology.md)中的官方 SHA256 核对并在隔离环境安装。下载使用镜像仅改变传输来源，不改变发行身份；wheel 保存在忽略版本控制的 `runtimes/third_party/python-geometry/`。没有修改主开发 Python 或加入原生算法降级。

Ubuntu 24.04 原生导入最初因 libusb-1.0.so.0 缺失失败，ldd 未检出其他缺失库。验收将官方 libusb-1.0-0 2:1.0.27-1 解压到本轮原生测试目录，只为子进程设置 LD_LIBRARY_PATH，没有系统安装。正式发行必须列明系统依赖，并在目标镜像及 bundled Python 重验，当前不能宣称发布依赖闭环。

- 原生解析真值包含竖直面、倾斜面、float32/64、明确外点、共线/重合退化；候选后仍使用项目的正交重拟合，不用上游返回平面替代。
- 重复与并发使用各自 Scope，不设置 Open3D 全局随机种子、不增加等待队列。取消检查覆盖原生前后和重拟合；原生长调用的中止使用既有 ProcessTreeSupervisor/OwnershipScope，超时和取消后确认整组为空。
- 短重复资源测试为单进程 20 次原生调用，记录 RSS/线程及每次 Scope 数组归零，不自拟未批准的资源门禁，也不当作长期稳定结论。
- 同一 14,745,099 点完整样本的 SVD 与原生 RANSAC 两路径在 Windows/Ubuntu 通过；数据、索引、dtype、逆变换与释放均核对。RANSAC 全样本门槛显式取包围盒对角线，仅验证全量处理/容量，不证明离群点剔除能力或工业公差。外点能力由独立解析真值测试证明。
- 完整样本原生测试工作预算显式设为 32 GiB 以容纳保守候选估算，非生产默认也不是实测 RSS。数组计费 SVD 为 471,843,168 字节，原生路径为 530,823,564 字节，关闭后均为零。原生峰值 RSS 和目标硬件生产容量仍需批准预算后验收。

### 本批节点与界面接线（2026-10-23）

- `backend/geometry_handlers.py` 只做 DTO/端口解析并调用现有四个算法。`settings` 将平面或基准参数原子提交，不新增计算器。`build-frame.features` 使用执行器既有 multiple 端口；`transform-cloud` 只接 pose，没有第二套手填矩阵。
- `cloud-preview` 增加可选多来源 features 和 pose；输出新增显式 `amvision.geometry-preview.v1` 附件，核对同观测、坐标、单位与质量。附件只保留数值、平面支持边界及坐标矩阵，不携运行点云访问引用。支持边界是显示范围，不是表面拓扑或真实轮廓。超过原有显示预算时返回 unavailable，不影响保存/导出。
- ROI 使用同一草稿的数值字段与 Three.js TransformControls；应用提交，取消丢弃。截面带绘制受有限边界裁剪的显示几何。相机操作不修改配方，浏览器不参与拟合。只从当前成功预览中显式选择显示来源，运行切换清除选择。
- 输入端口模式缺少 ROI 连线时，沿既有配方预检提示并阻止保存/发布；参数模式拒绝冲突连线。有限边界拖动结束后按最新草稿刷新依赖截面，延迟刷新在卸载后不再分配资源；刷新异常沿原有 renderer 关闭路径处理。
- 几何方法编辑复用已有限值规则编辑器，标题为几何质量；阈值保持空白，不套产品 OK/NG。主/次/第三面按已连接节点的稳定 ID 提示，动态输入仍由运行契约校验。其他节点未完成只提示，不能使当前节点无法应用；保存/发布继续统一拒绝已知配方错误。
- 视口/几何缓冲沿原有 CPU/GPU 总预算计量，更新、超限、上下文丢失、卸载统一释放。三维模块延迟加载，未选择点云显示时不创建 renderer。生产 manifest 仍不存在，不增加入口、后台进程或队列。
- 修复既有 read/export 资产来源分支：执行器填入的未连接端口 `None` 不再被当作冲突输入，真实非空冲突仍拒绝。

本批验证：

- Windows 与 WSL Ubuntu 原生目录组合各 **372 项通过**；包含受控 I/O、M1 资源与六节点、M2 契约/算法/四节点、多来源三面原点、成功/失败/成功、原生取消及整组回收。
- 同一完整样本经真实 GraphExecutor 执行四节点和 cloud-preview，两平台分别 **2 项通过**（SVD/RANSAC-SVD）。14,745,099 点逐行 dtype/原始索引/逆变换核验，有界显示 10,000 点；Scope 关闭后数组计费归零。Windows 28.906/30.562 秒，Ubuntu 18.752/27.442 秒，仅过程记录，不作性能门禁。
- Windows 与 WSL Ubuntu 正式 REST 发布 → 依赖准入 → 独立 WorkflowAppRuntime worker → 同机 Trigger → 四节点 → 返回坐标/释放，每平台 **1 项通过**。使用隔离测试包和显式测试配置，不替换 loader、准入或 handler。Ubuntu 最后同时复核四节点 4 项，共 5 项通过；为加载现有 API 路由补齐的依赖仅安装到隔离环境，未修改系统库或主开发环境。
- 前端六组专项回归 **33 项通过**；随后扩大至 Workflow 相关 **18 组、112 项通过**，覆盖原子草稿/取消、任务切换、预览失效、晚返回、卸载、输入接线、非法 ROI、有限截面及拖动依赖刷新、几何缓冲归零。最终 Vue 类型检查和生产构建通过；Three.js chunk 仍有大于 500 kB 的构建提示，未放宽告警阈值。变更 Python 的 Ruff 与 `git diff --check` 通过。
- 实际浏览器使用隔离验收页，加载正式 Vue 组件和完整样本的实际有界显示；该页面不冒充完整 Workflow 编辑页验收。桌面和 390×844 视口无空白/页面横向溢出；像素检查分别 22,625/13,124 个非透明像素。拖动 ROI 修改同一中心字段，取消不改原配置，关闭后 CPU/GPU 计量均为零。用户原 Workflow 未保存草稿未操作。

### 下一步

下一步顺序：

1. 生产超时/容量确认、完整离线依赖锁定及 bundled profile 验收仍单独完成；节点继续隐藏。
2. 现场确认具体基准、单位和质量规则后，以有可追溯真值的工件检验测量准确度；未标定样本不能代替。
3. 节点正式启用前完成目标发行包中的 Workflow 编辑/发布/运行页面验收；本批组件验收不代表现场发行环境。
4. 之后沿基线进入 M3 尺寸节点，三态和消费者留在 M3.4；不重复实现 Workflow、发布、Broker，也不重复 P99/长稳。

### 上批清理（2026-10-22）

本轮未启动 API、worker、Vite 或独立后台服务；已有用户开发服务和浏览器未保存草稿未改动。pytest、下载及安装进程均已退出；Windows/WSL 按本轮解释器命令行核查无残留，测试中的 OwnershipScope 也确认整组为空。删除前核验绝对路径，仓库 `.tmp/` 已清空，WSL `/home/am/.cache/amvision-m2-verify` 已删除，包括隔离 venv、临时 libusb、测试存储和缓存。原始样本未改动，系统 Python/系统库未修改；已校验的 Windows/Linux wheel 保留在忽略版本控制的依赖资产目录，不从 `.tmp` 交付。没有清理非本轮系统缓存或其他项目数据。

### 本批清理（2026-10-23）

本批隔离 UI 验收服务（5617）已停止，检查无监听；Windows 与 WSL 本轮 pytest、原生算法和发布运行 worker 无残留。删除前确认专用路径及进程状态，仓库 `.tmp/` 已清空，WSL `/home/am/.cache/amvision-m2-nodes` 已删除，包含隔离 venv、临时 libusb、测试数据库/存储及有界显示文件。正式前端构建产物和已校验依赖 wheel 不作为测试垃圾删除。没有修改原始 PLY 样本或系统库，没有清理其他项目及系统通用缓存。

实际验收页已关闭，浏览器视口覆盖已恢复。原有用户 5600/5601 服务、worker、inference daemon 和未保存 Workflow 草稿未主动停止或操作；本次“测试环境清理”不表示用户开发服务全部关闭。未执行 P99、长稳或 Git 提交。
