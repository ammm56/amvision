# 3913 正面独立检查验证（2026-10-29）

目标草稿：`workflow-app-20261028070103`。节点边界与数据契约见 [按区域测量、判定与证据绘图](../nodes/inspection-measurement-items.md)。

## 当前完成范围

- 新增7个通用掩膜、测量、判定、汇总和绘图节点；产品参数只放在开发配方脚本中。
- 配方将集中式 ROI Foreground Compare 替换为显式检查支路。保留定位、可编辑 ROI Grid Create、原像素条码搜索框、模型选择和读码规则。
- 准备的草稿为138节点，检测按03A前景/测量、03B独立判定、03C证据显示、03D汇总分组。03C可整组禁用，不影响检测结果。
- 使用正式 Node Catalog、Graph 校验和 WorkflowGraphExecutor 执行检测子图，包含 Object Field/Create Object、表格和图集预览，没有模拟节点处理器。
- 重启后已核对在线5600加载7个新增节点及 ROI Grid 参数，正式 API 校验通过后已保存138节点草稿。原应用没有发布新版本或切换 Runtime。
- 正式 Preview 的检测支路与完整读码链路均已完成：重启后整链18槽通过、18码正确，251个显示/数据资源完成交付，显示错误为0，详见下方复测记录。
- 浏览器发现18张图展开后图集高约984像素，原430像素行距导致下一节点覆盖图片。检查与证据组已统一为1120像素行距，更新分组边界；只调整布局。实际点击 `slot-02-03` 可打开角度证据查看器，显示角差0.01249°、阈值0–3°、结果pass及参考/当前轴线。截图为本目录 `browser-angle-evidence.jpg`。

## 实图与受控用例

输入为 `data/files/developer/线扫16K读码检测/3913/validation/front-registered/` 已有概览图。每张图先使用实际 Hough Circles、Circle Pattern Locate 定位并校正，再进入检查子链。

| 用例 | 结果 |
|---|---|
| 正常正面 | 18槽通过 |
| 整盘平移 | 18槽通过 |
| 整盘正/负角旋转 | 各18槽通过 |
| 受控缺件 | slot-02-03 未通过 |
| 受控平移跨槽 | slot-02-03、slot-02-04 未通过 |
| 受控倾斜 | slot-02-03 未通过 |
| 无定位圆 | 定位拒绝，不继续检查 |

七张可定位图片的缺失、多出、质心偏移和角差数值与原比较处理器逐槽对照一致（误差<1e-8）。每项检查生成18项判定、表格和证据图。表格按显式嵌套字段路径读取，没有把槽位 ID 丢失。

示例：受控倾斜的 slot-02-03 主轴角差5.5206°，超过3°；质心偏移5.0342 px，小于8 px，因此角度失败、偏移通过。受控缺件缺失比例0.97599，超过0.05。各项分别判定，不用总结果覆盖单项依据。

## 性能与资源边界

同一进程内使用实际图执行器：

- 七张图片的检测子图包含每项绘图、Gallery Preview 和 Value Preview，耗时约1.16–1.49秒。
- 关闭独立证据分支，重复执行30次；跳过前5次后，中位数511.5ms、最大722.2ms。
- 采样进程 Private 从约694.94MiB到692.62MiB；句柄数在369–370间，没有观察到按执行次数持续增长。
- 每次执行后调用Run图像注册表的清理路径。该短测不能替代长期现场运行认证。
- 使用实际执行器完整禁用证据分支的21个节点，确认21个节点均未执行、32个检测节点执行，18槽仍全部通过。仅禁用图集节点不能自动跳过上游绘图。

这些数值只覆盖配准概览图的放置检查子链，不包含整图加载、定位、模型推理和读码；不能据此宣称完整工作流低于10秒。

## 在线整链及 Preview 通道复测

使用 `3913正面大图.bmp`（20000×16384）和已部署 OpenVINO 模型：

- 完整 Preview 首次业务成功，18槽全部通过、18个条码均解析成功；图执行约98.26秒，显示交付约21.31秒，出现8个 `preview_memory_unavailable`。随后浏览器与禁用显示的 Preview 快照均出现 `preview_memory_channel_failed:allocate`。不能把业务成功等同于显示验收通过。
- 检测支路单独 Preview 成功，图执行20.34秒、显示交付26.68秒，资源交付无错误。Preview 仍捕获普通节点值，不能作为禁用显示的生产 Runtime 性能基准。
- 临时发布副本关闭所有 Preview 节点和独立证据组，通过正式 Runtime 连续执行3次：15.27、15.34、23.86秒；每次18槽通过，18个条码文本按明确槽位 ID 与前一版基准一致。临时 Runtime 已停止并物理删除，临时应用已物理删除。当前完整链路未通过10秒目标。
- backend 线程采样确认：普通节点旧值没有 Blob 时仍扫描整个会话的资源引用，循环更新重复占用会话锁，同时阻塞 WS 取消息。已改为只在旧值包含 Blob 时检查共享引用，并将资源提取改为单集合遍历，接收确认只计算一次引用集合。不新增缓存、队列、重试或 timeout 放宽；变更仅在编辑态 Preview SessionManager。
- 资源会话、显示、通道故障和 Worker 退出相关回归61项通过；独立检查、表格及 Catalog 回归22项通过。当时标准启动入口因旧 LocalBuffer 锁缺少可验证版本信息拒绝接替；未删除锁或强制结束原服务。服务随后由使用方正常重启，复测结果如下。

报告资产：本验证目录的 `online-full-preview/`、`online-inspection-only/`、`online-no-preview/`、`online-no-preview-profile/`、`backend-profile.json`；Runtime 报告位于 `validation/front-performance/inspection-primitives-runtime-20261029/report.json`。失败报告保留，不以成功的子链覆盖整链问题。

本轮测试进程均已结束，失败的临时启动器已停止。清理本轮 `.tmp/pytest-inspection-preview-fix` 和 `.tmp/pytest-inspection-online-regression` 的命令被自动审批以 `blocked by policy` 拒绝，目录仍待清理；未改用其他方式绕过。

## 服务重启后的完整验收

- Backend PID30372 加载修复后，使用同一张20000×16384 BMP完成整链 Preview：图执行35.927秒，调用至全部资源接收约43.211秒；665次节点执行全部结束，251次 `display.begin` 与251次 `display.end` 配对，没有 `display.unavailable` 或通道错误。会话通过正式接口释放。
- Preview 与正式 Runtime 的18槽逐项测量、阈值、判定按 `item_id` 精确相等；18个条码文本按同一 ID 精确相等。
- 通过内置浏览器再次手动发起完整 Preview，页面显示 `Preview succeeded`。7项检查均出现逐槽图集和数值表；双击角差表可查看完整18行，点击 `slot-02-03` 可查看原图、参考/当前轴线、角差0.01249°和0–3°阈值。没有再次出现上一轮通道失效。
- 浏览器截图位于验证资产目录的 `browser-full-after-restart-angle.jpg` 和 `browser-full-after-restart-table.jpg`。API报告为 `online-full-after-restart/report.json`。截图对应本次浏览器实际执行，不复用上一轮图片。
- 关闭预览和03C证据组的临时 Runtime 诊断对照为13.342/14.608秒；原图解码与登记3.360/3.348秒，OpenVINO Batch 6.686/7.545秒。诊断仅打开已有节点计时，没有向图中增加计时节点；完整HTTP时间包含原图读取与响应返回。两次均18槽、18码一致，临时资源已物理删除。
- 单独比较原图 `read_bytes + imdecode` 与 `mmap + imdecode`：前者2.171/2.311秒，后者2.177/2.267秒，解码像素SHA256一致。没有稳定耗时收益，因此不增加mmap读图分支，也不放大跨执行缓存以缓存937.5MiB整图。报告为 `validation/front-performance/decode-copy-benchmark.json`。

正式响应连续执行与资源测量见 [整链性能验证](linescan-front-performance-20261029.md)。当前仍未达到10秒节拍；Preview修复只解决编辑态显示阻塞，不能把重启后的环境变化全部归为该修复的生产性能收益。

## 代码回归

- 测量/判定/绘图、预览表格、节点 Catalog、原比较与裁图读码、ROI Grid 交互后端回归：43项通过。
- 最后补充表格嵌套列投影后，针对测量、表格与几何关联、已有 OpenCV 滤波节点及内存图片输入执行回归：23项通过（与上一组有重叠，不累计为66项）。
- 检查覆盖 ID 顺序打乱、重复/缺项、坐标不一致、非二值输入、空前景、不可测角度、缺失字段、非法阈值、原始输入不被绘图或表格修改等边界。

## 可复现操作

```powershell
conda activate amvision
python -m scripts.configure_linescan_front_inspection
python -m scripts.validate_linescan_front_inspection
# backend 加载最新代码后，验证当前在线草稿并保存（不发布）
python -m scripts.configure_linescan_front_inspection --apply
```

脚本在正式 API 校验通过后才保存，并检查验证期间草稿指纹未变化。输出资产位于 `data/files/developer/线扫16K读码检测/3913/validation/inspection-primitives-20261029/`：`inspection-workflow.json`、`validation.json`、逐项证据图片。该目录是本次开发验证资产，不是生产参考或训练数据。

仍需：CPU完整工作流10秒节拍达标、实际槽壁允许区域标定及独立现场异常样本验收。现有参考边界比例接近0.02阈值，需要真实重复采样判断裕量，不能只凭参考自检通过就放行；本次成功复测不代表多日稳定性认证。
