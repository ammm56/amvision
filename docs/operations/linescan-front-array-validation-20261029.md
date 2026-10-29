# 3913 正面定位、槽位阵列与读码验证

日期：2026-10-29。对象：开发环境 `workflow-app-20261028070103` 草稿，仅正面；未发布版本、切换 Runtime 或修改 Trigger。通用契约见 [圆心定位、ROI 比较与读码](../nodes/roi-comparison-and-crop-decode.md)。

本页记录阵列和可编辑 ROI 实现阶段的配置与验收。后续草稿已改为直接裁剪搜索窗口、OpenVINO CPU 与 Detection Batch，最新配置、无预览性能及尚未达到的10秒目标见 [正面工作流性能验证](linescan-front-performance-20261029.md)。下文的72节点、6组和全预览耗时属于前一阶段，不代表最新草稿。

首槽与阵列随后合并为通用 ROI Grid Create，当前90节点；最新交互、坐标变更和验收状态见 [网格简化与图片交互](linescan-front-grid-interaction-20261029.md)。下面的 Create ROI + ROI Array 连法是前一阶段记录。

## 完成内容

- 原图 → 1/8概览 → Hough Circles → Circle Pattern Locate → Planar Transform Bridge 校正概览。
- Create ROI 编辑托盘范围，裁出托盘；另一个 Create ROI 在托盘局部图编辑首槽多边形；通用 ROI Array 以3行6列和明确的二维位移向量生成18槽。删除原配方 Create Object 及其18项固定坐标提取链。汇总结果使用的 Create Object 继续保留。
- ROI Foreground Compare 比较参考前景缺失/多出、质心偏移、主轴角差；新增可选的允许区域边界检查。搜索余量不改变下游裁剪来源，也不改变绘制结果的 ROI 几何。
- 正常项按 `item_id` 进入 For Each；Mapped ROI Crop 从原分辨率图局部采样。工件图上的 Create ROI 可编辑条码搜索框，初始1000×1000；随后目标检测、类别筛选、40像素外扩、裁剪、显式红通道、Data Matrix 解码与结果汇总。
- 72个节点分为6组，补充托盘回绘、阵列、逐槽图片/差异、放置判定、条码搜索/检测/裁剪/解析预览。

比较参数属于本样本配方：灰度阈值80、边缘容差2像素、缺失/多出比例各5%、质心偏移8像素、主轴角差3°、边界搜索余量8像素、越界比例2%。所有几何阈值属于1/8概览图像素，不能直接解释为毫米或生产验收公差。

## 实际结果

源图为 `data/files/developer/线扫16K读码检测/3913/3913正面大图.bmp`，20000×16384、24-bit，像素矩阵约937.5 MiB。

| 检查 | 结果 |
| --- | --- |
| 原始 BMP 全链 | 18槽通过，18码读出，按槽位 ID 保留关联 |
| 全分辨率平移+旋转 | 18槽通过；18个码与原图逐 ID 一致 |
| 单槽局部缺失的全分辨率受控图 | r02-c03失败并跳过读码；其余17码与原图一致 |
| 概览图平移、正/反向旋转 | 均18槽通过 |
| 受控缺失、6°倾斜 | 均检出 r02-c03 |
| 受控横移25概览像素 | r02-c03与r02-c04失败；移动前景侵入邻槽边界观察域 |
| 定位特征消失 | Locate明确失败，无固定坐标回退 |
| 条码框改为1200×1100 | 18码与1000×1000结果逐 ID 一致；仅修改验证快照 |
| 连续两次原图复测 | 两次均18码一致，Preview资源交付无错误，会话均释放 |
| 浏览器实际 BMP 预览 | For Each 18/18；72节点无重叠，50张图片全部加载；无浏览器错误日志 |
| 回归测试 | 127 passed；覆盖节点、catalog、坐标映射、前景/边界、循环依赖及Preview交付 |

同目录 JPG 在界面中能完成定位、放置检查和流程执行，但有条码 `unreadable`。它不能代替原始 BMP 的读码证据；具体图像差异或有损压缩影响未在本任务独立归因。业务流程 `succeeded` 不等于每个码均解码成功，应检查各槽的解码状态。

## 内存与耗时

6次正式大图 Preview（原图、运动、缺失、改搜索框、两次复测）的 Worker Private 峰值约2.01–2.93 GiB，结束并释放会话后约166.5–170.6 MiB。最后3次句柄均为355→355，未观察到随本组重复运行持续增加。样本数量有限，不构成长时间稳定性认证。

全预览图执行时间约29.0–95.4秒，包含18次模型调用、局部几何采样和各阶段图片交付。后续复测约82.1/77.6秒。慢项中包含 `barcode_roi/search_preview/detection_preview` 的显示处理以及模型调用和裁剪；本次未独立归因全部波动，不能把这些数值视为已验证的生产节拍，也不能以调试预览推断 Runtime 无预览时的耗时。

## 使用与证据

1. 在节点图预览输入中选择“本地磁盘图片”，使用上述原始 BMP；也可通过现有图片公开输入传入真实采集图。
2. 预览后双击“托盘范围”的 Create ROI 图片，进入“取参 → 矩形 ROI → 应用参数”；首槽节点同理使用多边形工具。
3. ROI Array 设置行列数量和二维位移。预览“18槽阵列与编号”核对所有槽，不能只检查首槽。
4. 检查逐槽差异及放置结果。条码框在正常工件图中编辑，修改后重新预览；循环中的此参数作用于所有正常槽位。

配置：`python -m scripts.configure_linescan_front_array --apply`。原配置入口最终也复用此阵列构建步骤。实际全链验证：`python -m scripts.validate_linescan_3913_workflow --image <原图> --local-file --report front-array/<独立报告名>`。扰动验证：`python -m scripts.validate_linescan_front_cases --offline-placement`，或 `--full-motion` 执行正式 Preview 矩阵。

详细证据在开发数据 `validation/front-array/`：`stage2-cases.json`、`stage3-cases.json`、`memory-timings.json`、各次 `report.json` 与下载资源；界面截图为 `ui-workflow-layout.jpg`、`ui-first-slot-editor.jpg`、`ui-array-preview.jpg`、`ui-barcode-roi.jpg`。

当前只有一张真实正常正面图。受控扰动验证的是可解释的流程响应，不是现场真实缺陷精度；当前阈值必须通过更多正常、偏移、越槽、倾斜等实拍样本校准。二维前景与姿态检查不能证明未翘起或已压到底。扫描的非刚性拉伸、明显透视、速度变化也不在当前刚性配准已验证范围内。
