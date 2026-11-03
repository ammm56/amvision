# 3913 正面逐工件结果与坐标验证

## 范围与状态

日期：2026-10-29。目标草稿：`workflow-app-20261028070103`。

已在原正面工作流新增“08 逐工件 JSON / 总 OK-NG”节点组及“最终返回 JSON”预览。公开输出仍为 `report: value.v1`，其值改为下述逐工件结果。原始检测、定位、读码诊断保留在原节点中。没有新建行业专用运行节点，没有修改模型、阈值、参考图、Runtime 或 Trigger 协议。

更新的是编辑草稿。真实 Runtime 验证使用临时发布副本；测试完成后已停止并物理删除临时 Runtime 与应用。已有发布版本、Runtime 和 Trigger 没有切换；后续正式使用需要发布此草稿并选择相应版本。

## 返回格式

业务格式标识：`amvision.workpiece-inspection.v1`。HTTP/Trigger 外层仍使用原协议包装，以下字段位于业务 `report.value` 中。

| 字段 | 类型与含义 |
| --- | --- |
| `format_id` | 上述业务格式标识 |
| `face` | 当前工作流固定为 `front` |
| `image_size` | `[2500, 2048]`，顺序为宽、高 |
| `coordinate_space` | `resized-source-image-pixels` |
| `expected_count` / `count` | 预期工件数与实际返回工件数，当前均为 18 |
| `height_assessment` | `not_measured`；当前二维方法没有测量物理高度 |
| `result` | 总体 `OK` / `NG` |
| `items` | 逐工件记录数组，以 `item_id` 显式关联 |
| `items[].item_id` | 槽位标识，例如 `slot-02-03` |
| `items[].result` | 本件放置与条码均通过时为 `OK` |
| `items[].placement.result` | 原放置规则汇总结果转为 `OK` / `NG` |
| `items[].placement.roi` | `bbox_xyxy` 与 `polygon_xy`，表示该槽位配置的检测 ROI，不是新预测的工件轮廓 |
| `items[].placement.reasons` | 原放置规则的失败原因数组；通过时为 `[]` |
| `items[].barcode.result` | 检测与解码判定 `OK` / `NG` |
| `items[].barcode.state` | 原解码状态；未进入读码分支时为 `not_executed` |
| `items[].barcode.detections` | 当前 Select Best 选中框数组；每项含 `region_id`、`class_name`、`score`、`bbox_xyxy`、`polygon_xy` |
| `items[].barcode.values` | 有效、非空的解析文本数组；未解析时为 `[]` |

`barcode.detections` 返回选中的模型检测框，不是外扩后的解码裁剪框，也不是条码解析器自身的角点。当前流程每件最多选择一个检测框。未选中的模型候选框仍从原模型与选择节点查看。

完整实测 JSON 位于本地数据目录 `data/files/developer/线扫16K读码检测/3913/validation/final-result-20261029/result-normal.json` 和 `result-missing.json`。

## 坐标约定

所有公开坐标均在**当前原图直接 resize 为 2500 × 2048 的图片**上使用。原点为左上角，x 向右，y 向下，单位为像素。输出保留浮点数，绘制时再取整。

必须区分配准参考图与当前图：

1. 槽位 ROI 在参考概览图中编辑。返回前通过本次 Circle Pattern Locate 的“参考概览图 → 当前概览图”变换，得到当前缩放图坐标。
2. 条码模型在局部搜索图中检测。先用该图携带的 `source_from_crop` 将检测框四角映射到当前原图，再用 resize 变换映射到 2500 × 2048。这里只计算坐标，没有对大图执行额外 warp。
3. 当前输入为 20000 × 16384，比例为 1/8。resize 与现有裁剪链采用像素中心约定：`x'=(x+0.5)/8-0.5`，y 同理。
4. `bbox_xyxy=[xmin,ymin,xmax,ymax]` 是变换后多边形的轴对齐外接框；`polygon_xy` 保留定位旋转。不能只缩放宽高、遗漏裁剪平移或托盘定位变换。

原诊断节点仍可含局部图或原图坐标；这些诊断字段不混入最终业务 JSON。调整相机图尺寸、overview 尺寸或裁剪比例时，应同步核对坐标变换参数。

## 编排与判定

- 使用现有 List Group By、Extract Value Field、Object Field、Create Object、For Each、Compare、OK/NG Decision 等基本节点。按 `item_id` 关联，节点位置和列表排序不参与匹配。
- 先逐个投影选中条码框，再遍历完整放置结果列表汇总。两个独立循环顺序连接，不使用嵌套循环。
- 槽位放置通过、恰好匹配一个条码记录、恰好一个选中框、解码状态 `decoded`、恰好一个有效非空文本，才判定本件 `OK`。
- 放置 NG 的工件仍返回 ROI；即使上游跳过其读码，最终也保留该槽位，条码数组为空，状态为 `not_executed`，本件与总体为 `NG`。
- 总体要求条目数、唯一 ID 数和 OK 条目数均等于预期数量。空列表、缺项和重复 ID 不会判为总 OK。
- 本次通用节点补充仅为 Transform 2D Create 的可选矩阵输入绑定。节点实现与 `opencv.nodes` 包版本更新为 0.1.9；复用已有参数解析与几何处理器。包版本变化使 Preview Worker 在现有空闲刷新边界载入新目录。

## 验证结果

| 验证 | 结果 |
| --- | --- |
| 图执行器、工业几何、坐标桥接、catalog、版本策略 | 31 项通过 |
| 真图完整 Preview API | 成功；显示资源可读取；Preview 会话已释放 |
| 内置浏览器 Preview | 成功，239 条节点记录；“最终返回 JSON”可展开、复制 |
| 正常原图 CPU/OpenVINO Runtime，2 次 | 18 件均 OK；18 个条码值与基线逐 ID 一致；原放置测量数值一致 |
| 缺件构造图 Runtime，1 次 | 总 NG；仅 `slot-02-03` 为 NG；其条码 `not_executed`；其余 17 件解码正常；仍返回 18 项 |
| 独立 NumPy 复算坐标 | 正常与缺件结果最大差约 0.000158 像素，小于 0.0002 像素容差 |
| 返回坐标叠加 | 直接在缩放原图绘制，绿色槽位轮廓、橙色条码框对应正常 |
| 临时验证资源 | Runtime 与应用均已删除 |

图执行器测试另覆盖旋转/平移、条码乱序、无检测框、未解析、无效文本、空文本、多码、重复条码、缺槽及重复槽位。

正常 Runtime 两次墙钟耗时约 17.14 / 18.94 秒，缺件约 17.59 秒。正常测试与其他验证存在相邻执行和环境竞争，不作为无干扰性能对照；这些结果没有达到此前的 10 秒目标。完整 Preview 打开逐步证据图时约 60 秒，不能与禁用显示的 Runtime 耗时混用。本次没有完成长期 soak 或新现场数据准确率认证。

审计产物：

- `validation/front-performance/final-result-normal/report.json`
- `validation/front-performance/final-result-missing/report.json`
- `validation/final-result-20261029/preview-normal-v3/report.json`
- `validation/final-result-20261029/verification.json`
- `validation/final-result-20261029/returned-coordinates-2500x2048.png`
- `validation/final-result-20261029/browser-final-json.png`

以上相对路径均基于 `data/files/developer/线扫16K读码检测/3913/`。

## 重复验证

```powershell
conda activate amvision
python -m pytest tests/test_linescan_front_result_graph.py tests/test_opencv_industrial_geometry_nodes.py tests/test_opencv_geometry_bridge_nodes.py tests/test_opencv_geometry_node_catalog.py tests/test_node_version_policy.py -q --basetemp=.tmp/pytest-linescan-result
python -m scripts.audit_linescan_front_result
```

`configure_linescan_front_result.py` 生成并校验汇总子图，只有显式 `--apply` 才保存草稿。已有汇总组更新只替换该脚本负责的 `final_*` 节点；不重置定位、ROI、检测与读码参数。`validate_linescan_front_runtime.py` 使用正式发布、启动、调用和删除接口测试临时副本。审计脚本只读取已保存报告并复算坐标，不重新调用模型。
