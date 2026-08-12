# VOC 实例分割数据集格式

## 范围

`voc-instance-seg-v1` 表示使用 `SegmentationObject` indexed PNG 定义实例、使用
`SegmentationClass` indexed PNG 定义类别的 VOC 实例分割格式。该格式支持导入和
导出，平台内部统一保存为 0-based pixel 几何和 compressed COCO RLE。

支持直接 VOC 根，也支持以下包裹层：

- `VOC2007/`、`VOC2012/`
- `VOCdevkit/VOC2007/`、`VOCdevkit/VOC2012/`
- zip 内的额外单目录包装层

## 标准目录

```text
VOC2012/
├─ Annotations/
├─ JPEGImages/
├─ SegmentationClass/
├─ SegmentationObject/
└─ ImageSets/
   └─ Segmentation/
      ├─ train.txt
      ├─ val.txt
      ├─ trainval.txt
      └─ test.txt              # 可选
```

每个 split 成员必须同时存在同 stem 的 JPEG、XML、class mask 和 object mask。
`train.txt` 与 `val.txt` 必须互斥；存在 `trainval.txt` 时必须等于两者并集。

## 标注事实来源

实例分割的权威顺序固定如下：

1. `SegmentationObject` 中除 0 和 255 外的索引定义实例像素。
2. 同一实例像素在 `SegmentationClass` 中必须得到唯一有效类别。
3. bbox 和 area 从实例 mask 计算，使用 0-based、右下 exclusive 的 xywh。
4. mask 按 Fortran order 编码为 compressed COCO RLE，保留孔洞和不连通区域。
5. XML 不覆盖 mask 的类别、bbox 或 area，只补充 `difficult`、`truncated`、
   `pose` 和源位置等审计元数据。

VOC XML 没有坐标声明时仍按项目默认的 0-based、xmax/ymax exclusive 解释；只有
XML 明确声明官方 Pascal VOC 语义时才使用 1-based、inclusive。由于实例几何来自
mask，XML 坐标约定不会改变 canonical mask bbox。

## XML 与 mask 不一致

XML object 与 mask 只在相同类别中按最大总 bbox IoU 做一对一匹配，不设置会丢弃
小目标的固定 IoU 阈值。mask 数量多于 XML 时，未匹配 mask 仍完整导入但不继承
XML 元数据；XML 数量更多时，未匹配 XML 只记录警告，不创建没有 mask 的实例。

以下问题会阻止导入：

- 必需目录或配套文件缺失
- PNG 不是 `P/L` 单通道 indexed PNG
- 图片、XML、class mask、object mask 尺寸不一致
- 一个实例包含零个或多个有效 class id
- 自定义 class id 无法通过 XML 得到稳定类别名
- 类别映射为空或同一 class id 在不同样本中映射冲突
- split 重叠、重复或 trainval 并集不一致

以下问题作为可追溯警告，不删除 mask：

- `VOC_SEGMENTATION_XML_INSTANCE_COUNT_MISMATCH`
- `VOC_SEGMENTATION_XML_CLASS_COUNT_MISMATCH`
- `VOC_SEGMENTATION_XML_OBJECT_UNMATCHED`

## 导出规则

VOC 导出生成 `Annotations`、`JPEGImages`、`SegmentationClass`、
`SegmentationObject` 和 `ImageSets/Segmentation`。class/object mask 使用官方 VOC
palette；官方 20 类优先复用 1–20 索引，自定义类别使用剩余索引。

indexed PNG 不能表达重叠实例，也不能在单张图片中表达超过 254 个实例。出现这两种
情况时导出明确失败，不做静默覆盖。polygon 和 COCO RLE 都先还原为二值 mask，再
写入 indexed PNG。XML 使用项目默认 0-based/exclusive 坐标并写入明确声明。

导出 COCO instance segmentation 可无损保留 RLE。YOLO segmentation 单行不能表达
RLE、孔洞或多个独立 polygon，现有 YOLO 导出器会明确拒绝不能无损表达的样本。

## VOC2012 开发基准

标准开发副本位于 `data/files/datasets/segmentation/voc2012`。可独立执行：

```powershell
python -m backend.maintenance.voc_instance_segmentation_dataset
python -m backend.maintenance.voc_instance_segmentation_dataset --apply
```

第一条命令只核对源文件和目标文件并预览 split；第二条命令补齐 XML、生成独立
test split 并写入 `amvision-voc-instance-segmentation.json` 全量报告。维护命令不会
修改官方源目录。图片、mask 和 XML 必须与官方源逐字节一致，否则停止；开发副本的
split 清单是唯一允许派生的内容。

官方 train 保持不变。官方 val 使用命名空间
`amvision-voc2012-segmentation-val-test-v1` 对样本 id 计算 SHA-256，按 digest 和样本
id 稳定排序后等分：前 50% 为 test，其余为 validation。`official-val.txt` 保留原始
官方 val，报告记录算法、命名空间、比例和计数。train、validation、test 三者互斥，
官方 train 不参与 test；重复执行得到相同清单。

2026-08-10 全量结果：

- 2,913 张图片
- train 1,464，validation 725，独立 test 724
- 6,934 个 mask 实例
- 20 个类别
- 22 条 XML/mask 对照警告，涉及官方数据中 8 张图片
- 0 个 mask 解析错误

这 22 条警告说明 XML 不能作为 VOC instance segmentation 的实例事实来源；完整警告
和文件名保存在开发副本的报告中。
