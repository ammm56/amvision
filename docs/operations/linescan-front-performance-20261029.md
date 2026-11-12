# 3913 正面工作流性能验证

日期：2026-10-29。对象为 `workflow-app-20261028070103`，仅正面。目标是在关闭预览后，CPU 优先完成整张线扫图的定位、18槽放置检查与条码解析，整链低于10秒。**当前 CPU 测量未达到该目标，不能按10秒节拍验收。**

## 输入与测量边界

实际输入为开发数据目录 `data/files/developer/线扫16K读码检测/3913/3913正面大图.bmp`，20000×16384、BGR24，解码矩阵937.5 MiB。测试通过本地文件引用提交，包括读取、解码、定位、放置判断、模型推理及读码；没有将解码预先移出计时。公开图片输入及已有 Trigger 协议不变。

验证副本关闭 Image/Value/Gallery Preview、节点调试图片和比较差异图。为分解耗时的运行显式打开节点诊断；另外使用关闭诊断的正式响应方式复测。原草稿保留预览能力和可编辑参数，生产发布前仍需按实际需要关闭预览。临时 Workflow 和 Runtime 经正式 API 创建、发布、启动及物理删除，原应用的发布版本、Runtime、Trigger 未切换。

开发机为 i7-11800H，8物理核、16逻辑线程。系统同时有原有服务及其他应用运行，本组没有停止无关进程。耗时波动明显，以下结果不是隔离硬件的性能上限，也不是长期稳定性认证。

## 已应用的优化

1. Mapped ROI Crop 新增可选 `window_roi`，直接将父槽位与局部窗口变换组合后采样原图，不再每槽生成完整工件图再裁1000×1000窗口。窗口位置和尺寸仍由 Create ROI 编辑；模型像素链路不经过 JPEG。
2. 循环外保留一张原分辨率参考工件图供框选。只在编辑显示支路编码 JPEG，几何取参仍使用原尺寸。
3. 使用相同训练权重的 OpenVINO FP32 CPU 模型；当前开发目录没有该条码模型对应的 OpenVINO 构建，因此通过正式转换任务生成，并验证导出输出与源模型 allclose。最大绝对误差0.000946，平均绝对误差约0.0000109；最终解码文本另行逐槽核对。
4. 18张搜索图经已有 Detection Batch 一次提交，减少逐图输入注册和模型调用开销。一个模型实例内仍顺序推理，不增加并发队列，不宣称张量批推理。
5. Batch 结果按 `item_id` 分组，循环按搜索图的 `roi_id` 取唯一结果。坐标来源保留在图片引用中，不依赖数组位置或节点布局顺序。没有正常槽位时，Conditional Start/End 明确绕过 Batch，读码循环返回空列表。

这些是通用节点和明确编排；没有新增3913专用算法节点。本轮早期草稿为95个节点，之后将放置检查展开为独立测量、判定、证据支路，当前为138个节点，详见 [独立检查验收](linescan-front-inspection-primitives-20261029.md)。模型和读码规则保持一致。

当前 CPU 部署为 `deployment-instance-26e1175063ab414fa40666f4fa246b68`，构建为 `model-build-f9e993c0f4e5`，转换任务为 `task-ea61996024cd`。单实例、FP32、latency、单 stream，线程设置沿用平台 CPU 配置。原 ONNX CPU 部署保留。

## CPU 实测

| 条件 | 图执行时间 | HTTP往返时间 | 说明 |
| --- | ---: | ---: | --- |
| 原 ONNX CPU 编排，无预览 | 43.73秒 | 见原报告 | 18次单图模型调用约16.15秒，完整工件裁剪约11.22秒 |
| 直接窗口、OpenVINO 单图循环 | 26.97秒 | 28.11秒 | 一次具有完整节点诊断的成功运行 |
| 直接窗口、OpenVINO Batch | 16.07秒 | 21.05秒 | 本组最快成功运行，18槽18码均正确 |
| 同一 Batch Runtime 连续5次 | 17.72–38.14秒 | 22.55–42.78秒 | 均成功且条码逐 ID 一致，性能波动未完全归因 |
| 关闭诊断的正式响应补测 | 未开启节点计时 | 46.22秒成功；45.15秒失败 | 第一次18码一致；第二次在 Batch 发生 inference Mailbox 响应超时 |

最快 Batch 样本中，大图解码节点约5.08秒（其中解码约3.95秒），Batch 模型节点约7.09秒，18窗口准备约0.61秒，逐槽读码循环约0.62秒。完整工件参考图只裁一次，约0.42秒。原逐槽完整工件裁剪已从主要瓶颈中移除。

独立 OpenVINO CPU 测量中，18个真实窗口的原始推理合计约7.32秒；改变2/4/8/16线程未得到稳定优于当前配置的结果，因此没有按单次偶然值修改线程数。不能通过缩小条码有效像素、取消放置检查、降低模型输入尺寸或跳过条码来宣称达到10秒。

最后一组系统采样中，整机 CPU 89.6%–99.9%，可用内存约3.2–4.7 GiB；另有图形工具、编辑器、浏览器等进程竞争 CPU。此信息说明测试未隔离，不能单独证明超时根因。超时及波动均保留为未通过项，不靠延长超时或隐藏重试消除失败记录。

额外使用相同权重的 PyTorch FP32 CUDA 部署作对照，正式 warmup 后两次都读出18个相同条码，图执行37.62/18.20秒、HTTP往返39.55/21.53秒。第二次模型节点2.08秒，大图解码节点10.22秒，整链同样未通过10秒。原草稿继续使用 OpenVINO CPU；GPU 对照资源在测试结束后停止、删除。首次未预热对照遇到控制期望状态冲突，该失败也保留，不能用于性能统计。

下一轮验收应在加载最新修复并有足够空闲 CPU、内存的环境中进行，分别记录第一次与连续执行的完整耗时、节点耗时和资源使用；随后才能判断是否需要更小模型或现场硬件调整。现有证据既不能承诺 CPU 达标，也不能证明 CPU 永远无法达标。

## 正确性与资源

`validation/front-performance/correctness-audit.json` 核对了10次正式运行：原图、连续5次原图、整图平移旋转、单槽缺失、无合格槽位、修改搜索框尺寸。

- 原图和运动图均18槽通过，18个解码文本与优化前基准逐 ID 相同。
- 缺失图只有 `slot-r02-c03` 放置失败并跳过读码，其余17个文本相同。
- 测试副本将质心阈值设为0，验证没有合格槽位时模型不执行，返回空码列表。该阈值未写回草稿。
- 搜索框改成1200×1100仍读出相同18码，仅修改验证副本。
- 连续5次结束后的 Runtime Worker Private 约138.4–140.6 MiB，句柄355→345；本组未观察到单调增长。该记录不覆盖多日运行。
- 本轮相关回归21项通过（67.82秒），覆盖 Mapped ROI Crop、Preview 故障通道及真实 spawn 回收、原 Preview Worker、geometry catalog 和 Image Decode；所改性能脚本与新增测试通过 Ruff 检查。

目前只有一张真实正常正面图。受控缺失、移动等只验证流程响应，不替代真实缺陷精度；二维前景检查不能证明没有翘起或已压到底。

## Preview 故障处理

一次大图 Preview 在内存 RPC 超时后，旧 Worker 被继续复用，迟到回复导致下一次请求出现协议不匹配。修复将故障通道标为不可复用，并在确认 Worker 退出后释放槽位和预算；正常预算拒绝不销毁健康 Worker。不延长超时、不重试业务，也不修改 Runtime/Trigger 数据通道。

最小测试覆盖超时后拒绝迟到回复、错误请求 ID、正常业务拒绝和两次真实 spawn 的故障回收。后续正常重启后已完成真实 Preview 界面复测，结果见下节；早期独立 Runtime 成功不能替代当时尚未完成的显示验收。

早期内置浏览器绑定失败，未完成当时的界面验收；后续重置浏览器控制会话后，已在同一标签页实际验证整链 Preview、逐槽图片查看器和18行完整测量表。

## 重启后正式 Runtime 连续复测

以下使用当前138节点草稿的临时副本，同一 OpenVINO FP32 CPU 部署，不修改原应用发布版本、Runtime 或 Trigger。输入仍为原始BMP文件引用，计时包含读取和解码；03C证据组、所有预览节点及调试图被显式禁用。

| 测试 | 结果 |
|---|---|
| 诊断对照2次 | HTTP13.342/14.608秒；图执行首轮13.024秒 |
| 无诊断的正式响应10次 | 全部成功；最小12.972、中位13.723、最大14.376秒 |
| 逐槽正确性 | 10次均18槽通过、18码一致；全部测量/阈值/判定，以及条码定位选择、裁剪解码结果、搜索ROI按ID与诊断基线精确相等 |
| 单槽缺件整链 | 15.885秒成功；仅slot-02-03不通过并跳过读码，其余17码一致 |
| 全槽不通过分支 | 5.911秒成功；没有执行Detection Batch，返回空条码列表 |
| Runtime Worker运行后资源 | Private141.71–145.45MiB；句柄356→345，中间无持续单调增长 |
| 环境 | 整机CPU各次间隔平均69.4%–78.6%；可用内存约6.29–6.62GiB；没有停止无关应用 |

10次运行仅验证短期稳定性，不是长期运行认证。各次输入、阈值、测量和条码均一致，没有通过放宽阈值、缩小条码像素或减少检查项换取性能。四组临时 Runtime 已停止并物理删除，临时应用亦已物理删除；再次GET八个资源均返回404，记录为 `inspection-resume-resource-audit.json`。验证脚本及Preview修复文件通过Ruff检查。

诊断两轮的主要耗时：原图解码与登记3.360/3.348秒（937.5MiB raw图含内容摘要），模型Batch6.686/7.545秒，概览缩放0.614/0.635秒；搜索窗口准备0.447/0.635秒，读码循环0.462/0.337秒。父级控制节点计时包含子链，不能与Batch、循环内部节点重复求和。

两种读图方案单独对照：`read_bytes + imdecode` 为2.171/2.311秒，`mmap + imdecode` 为2.177/2.267秒，解码像素SHA256完全一致，没有稳定收益，因此不引入mmap文件生命周期分支。直接 `imread` 在当前Windows环境无法读取该中文路径；不采用改名、复制大图或路径旁路来包装性能收益。保留现有跨执行缓存上限，不以缓存整张测试图片掩盖现场每次新图的真实成本。

结论：本轮整链Preview与浏览器显示已通过，但CPU完整链路仍未达到10秒。当前主要成本是大图解码/摘要和既有YOLOX-M模型计算；在保持简洁实现和现有检测结果的约束下，本轮不继续叠加并发队列、特殊BMP解码器或隐式降精度。后续若必须达到10秒，应在现场目标硬件复测，或将模型规模/输入方案作为独立精度验证任务，不把尚未验证的改动直接写入配方。

证据：`inspection-timing-after-restart/report.json`、`inspection-normal-repeat-after-restart/report.json`、同目录`correctness-audit.json`、`inspection-missing-after-restart/report.json`、`inspection-reject-all-after-restart/report.json`、`decode-copy-benchmark.json`、`imread-unicode-benchmark.json`。

## 复现与证据

在仓库根目录先执行 `conda activate amvision`。

```powershell
python -m scripts.optimize_linescan_front_workflow --batch --deployment-id deployment-instance-26e1175063ab414fa40666f4fa246b68 --apply
python -m scripts.validate_linescan_front_runtime --deployment-id deployment-instance-26e1175063ab414fa40666f4fa246b68 --batch --runs 2 --report runtime-openvino-new
```

第二条命令从当前草稿复制临时应用，关闭预览，执行真实图片，按槽位核对解码文本，最后停止并删除临时资源。当前Batch草稿使用 `--timings` 返回已有节点计时，无需新增诊断节点；`--baseline-report <report.json>` 对照已有Runtime报告中的全部逐槽测量和判定。`--diagnostics` 为早期逐图检测编排的诊断输出，不用于当前Batch草稿。`--image`、`--barcode-bbox`、`--reject-all` 分别用于已有扰动图、可编辑框和空分支检查。

数据目录下 `validation/front-performance/` 保留配置、转换校验、部署信息和各轮 `report.json`。主要报告为 `baseline`、`runtime-openvino-debug`、`runtime-openvino-batch-3`、`runtime-openvino-batch-repeat`、`runtime-openvino-batch-motion`、`runtime-openvino-batch-missing`、`runtime-openvino-batch-empty`、`runtime-openvino-batch-window`、`runtime-openvino-final`、`runtime-gpu-batch-warmed`。环境采样为 `environment-final.json`。运行失败的报告保留错误，不能用于成功耗时或准确性统计。

最后草稿与资源复核为 `final-draft-audit.json`；补测临时应用及 Runtime 删除后 GET 均为404，GPU 对照部署删除返回204、再次读取404。测试进程结束后尝试清理 `.tmp/pytest-linescan-performance` 与 `.tmp/linescan-diagnostics`，执行被工具策略拦截，未重试或绕过；这些目录仍是待清理临时产物，不作为交付证据。
