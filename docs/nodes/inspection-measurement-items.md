# 按区域测量、判定与证据绘图

本文定义通用的逐区域检查链。产品槽数、参考图、允许范围和阈值属于 Workflow 配方，不写入节点代码。原 ROI Foreground Compare 仍可用于集中式比较；需要逐项调试时使用本文的基础节点组合。

## 流程与责任

```text
托盘自身特征定位 → 当前图校正到参考图坐标
                             ↓
参考图 / 当前图 → Binary Threshold → Mask Logic(not，深色前景时)
                             ↓
可编辑 ROI Grid Create → ROI Mask Extract
                             ↓
                前景掩膜 / 允许域掩膜
                   ↓                  ↓
       Mask Items Properties    Mask Items Difference
                   ↓                  ↓
       Pose Items Difference    缺失/多出/超出允许域面积
                   └─────────┬────────┘
                  Measurement Items Check（每项独立）
                             ├→ Draw Inspection Items → Gallery Preview
                             ├→ Value Preview（表格或 JSON）
                             └→ Object Field → Create Object → Inspection Items Merge
                                                                  ↓
                                               Draw Regions / 后续筛选、读码、汇总
```

定位只使用托盘特征。测量前不单独把当前工件对齐到正常工件，否则可能消除需要检测的偏移或旋转。二值分割、测量、阈值判定和绘图分别显式配置；绘图不重新计算结果。

## 通用节点

| 节点 | 输入 | 输出与用途 |
|---|---|---|
| ROI Mask Extract | 二值 `mask:image-ref.v1`、`rois:roi-list.v1` | `masks/allowed_masks:image-refs.v1`；观察前景与允许域，不判定缺陷 |
| Mask Items Difference | `masks_a/masks_b:image-refs.v1` | `masks` 差集证据、`metrics:value.v1` 面积与比例 |
| Mask Items Properties | `masks:image-refs.v1` | `metrics:value.v1` 像素面积、质心、无向主轴与各向异性 |
| Pose Items Difference | `current/reference:value.v1` | `metrics:value.v1` 的 dx、dy、质心距离和无向轴夹角 |
| Measurement Items Check | `metrics:value.v1` | `checks:value.v1`；明确字段、闭区间、单位、通过/失败/不可测 |
| Inspection Items Merge | `checks:value.v1` 命名检查对象、`image:image-ref.v1` | `summary:value.v1` 保留各项判定；`regions:regions.v1` 用于现有绘图节点 |
| Draw Inspection Items | `image`、`checks`、可选证据 `masks` | `images:image-refs.v1`；原图、允许域、证据掩膜、测量线及数值标题 |

这些节点位于 `opencv.nodes` 包，沿用现有取消、timeout、禁用和进程内执行机制，不新增线程、缓存或任务队列。节点版本使用节点包版本；不引入产品专用节点。

## 数据关联和坐标

测量与检查的 `value.v1` 正文：

```json
{
  "format_id": "amvision.measurement-items.v1",
  "count": 1,
  "items": [{
    "item_id": "slot-01-01",
    "source": {
      "roi_id": "slot-01-01",
      "roi_kind": "bbox",
      "bbox_xyxy": [10, 10, 90, 90],
      "polygon_xy": [[10, 10], [90, 10], [90, 90], [10, 90]],
      "area": 6400,
      "coordinate_space": "tray-reference-overview",
      "image_size": [100, 100],
      "observation_bbox_xyxy": [2, 2, 98, 98],
      "search_margin_pixels": 8
    },
    "result": {"area": 400, "center_xy": [34.5, 39.5], "axis_angle_degrees": 90}
  }]
}
```

- 检查正文格式为 `amvision.inspection-check-items.v1`；汇总正文为 `amvision.inspection-items.v1`。都保留 `item_id/source/result`，不按列表位置或画布位置关联。
- 掩膜列表使用现有 `image-refs.v1`，每个引用附加 `roi_id/measurement_source`。局部掩膜的尺寸等于 `observation_bbox_xyxy` 的宽高。质心输出为共同图像坐标，不是裁图局部坐标。
- 两组比较必须具有完全相同的 ID 集合、坐标系名称、图像尺寸、观察框和允许多边形。重复、缺项、错误尺寸或不同坐标拒绝执行，不能默默跳过。
- `coordinate_space` 是配方对共同坐标的显式声明，不能代替上游配准。相同尺寸的两张图也不一定已经对齐。
- 每组 1–1024 项；空集合不能被汇总成“全部通过”。命名检查对象为 1–64 项。Object Field 的 Key 必须与 `check_id` 一致。
- `regions.score=1` 是规则绘制记录值，不是模型置信度或现场准确率。

## 算法定义

1. **ROI Mask Extract**：只接收单通道 uint8、0/255 的二值图，不隐式分割。允许域来自可编辑矩形/多边形；观察域为允许域按 `search_margin_pixels` 膨胀后的区域。观察框必须完整位于图像内，不能截断后继续判定。
2. **Mask Items Difference**：`difference = A AND NOT dilate(B, tolerance_pixels)`，椭圆核。分别输出 `area_a/area_b/difference_area/ratio_to_a/ratio_to_b`。分母为零时比例为 null，不伪造为零。
3. **Mask Items Properties**：直接计算前景像素矩，保留孔洞和多个组件。面积单位 px²；质心单位 px。主轴由二阶矩特征向量确定，是无向轴，不能检测 180° 反装；各向异性低于 `min_axis_anisotropy` 时角度不可测。
4. **Pose Items Difference**：dx/dy 为当前减参考，距离为欧氏距离，轴夹角规范到 0–90°。没有质心或可用主轴时，相应差值为 null。
5. **Measurement Items Check**：字段必须存在，至少配置一个有限上下限，边界包含等号。不可测为 `state=unavailable, passed=false`，不以零代替。每项输出 `check_id/metric/value/unit/minimum/maximum/state/passed/measurement`。
6. **Inspection Items Merge**：只汇总明确接入的检查，任一失败或不可测都不通过；`reasons` 为未通过的检查名。不会隐式补上未配置的业务规则。
7. **Draw Inspection Items**：只读取已有判定和测量。橙色覆盖为证据掩膜，边框表示允许域及判定；黄色为参考质心/轴，青色为当前质心/轴。标题显示 ID、检查名、值和上下限。输出带标题边，标记 `visualization_only=true`，不能当作原坐标的算法输入。

边界检查仅覆盖明确的观察域。超出观察域的物体不会被该槽的局部检查完整测量；搜索余量、相邻槽覆盖及整盘检查应按场景配置。

## 正面线扫配方

配准和检查使用 2500×2048 概览图，原图为 20000×16384。像素阈值属于概览图，不能直接当成原图像素或 mm；读码仍用原图采样。

| 检查 | 测量来源 | 当前验证阈值 |
|---|---|---|
| 参考有效性 | 参考前景面积 | ≥500 px² |
| 参考允许域核对 | 参考前景减允许域，除参考面积 | ≤0.02 |
| 缺失 | 参考减当前，除参考面积 | ≤0.05 |
| 多出 | 当前减参考，除参考面积 | ≤0.05 |
| 质心偏移 | 当前/参考前景质心距离 | ≤8 px |
| 主轴角差 | 当前/参考无向主轴夹角 | ≤3° |
| 超出允许 ROI | 当前前景减允许域，除当前面积 | ≤0.02 |

分割为灰度阈值80后的深色前景；容差2 px，观察域余量8 px。以上均为现有验证配方参数，不是已验收的工业公差。

`reference.png` 是正常图在配准坐标下的参考前景来源。当前允许多边形尚需按实际槽壁或允许放置范围标定。与参考轮廓一致不等于已经证明放入槽内；二维比较也不能保证识别所有翘起。单张正常图与受控扰动只能验证链路和计算，实际误报/漏报率必须由独立现场正常、偏移、倾斜、越槽、空槽及翘起样本验收。

现场核对顺序：托盘定位 → 18槽允许 ROI → 当前/参考分割 → 参考有效性 → 各项数值和证据图 → 汇总 → 正常槽读码。先核对分割是否代表工件，再调整阈值，不能用宽阈值掩盖错误分割。

## 预览与资源

- 每项检查分别连接 Value Preview 和 Gallery Preview。Value Preview 的表格 Columns 可配置显式 `path`，例如 `result.value`、`result.maximum`；Key 是表格列键。显示字段投影保留原始行及 `item_id`，避免破坏已有几何关联。没有 Path 时保持原有顶层字段读取，缺失路径显示空值，不修改输入的业务数据。
- 检测内部复用 Run 内 raw image-ref，不把中间二值图逐次 PNG 编码后再解码。Binary Threshold 改用已有矩阵输出路径；显式保存仍遵循原保存行为。
- 图像与掩膜由 ExecutionImageRegistry 管理，随 Run 释放。证据图不作为判定输入，可禁用完整证据组。仅关闭 Gallery Preview 不会自动关闭其上游绘图节点；需要时显式禁用整个证据组。
- 不改 Runtime、Trigger、训练或模型推理调度协议。完整工作流节拍须另行测量，检测子链耗时不能替代包含原图加载、定位和读码的总耗时。

实施与实图验证记录见 [正面独立检查验证](../operations/linescan-front-inspection-primitives-20261029.md)。
