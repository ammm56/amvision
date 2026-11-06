# B06 标定栅格输入与点云来源

## 1. 实施范围

2026-11-05，代码基点 `91a41fab`。B06 已实现严格标量文件/同机数组读取、两类标定模型、完整像素点云转换、现有 CloudRuntime 登记、过滤后的原始行号、原件与派生资产保存/重读、单资源包空环境导入。复用 ObjectStore、LocalBuffer reader guard、CloudArrayBudget、ResourceScope 和计量资源服务，没有第二套资源或生命周期系统。

**B06 公开节点、Trigger/Python/Windows .NET、参数工作区和真实发布已接通；当前源码包为 0.1.29、25 节点。** 新增 Raster to Cloud，复用原有 Filter Valid、Cloud Preview、保存读取、发布版本和独立 Runtime。既有工件 111 节点、317 条边、50 项测量、质量条件和生产预算不变；新节点没有自动插入原工件配方。第 5 节是前批内核证据，第 6 节是本批公开接线与页面验收，不能混为一次测试。

**后续审计发现的跨代来源缺陷已修复。** 原件/数组块曾共同命中“资产重读 → 过滤 → 再次保存 → 重读”丢失标定的问题；历史 37 通过/2 失败是修复前复现。现在资产登记和保存复用原始观测边界，同次摘要也不再重复扫描，输入载荷限额与解码内存预算分别约束。Windows/WSL 合并回归各 309 项（含 B07 输入和启用边界）；真实发布 Windows 7 项、WSL 6 项通过/1 项平台跳过，第三代资产 Windows 像素拾取已验，专用 A10 包空环境存读已覆盖。完整修复边界与各平台新证据见[审计记录第 6 节](3d-metrology-b06-review.md#6-来源修复与同次摘要复用)。工作区未自动提交，不扩大为未覆盖容量或实采精度的声明。

## 2. 已确认的测量定义

| 项目 | 固定规则 |
| --- | --- |
| 输入方式 | 每次完整输入；文件或同机二进制数组；原始载荷最多 1,000,000,000 字节 |
| 针孔深度 | 已去畸变、零 skew；明确选择轴向 Z 或沿射线距离；不估计内参、不猜畸变模型 |
| 正交高度 | 明确零行零列的零高原点、行列间距、行列与高度三个正交单位方向 |
| 标定追溯 | `calibration_id`、`calibration_revision` 和完整参数正文一起保存；标签不授予资源访问权限 |
| 标定来源 | 文件模式由节点 settings.raster 提供；同机数组由 PREPARE 中的完整 descriptor 固定，节点参数仅为 kind=local-array，不允许覆盖标定 |
| 像素身份 | `row * width + column`，行优先；`source_point_count = width * height` |
| 无效数据 | 原标量保持类型和值，`validity=0`，位置为 NaN；之后由已有 Filter Valid 显式剔除 |
| 输出精度 | `position_dtype` 显式指定 float32/float64；块内使用 float64 计算；原标量不降精度 |
| 外参 | 后续连接已有 Build Frame/Transform Cloud，不在读取器内重复实现位姿求解或变换编排 |

像素中心使用整数列/行坐标，不隐式加半像素。物理值 `h = raw * value_scale + value_offset`。针孔射线 `q = ((column-cx)/fx, (row-cy)/fy, 1)`：轴向模式为 `p=h*q`，射线距离模式为 `p=h*q/||q||`。输出相机坐标 X 向右、Y 向下、Z 向前。正交模式为 `p=origin+column*column_step*column_direction+row*row_step*row_direction+h*height_direction`。

原始哨兵先于尺度转换判断，且必须能由原 dtype 精确表达。物理范围为包含边界的显式 minimum/maximum，均可明确填写 null 表示不施加该侧范围。针孔有效深度必须严格为正；正交高度允许零和负值。缺失单位、非正焦距、非正步距、未知投影、非正交方向、尺度溢出和坐标存储溢出拒绝，不修正参数或降级。

## 3. 字段与文件范围

输入契约见 [raster3d.py](../../backend/contracts/workflows/raster3d.py)。二进制 `amvision.raster-buffer.v1` 使用 little-endian、连续 HW 标量，可紧随同尺寸 uint8 的 0/1 mask；没有行 padding 或额外尾字节。布局和完整标定共同参与 descriptor SHA256。普通 uint8 图片传输没有承担物理深度入口。

| 输入格式 | 当前接受类型与约束 |
| --- | --- |
| NPY 1.0/2.0 | uint8/uint16/int16/uint32/int32/float32/float64；二维标量；C/F 顺序及大小端规范化；拒绝 object、结构字段、缺字节和尾部数据 |
| PNG | 单通道 uint8/uint16；检查头部、CRC 和完整解码；拒绝彩色、调色板和隐式灰度转换 |
| TIFF | 单页 uint8/uint16/int16/int32/float32；无损压缩 1/5/8/32946/32773；BlackIsZero、原方向；拒绝多页、额外通道、SubIFD、损坏块和有损压缩 |
| 同机数组 | 与 NPY 相同的七种 dtype；可选原始 mask；实际字节长度必须与描述一致 |

TIFF float64/uint32 不在本批已核定的 Pillow 类型矩阵内，明确拒绝，不改成 float32 或 int32；这些精度仍可通过 NPY/数组输入。未引入新生产依赖或自写解析器，NPY 使用 NumPy 2.4.4，PNG/TIFF 使用 Pillow 12.2.0。OpenCV 只在测试中作为独立写出器，不作为坏文件解码失败后的备用路径。

输出字段为 `positions`、原 dtype 的 `raw_samples`、uint8 `validity`、uint8 `sample_status`，有输入 mask 时还保留 `input_mask`。状态按顺序互斥归类：0 有效、1 非有限原值、2 mask 屏蔽、3 原始哨兵、4 超出物理范围、5 非正针孔深度。所有原像素均占位，不补洞、不先过滤或重新编号。

## 4. 所有权与保存

文件准入与旧 PLY/PCD/XYZ 共用 [file_snapshot.py](../../custom_nodes/metrology3d_nodes/shared/io/file_snapshot.py)：项目权限、不可变版本、完整字节长度和 SHA256 检查后，在同一快照解码。没有新增文件缓存或用户系统路径入口。

同机数组沿已有 reader guard 只读借用，先校验摘要、长度、布局和容量。转换输出使用已有 OwnedCloudArrays 与 Scope；转换完成后输入借用结束，输出不再依赖原 mmap。guard 关闭失败保留容量占用并抛出错误，不假报回收成功；取消保留取消语义，不翻译成坏文件。

分配前计入输入解码与输出字段。Pillow int16 TIFF 使用 int32 解码，因此预算计入原生图、数组桥接、规范化副本和可能的压缩文件副本；这不是进程 RSS 的完整上限。投影计算分块，已有原生解码调用仍需要节点进程 timeout/整组停止处理强制中断，本批没有独立实现新的中断器。1 GB 输入并不代表 1 GB 活跃数组足够，未自动修改工作站策略。

| 保存情形 | 实际表达 |
| --- | --- |
| 文件原件 | 点云资产的 `raster-original` 表达，原文件字节、完整标定、无效规则、输出字段和摘要一起保存 |
| 数组原件 | 复用 `array-blocks`，保存原标量、mask、计算坐标、状态和标定来源 |
| 过滤/派生 | 复用既有索引/父来源，保存最初像素行号及完整原始网格总数；不将子集长度当原始像素数。重读资产再次派生保存的标定来源缺陷尚待修复 |
| 重读 | 生成当前 run 的新引用；旧 run/cloud ID 和被修改的标定正文不能取得访问权 |
| 搬运 | 既有单资源 ZIP 和 A10 专用配方资源包空环境恢复已覆盖；含多代依赖闭包与原始标定，不扩大为最大容量包验证 |

全部三维格式仍为开发期 v1。不增加旧格式读取或猜测式兼容逻辑，既有用户资产未删除。

## 5. 前批内核验证与审计

Windows 最终受影响组合 **277 项通过**，包括 B06、原点云契约/Runtime/资产、预处理、启用边界、旧 PLY/PCD 文件和交换导出。WSL Ubuntu 原生目录的 B06/Runtime/资产/契约/预处理组合 **200 项通过**。两者都包含文件/真实 mmap 的异常 traceback 持有回归，不将前序阶段通过数重复累加。Ruff 与 `git diff --check` 通过。Windows OpenCV 测试写出器的旧 Deflate 标记警告及损坏压缩数据用例的 libtiff 错误日志是显式测试输入，不是生产路径备用解码成功。

独立真值覆盖轴向与射线深度、倾斜正交网格、负/零高度、全部原 dtype、大小端与行列顺序、NaN 位模式和负零、哨兵与范围优先级。文件覆盖截断、维度/精度不符、对象 NPY、CRC、损坏 TIFF 元数据及压缩正文、多页/方向/通道错误。所有权覆盖真实 mmap 回收阻止、旧引用拒绝、描述摘要不符、预算拒绝、取消、消费方异常和 guard 关闭失败。

Windows 完整现有 PLY 的既有 SVD 几何链路通过：14,745,099 点、输入 SHA256 和 float32 XYZ SHA256 与冻结值完全一致，读取/过滤/几何/回收通过。本次诊断整条测试 35.047 秒，包含文件链路及独立几何验证，**不是正式 50 项工件图十秒计时**。该 PLY 也不是带标定的深度/高度网格，不能冒充 B06 实采输入验证。WSL 本批覆盖标量文件、真实 mmap 与资产链路，没有重复安装 Open3D 做原 PLY 全链。

本批没有启动 API、worker、Vite 或浏览器验收服务，没有改业务 5600/5601、显示缩放、GPU 配置。Ubuntu 依赖只安装于本轮原生隔离目录；清理对象是本轮测试目录，不是原工件或业务数据。生产依赖未新增；未自动 Git 提交。

收尾已核对本轮 Windows/Ubuntu 测试进程退出，仓库 `.tmp/` 为空；Ubuntu 隔离解释器、依赖、文件、mmap 和缓存目录已删除，Ubuntu 恢复本轮开始前的停止状态，其他 WSL 发行版未停止。移除仅转发字段定义的冗余函数后，29 项转换内核回归再通过，未重复计算为新增覆盖。

复验使用现有开发环境：

```powershell
conda activate amvision
python -m pytest tests/test_metrology3d_raster_conversion.py tests/test_metrology3d_raster_io.py tests/test_metrology3d_raster_buffer.py tests/test_metrology3d_raster_runtime.py tests/test_point_cloud_runtime.py tests/test_point_cloud_assets.py tests/test_point_cloud_contracts.py tests/test_metrology3d_preprocess.py tests/test_metrology3d_activation_boundary.py tests/integration/metrology3d/test_file_read.py tests/integration/metrology3d/test_asset_export.py -q -s --basetemp=.tmp/b06-check
```

Ubuntu 本批使用相同源码与 NumPy 2.4.4、Pillow 12.2.0、Pydantic 2.13.4；上述命令末尾的启用边界、旧格式集成两组未在该最小隔离环境运行，运行目录改为 Ubuntu 原生文件系统。该环境不是新离线发行包。

## 6. 本批公开接线与真实验收

### 6.1 入口、调用和所有权

`custom.metrology3d.raster-to-cloud` 两种 settings 是严格的判别联合，拒绝另一模式的残留字段：

| 模式 | 端口与参数 | 调用边界 |
| --- | --- | --- |
| file | file 输入 file-ref.v1；settings 包含 file_format 和完整 raster | 复用 HTTP 上传/Preview/Runtime multipart 和不可变文件引用；不允许同时连接 raster |
| local-array | raster 输入 calibrated-raster.v1；settings 只包含 kind | 仅同机共享内存；PREPARE 固定布局、标定和输入键；不允许同时连接 file |

服务端先核验发布 binding、descriptor、字节数和容量，再沿已有 LocalBuffer 分配。`amvision.workflow-trigger-raster-prepare.v1` 与 `amvision.workflow-trigger-raster-input.v1` 是新增类型，不改变 mailbox ABI，不新增队列/资源系统。REQUEST 禁止再次填入 PREPARE 的同名输入；本批回归补齐了该拒绝条件。私有 handoff 与当前 Run 绑定，普通 JSON 不能伪造 owner。读取后只读借用结束，输出由原 Scope 负责释放；取消、异常和客户端退出均走现有回收。

Python `PointCloudClient.invoke_raster` 与命令行 `--input-kind raster`，Windows .NET `InvokeCalibratedRaster` 的 byte[]/直接写入接口均使用同一协议。公开 schema 见 [SDK PREPARE](../../sdks/schemas/workflow-trigger-raster-prepare.v1.schema.json)。节点摘要统计每个像素状态；显示只增加小型 raster_source 描述，不再次复制原始数组。已覆盖的首次过滤/变换/保存重读可保留原始网格、标定身份和拾取像素行列；后续审计发现再次派生保存会丢失该描述，不能扩大成任意多代存读均通过。生成顶点没有唯一原像素时不伪造行列。

### 6.2 界面与验证记录

参数编辑复用 MetrologyWorkspace/CloudViewer。文件/数组切换、投影分支、单位、精度、尺度、无效规则与标定身份明确；数组模式不显示可覆盖标定的编辑框。格式不支持的精度、非正步距、非正交方向和不可精确表达的哨兵在提交前拒绝，后端仍独立校验。应用、取消、节点切换沿现有工作区生命周期。

| 本批验证 | 实际结果与覆盖 |
| --- | --- |
| B06 内核/输入/启用组合 | Windows、WSL Ubuntu 各 133 通过；本批随后追加的 schema/CLI 测试另列，不累加为独立覆盖 |
| 受影响旧点云组合 | Windows 129 通过；WSL 127 通过、2 项平台限定跳过；含旧 Trigger、Runtime、资产、契约、预处理、显示与新栅格 |
| 真实发布运行 | Windows 6 通过；WSL 5 通过、1 项 Windows net472 跳过；正式发布准入、独立 worker、文件上传、Python 数组、取消、停机切版和客户端写入中退出后的恢复 |
| .NET | net472 构建与契约程序通过；byte[] 和直接写入的真实 Trigger 调用在 Windows 发布测试中通过 |
| 客户端追加回归 | Trigger/公开 schema/命令行 cloud 与 raster 分发及自定义输入键，两平台各 11 通过；与上述组合有重叠，不重复累加 |
| 文件读取收尾 | Windows 文件组再次 71 通过；独立进程复核无先前受限 OpenCV 测试写出器的原生异常日志，生产解码仍只有 Pillow 路径 |
| 前端 | 新参数/像素显示及既有预览组合 19 通过，Vue 类型检查通过 |
| 真实 Windows 页面 | 文件/数组模式切换取消、文件 Preview、桌面/760px 窄屏、非空三维画布/旋转、应用模式配置、保存发布、停机切版、上传运行、查看结果、停止 |

Ubuntu 原组合曾有一次回收断言失败：测试在收到响应后只扫描一次，但实际响应发布在 executor finally 释放之前。改为有界等待 ACK、lease、source permit 和 executor 全部归零后，重跑同一组合通过；没有改生产等待、准入或回收逻辑。

页面使用独立解析网格 256×192（49,152 像素），`h=0.015*column+0.025*row+2*sin(column/32)`，0.25 mm 行列步距。显示概览显式设 1,000 点，计算使用全部像素；不是缺少点的真实工件替代品。截图：[桌面编辑](assets/metrology-raster/editor-desktop.png)、[窄屏编辑](assets/metrology-raster/editor-narrow.png)、[发布结果](assets/metrology-raster/published-result.png)。Ubuntu 覆盖后端与原生文件系统，不宣称 Ubuntu 浏览器验收。现有工件 PLY 不包含相机内参或原始高度网格，因此尚无 B06 实采标定误差对照。

隔离服务使用 5620/5621，业务 5600/5601 配置未修改。开始时前端静态运行配置指向 5600，只读取了业务列表；发现后将本轮 Vite publicDir 独立指向 5620，所有测试创建、发布和运行均在隔离空库完成。未修改系统缩放或 GPU 配置。

收尾变更 Python 文件 Ruff 与 `git diff --check` 通过；发布画布坐标区域检查到 4,564 个有色像素，非空显示与旋转/窄屏布局已实看。API、worker、Broker、Runtime、Vite 均已退出，5620/5621 无监听；仓库 `.tmp/` 与 Ubuntu 本轮隔离目录已清理，Ubuntu 恢复停止状态，其他 WSL 发行版未停止。截图留在本文相邻 assets 目录，不依赖临时文件。尚未自动提交 Git。

## 7. 后续固定顺序

1. **B06 来源修复与代表验证**：先修资产再次派生保存的标定来源丢失，覆盖多代、源点/生成点、文件/数组和资源包；再复用转换已有统计消除重复状态扫描。专用配方携原件资源包空环境组合、大载荷各角色峰值/取消、最新离线装配与实采对照独立记录；后几项不阻塞 B07，不能用旧 A09/A10/A12 证据替代。
2. **B07 扫描轮廓**：收口行序、固定步距/编码器位置、扫描轴、缺行/倒序及位姿定义，复用当前原像素/来源、LocalBuffer、保存和工作区；不得将轮廓扫描强套针孔模型。先解析真值，再文件/数组、节点与发布。
3. **B08 高度图**：明确投影网格、多层冲突、缺测与聚合来源，复用现有空间/资源预算；显式方法分别验证，不隐式填洞或新增资源系统。

十秒节拍、实体计量认证和最新离线装配继续独立记录，不阻塞上述开发；S2 旧诊断不重跑。台面内自动粗搜索、B09–B23 仍按[唯一剩余清单](3d-metrology-remaining.md)推进，不在本批重新命名或追加前置条件。
