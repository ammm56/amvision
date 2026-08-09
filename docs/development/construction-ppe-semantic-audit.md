# Construction-PPE 类别语义审计

## 审计范围

审计对象为开发调试数据 `data/files/datasets/detection/construction-ppe`。原始 `data.yaml` 包含 `none`、`Person`、正向 PPE 类别和四个 `no_*` 类别。审计用于确定导入前的类别语义和互斥标注冲突，不改变平台对其他数据集的自动判断规则。

## 结论

- Ultralytics 公开说明仍把类别 5 记为通用 `none`，并明确表示数据集没有专门的缺失 vest 类别。因此 `none → no_vest` 不是上游官方类别定义，而是本项目对当前本地副本逐框检查后的数据治理结论；不得把该映射扩展为其他数据集的默认规则。
- 原始类别 5 `none` 的框覆盖未穿 vest 人员的躯干区域，应在该数据副本中规范为 `no_vest`。
- 原始类别 6 `Person` 仅存在命名风格问题，规范为 `person`。
- 原始 `image886` 的右侧人员同时存在 `vest` 和 `none` 框，归一为 `vest / no_vest` 后 IoU 为 `0.623870`，属于同一区域互斥语义冲突。图像显示该人员穿着蓝色工作背带服，保留 `vest` 框并删除原 `none` 框。
- 其余正负类别对没有 IoU 大于等于 `0.5` 的冲突。多人同图造成的正负类别共现不是冲突。
- 已生成修正后的开发验证对象：Dataset id `construction-ppe-audited-20260808`、DatasetVersion id `dataset-version-5c35edabee35`、COCO DatasetExport id `dataset-export-bbf181fccdd4`。旧导出 `dataset-export-cfbdcbebe070` 保留为问题复现证据，不再作为后续精度基线。

## 标注统计

修正前共有 11 个类别、11,614 个标注：

| 类别 | 标注数 |
| --- | ---: |
| helmet | 1,750 |
| gloves | 1,461 |
| vest | 1,632 |
| boots | 1,613 |
| goggles | 526 |
| none | 800 |
| Person | 2,265 |
| no_helmet | 485 |
| no_goggle | 411 |
| no_gloves | 556 |
| no_boots | 115 |

修正后 `no_vest` 为 799 个标注，总标注数为 11,613。

## 正负类别检查

| 正向类别 | 负向类别 | 同图文件数 | 修正前最大 IoU | 修正结果 |
| --- | --- | ---: | ---: | --- |
| helmet | no_helmet | 2 | 0.000000 | 无冲突 |
| gloves | no_gloves | 4 | 0.000000 | 无冲突 |
| vest | no_vest | 103 | 0.623870 | 删除 `image886` 的冲突 `no_vest` 框 |
| boots | no_boots | 6 | 0.134604 | 无冲突 |
| goggles | no_goggle | 8 | 0.000000 | 无冲突 |

## 平台规则

- 导入器不会对任意数据集自动执行 `none → no_vest`，因为 `none` 没有跨数据集稳定语义。
- 未修正的副本应通过 `class_map` 显式传入 `{"5":"no_vest","6":"person"}`；如归一后存在正负框 IoU 大于等于 `0.5`，导入会失败并返回样本和 annotation 信息。
- 类别名经小写 snake_case 归一化后重名时导入失败，避免大小写或分隔符造成重复类别。

## 训练结果诊断

`task-9c2653a7fa32` 的 YOLO26-M 在第 143 轮使用 latest EMA 权重执行真实
`pycocotools` 验证，整体 `AP50=0.461317`、`AP50-95=0.220697`。该结果不是
页面刷新或 COCO `stats` 索引造成的假低值。三个普通 YOLO detection core 的
受控 forward/loss 已分别与 `projectsrc` 参考实现核对，低分主要集中在样本稀少的
缺失 PPE 类别：

| 类别 | 验证标注数 | AP50-95 |
| --- | ---: | ---: |
| vest | 171 | 0.3994 |
| helmet | 201 | 0.3777 |
| boots | 151 | 0.4096 |
| gloves | 136 | 0.3480 |
| goggles | 47 | 0.2788 |
| person | 239 | 0.2712 |
| no_vest | 81 | 0.1611 |
| no_helmet | 45 | 0.1057 |
| no_gloves | 56 | 0.0400 |
| no_goggle | 41 | 0.0343 |
| no_boots | 4 | 0.0019 |

`no_boots` 在训练、验证、测试中的标注数分别为 88、4、23。验证集只有 4 个目标，
单类 AP 对少量漏检和定位误差高度敏感，也无法代表长期现场分布。后续重新划分必须
采用按类别和场景分层的确定性 split，并为每个 `no_*` 类别设置最小验证/测试标注数；
在满足该门槛前，整体 mAP 不能作为模型实现正确性的唯一判断依据。
