# 3D Metrology M2 几何节点实施记录

日期：2026-10-22。依据[实施基线](3d-metrology.md)，承接 [M1 发布运行验收](3d-metrology-m1-published.md)。

## 已确认边界

- M2 实现 crop-roi、fit-plane、build-frame、transform-cloud，不重建 Workflow、发布、进程或点云所有权系统，生产节点仍不启用。
- M2 几何质量复用现有 `check_limits` 的逐项 `valid/passed/reason`，不将二态总摘要当产品判定。全平台 `limit-check.v2`、Result Record、PLC 及发布升级留在 M3.4；M2 不提前发布该格式，也不另写限值比较器。
- build-frame 支持显式锚点投影和三基准面交点两种原点。锚点模式的 X 来自显式方向或次基准面交线；三面模式主面确定 Z、次面确定 X、第三面只约束原点。方向必须明确，不用质心或单位矩阵补缺。
- 源精度、原始行号和原始总点数沿 M1；局部几何计算使用 float64，不对存储数据四舍五入。

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

**M2 未完成，四节点未接入 Catalog/handler，生产仍不可发现、不可启用。** 当前是内部算法及回归批次，不是前端或完整节点交付。

| 部分 | 实现与实测 | 尚未完成 |
| --- | --- | --- |
| crop-roi | 有向盒、有限圆柱、有界截面带；闭边界、稳定索引、循环/错坐标拒绝；Windows/Ubuntu 解析真值通过 | 节点端口及 ROI 图形/数值草稿编辑 |
| fit-plane | 全支持点分块中心化 QR 后 SVD，残差全量计算；方向、质量和退化回归通过；RANSAC 候选适配代码已写 | Open3D 原生集成、原生 RSS 验收、节点及界面 |
| build-frame | 两种显式原点、基准 ID/顺序、方向、三面退化和质量不足通过 | 公开嵌套输出契约对齐、节点及选择/显示交互 |
| transform-cloud | 同 run/observation/frame/unit、SE(3)、法向旋转、标量精确保留、缺测和取消回收通过 | 公开方法追溯契约对齐、节点及三维结果交互 |
| M1 回归 | 文件读写、资源 v2、六节点执行、Preview、不可启用边界通过 | 不代表 M2 四节点已进入发布执行链路 |

### 算法与审计记录

- 核心计算分别在包内 `shared/crop_roi.py`、`fit_plane.py`、`build_frame.py`、`transform_cloud.py`，未修改 Workflow 执行器、App 发布、Trigger/SDK、进程管理或训练/推理链路。
- SVD 使用局部 float64，分块中心化 QR 避免对大偏移坐标直接累积平方矩阵；最后对三列 R 做 SVD。输出点字段仍保持源 dtype。
- 平面质量要求配方明确支持点数、切向跨度比、法向分离、RMS 和最大残差。建坐标要求轴夹角正弦、X/Z 方向对齐下限；三面模式另要求条件数上限。代码不填写这些生产数值。
- 质量计算只调用现有 `check_limits`。内部结果保存逐项 `valid/passed/reason`；校验指标正文、规则身份及参数一致性。`usable` 不是产品 OK/NG。
- 稳健分支只复用 Open3D 候选支持点，再进行本项目正交重拟合。Open3D 0.20.0 的候选末次拟合并不是该正交 SVD 路径，不能直接用其返回平面作为本节点最终几何。源码见 [SegmentPlane](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/open3d/geometry/PointCloudSegmentation.cpp) 与 [Python 绑定](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/pybind/geometry/pointcloud.cpp)。
- 复核修正 RANSAC 工作对象估算：TBB 候选各自收集内点索引，不能只计一份；当前按所有候选可能并存及目标平台 vector 扩容计入准入检查。不设置全局 RNG、不新增任务队列。该估算不包含线程栈、分配器等全部 RSS，不能解释为进程硬内存限制；原生峰值仍待实测。
- 三面线性相关、方向歧义或质量失败不交付旧矩阵。缺测变换只产生目标 frame 的 unavailable 声明，不分配数组。
- 变换保留原始 PCD 的源视点追溯，不把旧视点伪装成新坐标视点。既有导出规则对不一致的源空间仍拒绝；本批未新增视点换算能力。
- 刚体矩阵/单位向量的结构容差沿既有二维刚体契约的 `1e-8` 量级；不是位置误差预算、图纸公差或扩大 ROI 的 epsilon。

### 内部契约与公开接入缺口

内部 DTO 已覆盖 ROI 联合类型、几何质量、平面观测、位姿和刚体矩阵，并拒绝额外字段、非有限值、镜像、尺度及身份错配。以下仍须在注册公开节点前处理，不能宣称 M0 的逐字段公开契约已经全部落地：

1. M0 的 `support.indices` 与 M1 实际 `CloudRuntime.register_subset` 重叠。本批内部支持点使用既有只读点云子集，保留最初行号及原始总数，不建第二个 owner/registry。已请求确认此复用方式，确认前不冻结公开 support 形状。
2. 公开输出的嵌套 `method/quality_policy/provenance` 及独立 `transform3d.v1` 外壳须与基线逐字段对齐；当前内部位姿/特征的平铺方法字段不直接作为已发布 API。
3. 变换方法内部已保存 `pose_id`、完整位姿结果摘要和实际 `target_from_source` 矩阵；公开父身份表示和持久追溯要随上项一并核对，不能用摘要声称完整上游证据已持久保存。
4. crop 的 ROI 参数/输入绑定、build-frame 的多来源特征端口、`found:boolean.v1` 及同观测显示附件尚未接入。不得以内部函数测试代替这些接线验收。

### 实际验证

最终组合回归：Windows **227 项通过**；WSL Ubuntu **227 项通过**。覆盖新几何契约/算法、M1 预处理、运行引用、显示、资产、严格文件读写、六节点执行和隐藏目录边界；不含尚未执行的 Open3D 原生用例。

完整样本单独使用 `tests/integration/metrology3d/test_geometry_full_sample.py`：

- 原文件 479,677,235 字节，14,745,099 点，SHA256 `ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b`。
- float32 位置数组摘要 `956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6`，未转为整云 float64。
- 两平台全量读取、有效点过滤、包围盒闭集裁剪、SVD、锚点坐标及刚体变换通过。全部 14,745,099 点保留；逐块核对原始行号、dtype 与逆变换误差界。
- Windows 本次处理观测 27.578 秒，Ubuntu 17.684 秒；不是受控性能门禁或跨平台性能结论。结束前数组计费 471,843,168 字节，Scope 关闭后归零。
- Ubuntu 对象存储、数据库及测试临时文件均位于原生文件系统；源码和原样本仍在 Windows 挂载盘。
- 样本无可追溯尺寸标定，显式测试 mm/右手及质量阈值仅用于链路验证，不证明工业计量精度。
- 派生变换的资源 v2 保存、关闭原运行、恢复新运行、PCD 导出及 uint64/法向保真另有回归；原始运行引用不获得新运行访问权限。

### 原生依赖阻塞及下一步

Windows Open3D 0.20.0 wheel 已从官方 PyPI 下载并核对 SHA256 `60010f21d44f13557ba007893bc13a69827faa4dc49eedd923d1397096c20d92`。本轮安装其配套依赖时下载仍低速，已停止；Ubuntu 的 400.8 MB wheel 仅下载约 8 MB，pip 显示预计数小时，已停止。**两平台原生 RANSAC 尚未实测，不计通过，不提供其他算法降级。** 已校验的 Windows wheel 作为忽略版本控制的依赖资产保存到 `runtimes/third_party/python-geometry/`，不从 `.tmp` 交付。

下一步顺序：

1. 确认 support 复用表示，按 M0 完成公开嵌套契约对齐，不新增索引传输/所有权系统。
2. 准备 Open3D 0.20.0 两平台离线 wheel 及配套依赖，执行 `tests/integration/metrology3d/test_geometry_native.py`。该套件缺依赖明确失败，不使用 skip 或替代库。
3. 补原生外点、退化、重复/并发调用、RSS 与既有 worker 取消/timeout 回收证据。生产超时与预算仍待确认，测试只用显式配置。
4. 通过后依次接入四个真实 handler/Catalog 与正式端口，测试失败传播和保存/导出支路。
5. 沿现有 Vue 参数编辑器及 CloudViewer/Three.js 实现 ROI 应用/取消、基准选择、平面/轴叠加和结果方向；补晚返回、数据切换、卸载、显存与监听器释放及浏览器截图验证。
6. 最后执行四节点实际 Workflow 组合及双平台完整样本验收。生产节点仍不启用，不重复 P99 或长稳测试。

### 本轮清理

本轮未启动 API、worker、Vite 或独立后台服务；已有用户开发服务未停止。所有本轮 pytest、下载及安装进程已退出。仓库 `.tmp/` 和 WSL `/home/am/.cache/amvision-m2` 已清空/删除，原始样本未改动。已逐项核对的三个系统临时下载目录已删除；其余系统 Temp 下 pip 元数据目录无法仅按时间证明归属，批量清理被安全检查拒绝，未删除。已校验的官方 Windows wheel 保留为忽略版本控制的依赖资产，而非测试临时文件。
