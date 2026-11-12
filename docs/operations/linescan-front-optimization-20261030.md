# 3913 正面大图读取与编排优化验证（2026-10-30）

## 范围与结论

工作流 `workflow-app-20261028070103` 使用 20000 × 16384 的 `3913正面大图.bmp`、18 个槽位和已有 OpenVINO FP32 CPU 条码模型。本次修改草稿，不发布新版本、不切换已有 Runtime，不改模型精度、检测阈值、协议或调度。代码位于通用 `opencv.nodes` 包，版本为 0.1.10。

保留了有实测依据的大图解码和编排简化。连续测试结果正确，短测未发现 Worker 内存或句柄持续增长；**尚不能承诺稳定在 10 秒以内，也不能据此声明现场准确率或长期运行认证通过**。

## 保留的实现

1. **Image Decode 增加显式 `bmp-bgr24` 方式。** 默认仍为 `opencv`。快速方式限定 BITMAPINFOHEADER / BI_RGB / 24 位 BMP；校验头、尺寸、行对齐和像素范围，支持正向与倒向行。本地和 ObjectStore 文件短期只读映射，复制为独立连续 BGR 矩阵后关闭文件和映射，省去近 1 GiB 的完整编码字节副本。上传/协议的编码缓冲区复用同一解析器；raw memory/buffer/frame 继续走原始像素路径。不支持的编码明确失败，不静默回退。完整像素 SHA 和 Run 释放边界保持原实现。
2. **Mapped ROI Crop 增加标准 `rois` 列表输入。** 与 `roi`、`roi_items` 互斥。由槽位阵列直接传入 ROI 列表，`selected_ids` 按正常槽位 ID 筛选，`window_roi` 仍来自手动编辑的条码区域。复用原采样、插值、坐标链及越界校验，串行生成局部图，不添加节点内并发或任务队列。
3. **减少编排中转。** 取消逐槽准备图片的 For Each，改为一次列表裁剪。最终结果中的字段提取复用 Object Pick / Merge Pair，结果组由 98 节点降为 86 节点，完整图由 239 节点、317 边降为 221 节点、295 边。仍是可检查的通用节点，未增加场景专用汇总节点或表达式执行器。
4. **保留交互与判定。** 首槽编辑图、ROI Grid、条码窗口、每项测量、证据图、NG 保留项和空列表跳过模型的显式分支均保留。条码框当前为 `[1720,1000,2720,2000]`，仍可在节点面板修改。返回坐标继续使用当前原图直接缩放后的 2500 × 2048 坐标系。

大图注册仍计算完整摘要；没有跳过像素校验、跨运行保留大图或并行重复读盘。OpenCV 算子线程数仍由既有 Worker 启动配置控制，不在节点执行中修改进程全局线程设置。定位与配准在概览图上执行，高分辨率条码裁剪只映射局部区域；未增加整幅 16K warp。

## 性能证据

相同图片、模型与阈值，按旧 A → 新 B → 新 B → 旧 A 顺序执行，每组 2 次。每次都独立核对 18 件测量、条码文本与最终坐标。以下为当前开发机结果，非隔离机器验收。

| 指标 | 旧流程 | 优化流程 |
| --- | --- | --- |
| 4 次完整调用范围 | 7.523–8.932 秒 | 6.934–8.158 秒 |
| 完整调用中位数 | 8.118 秒 | 7.359 秒 |
| 大图解码及注册节点 | 1.845–2.312 秒 | 1.304–1.401 秒 |
| 模型批量推理节点 | 3.232–3.665 秒 | 3.255–3.784 秒 |

这组完整调用中位数约降低 9.4%。定位与概览配准约数十毫秒，概览缩放约 0.35–0.55 秒；当前主要成本仍为模型推理和大图输入。For Each / 条件结束节点计时包含内部执行，不能与子节点耗时再次相加。

随后同一 Runtime 连续串行执行 20 次，20/20 成功：中位数 **11.790 秒**，p95 **14.649 秒**，最大 **21.909 秒**。整机采样 CPU 约 47.8–84.8%，前述交替对照约 33.0–44.4%。早先优化后两次调用为 15.217 / 15.095 秒。因此不能把不同时段的 17–19 秒与最佳 6.9 秒直接计算成优化收益，也不能宣布 10 秒门禁已经稳定通过。

没有采用的尝试：

- 普通 mmap + OpenCV imdecode 未呈现稳定收益，未加入默认读取路径。
- OpenVINO 请求复用与线程数 8 / 16 对照没有稳定、明显的收益；原始模型输出一致，保留现有自动线程、单 stream、LATENCY 配置。
- 不增加并行大图副本、不在节点中创建线程池、不更改 Runtime/Trigger 同步调用方式。

## 正确性与资源验证

- 76 项针对性测试通过，覆盖 BMP 行方向/填充/损坏输入、共享缓冲区和原始像素、裁剪坐标、结果图执行、catalog 与版本策略。
- 实际 18 个条码搜索裁图：旧逐项与新列表路径的像素 SHA、槽位 ID、`source_from_crop` 完全一致。
- 20 次完整调用：全部放置测量值、18 件条码文本和最终 JSON 与旧基线按 ID 一致；独立坐标复算最大误差约 **0.000158 像素**。
- 缺件构造图：18 项完整返回，只有 `slot-02-03` 为 NG，该件不执行读码，其他 17 件正常解码。全 NG 测试：0 件进入条码推理，最终仍保留 18 件 NG 结果。
- 完整 Preview API 成功，255 个显示资源均可读取，无显示错误，会话已释放。内置浏览器完整 Preview 成功，最终 JSON 可展开查看。两次完整证据显示测试的 graph 计时约 19.557 / 99.378 秒，波动较大；这些测试开启了逐项证据图，不能混入禁用预览的运行计时，也不能据此声称 Preview 性能门禁通过。
- 上传式 BMP 解码验证通过。983 MB 原图超过现有 Preview 单文件 64 MiB 限制，完整原图使用本地路径或 ObjectStore；本次未扩大上传容量。
- 20 次 Runtime 调用后 Worker Private 约 145–149 MiB，最后一次约 147.5 MiB；句柄由 356 回落至 345，未出现每次调用持续累积。单独读取/注册大图 20 次，释放后 Private 从约 548.36 MB 到 548.44 MB，句柄预热后保持 264。这里是调用后采样，不是执行峰值，也不代替长时间 soak。
- 验证创建的临时 Runtime 和应用均已通过正式接口删除。

## 准确性边界

当前只有一张真实正常正面大图。正常图、受控缺件和输入/坐标边界验证证明本次优化未改变既有结果，不能证明各种光照、材质、姿态及现场缺陷的准确率。未通过调宽阈值或裁掉边缘换取速度。

前景比较依赖配准、正常参考轮廓及允许槽位范围；主轴角差为二维无向角，搜索范围外的缺陷需要额外区域覆盖。当前未测物理高度，`height_assessment=not_measured` 保留，不能把二维通过解释为确认无翘起。

已有模型把 6 处实际 DataMatrix 候选标为 `qrcode`，当前工作流同时接受两类候选，再由 DataMatrix 解码器读取；18 个文本与基线一致。本次没有篡改模型返回类别，后续需使用标注数据单独检查类别混淆，不宜直接收窄为只接受 `dmcode`。

## 复现与证据

所有证据相对 `data/files/developer/线扫16K读码检测/3913/`：

- `validation/front-optimization-20261030/verification.json`：交替对照、20 次连续调用、资源和坐标汇总。
- `validation/front-optimization-20261030/image-input-production-20.json`、`crop-batch.json`、`openvino-request.json`：输入、裁剪与模型独立对照。
- `validation/front-optimization-20261030/preview-local/report.json`、`preview-local-final/report.json`、`preview-upload-final/report.json`、`browser-final-json.png`：Preview 与浏览器证据。
- `validation/front-performance/ab-a1`、`ab-b1`、`ab-b2`、`ab-a2`、`optimized-repeat-20`、`optimized-missing`、`optimized-empty`：原始请求结果、计时与清理记录。

```powershell
conda activate amvision
python -m pytest tests/test_bgr24_bmp.py tests/test_opencv_image_decode.py tests/test_circle_pattern_and_mapped_crop.py tests/test_linescan_front_result_graph.py tests/test_opencv_geometry_bridge_nodes.py tests/test_opencv_geometry_node_catalog.py tests/test_node_version_policy.py tests/test_runtime_image_buffer_inputs.py -q --basetemp=.tmp/pytest-linescan-optimized
python -m scripts.audit_linescan_batch_crop
python -m scripts.audit_linescan_optimization
```

`simplify_linescan_front_workflow.py` 默认只生成和校验候选，显式 `--apply` 才保存当前草稿；保存前核对指纹。运行测试脚本创建临时副本，不覆盖现场发布版本。测试必须串行执行，避免相互争抢 CPU 后误判收益；结果比对失败时不得只记录耗时继续放行。

本次不涉及数据库、HTTP/ZeroMQ/共享内存协议迁移，不改前端框架，不增加依赖；节点包仍使用已有 NumPy/OpenCV 与 Python 标准库，可随同目录 Python 发行。此前最终 JSON 契约与坐标定义见 [逐工件结果验证](linescan-front-result-20261029.md)。

## 草稿画布整理

2026-10-30 参照 3570 治具工作流的分组方式整理正面草稿。主流程从左向右排列，按输入、整盘定位、槽位阵列、放置检查、条码窗口、批量检测、裁剪读码和槽位汇总分区。七项检查按列对齐，下方相同列显示检查数据、证据绘制和图库；保留 `inspection-evidence` 组的整体启停用途。最终 86 个结果节点拆为坐标转换、逐槽关联、放置结果、条码结果、单件 JSON 和总判定六组，位于读码区下方。

整理后共 221 个节点、295 条连线、17 个分组。分组默认锁定位置，与 3570 一致；修改位置前可解锁。节点尺寸来自浏览器实测，并为图像、JSON 和 18 张图片的图库展开预留空间。

`scripts/arrange_linescan_front_workflow.py` 仅写入草稿的画布位置、分组、说明和 App Entry/Result 显示位置。正式 API 校验通过，保存前后剔除显示字段后的应用与模板逐字段一致，节点参数、启用状态、输入输出、连线和顺序均未改变；重复排列结果一致。未发布版本、未修改 Runtime/Trigger。本次布局调整不重复运行模型性能测试，也不改变前述性能或准确性结论。

布局快照、节点测量和浏览器截图保存在 `validation/front-layout-20261030/`。该目录的 `node-sizes.json` 必须与当前节点清单一致，脚本默认仅校验；显式 `--apply` 才保存，并在保存前核对草稿指纹。画布实显核对无节点重叠和组外节点。
