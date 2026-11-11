# 异常、连接器、RGB-D 和点云样本

在「数据集 → 导入数据集」选择 ZIP，向导根据 samples.json 识别连接器、RGB-D 和点云，数据定义中只读显示数据类型。这三类用于保存和查看 Workflow 工程样本，不作为模型任务选项；普通连接器训练图片按检测、分类等实际任务导入。「ZIP 清单格式」提供该任务的最小示例。查看固定版本后双击样本，使用“样本信息”或“参考资料”打开右侧面板。导出文件可以重新导入。

## ZIP 清单

包根放置 UTF-8 的 `samples.json`，也可把整个包放在一个外层目录。格式标识固定为 `amvision.sample-media.v1`。同一包内的样本属于同一种任务。路径使用包内相对路径及正斜杠。每条记录需要唯一的 `id` 和 `split`（train、val、test），可填写 `source`。图片支持 JPEG、PNG。

```json
{
  "format_id": "amvision.sample-media.v1",
  "task_type": "rgbd",
  "samples": [
    {"id":"frame_0042","split":"val","image":"rgb/0042.jpg","depth":"depth/0042.png","unit":"mm","scale":1,"invalid":0,"alignment":"unknown"}
  ]
}
```

其他任务使用同一外层结构，更换 `task_type` 和样本字段。

| 任务 | 必需字段 | 可选资料与查看方式 |
| --- | --- | --- |
| `anomaly` | `image`、`label`（normal 或 anomaly） | `defect` 是异常类型，`category` 是用于筛选的类别名。可选 `mask` 是与原图同尺寸的单通道 PNG，0 表示背景，1 或 255 表示标注区域。查看器按原像素叠加并允许隐藏。没有区域时只显示图像级标签。预测结果单列。 |
| `connector-reference` | `image`、`synthetic`（布尔值）、`unit`（mm 或 m） | `pins` 为 `[{"id":"P1","x":120,"y":80}]`，位置以原图左上角为原点。编号可隐藏。`pitch` 是设计节距，`plane` 是参考平面说明。独立实测量填入 `measured`，每项包含 `name/value/unit/source`。标定 JSON 通过 `calibration` 引用。无独立实测时面板明确显示“未提供”。 |
| `rgbd` | `image/depth/unit/scale/invalid` | 深度文件是 16 位单通道 PNG，物理深度等于原始计数乘以 scale，无效原值单独处理。保留两幅图的原生尺寸。RGB、深度和并排三种视图可切换，悬停读取深度图自己的像素坐标。`alignment` 接受 unknown、unregistered、registered；registered 表示输入已配准，要求一并提供 `calibration` JSON。导入不执行重投影。 |
| `point-cloud` | `cloud`（PLY 文件）、`unit`、`frame`（来源坐标系） | PLY 1.0 的首元素须为 vertex，支持 ASCII、大小端二进制、XYZ 标量坐标和可选 red/green/blue。只呈现顶点。面板区分总点、有效点和无效点；缺失 RGB 时使用高度或单色。可旋转、缩放、切换视角、投影和点大小。原始 PLY 随版本保存。 |

深度和点云单位支持 mm、m。深度无效像素显示为黑色。点云遇到非有限 XYZ 时保留原文件和无效点数；显示端从有效点确定性抽样，最多 50,000 点。原始文件与工作站缩略图分开保存。预览中的标注和高度着色属于数据查看，尺寸测量与生产判定仍由 Workflow 执行。

## 服务接口与版本

- `GET /api/v1/system/bootstrap` 发布四类任务及导入家族 `amvision-media`。沿用 `POST /api/v1/datasets/imports` 的权限、队列、错误报告和取消机制。
- 样本详情 `metadata.sample_media` 提供任务资料和登记的附件键。`GET /api/v1/datasets/{dataset}/versions/{version}/samples/{sample}/image?asset={key}` 按样本身份与读权限获取一个附件。可用键包括 mask、mask-preview、calibration、depth、depth-values、depth-preview、cloud、points；缺少的键返回 404。`depth-values` 是深度图原生行顺序的小端 uint16；`points` 是每点 6 个小端 float32（居中缩放的 XYZ，加上归一化 RGB），物理坐标由 `origin + xyz × scale` 恢复。
- 在当前版本保存增删后 vN 不变。手动创建的新版本独立拥有全部附件。四种原格式导出分别使用 `amvision-anomaly-v1`、`amvision-connector-reference-v1`、`amvision-rgbd-v1`、`amvision-point-cloud-v1`。导出保留原件，重新导入时再生成显示数据。不同批次的同名样本可以并存。导出范围内的配对 ID 重复时分配唯一 ID，并在 `origin_id` 保留原 ID。
- 实施上限为清单 8 MiB、单个源文件 128 MiB、标定 JSON 1 MiB、图片 16,777,216 像素、点云 200 万顶点，单包归一化素材 4 GiB。原有 ZIP 解包及项目空间限制也继续生效。
- 使用已有数据库元数据字段，无表结构迁移。开发环境需使 HTTP 和数据集 worker 同时加载新代码。前端沿用本地 Vue/Three.js 资源，支持离线使用。
