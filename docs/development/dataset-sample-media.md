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
| `point-cloud` | `cloud`（PLY 文件）、`unit`、`frame`（来源坐标系） | PLY 1.0 必须只有一个 vertex 元素，支持 ASCII、大小端二进制、XYZ 标量坐标和可选 red/green/blue。不接受 face、其他元素或 list 属性，不忽略其正文。面板区分总点、有效点和无效点；缺失 RGB 时使用高度或单色。可旋转、缩放、切换视角、投影和点大小。原始 PLY 随版本保存。 |

深度和点云单位支持 mm、m。深度无效像素显示为黑色。点云遇到非有限 XYZ 时保留原文件和无效点数；显示端从有效点确定性抽样，最多 50,000 点。原始文件与工作站缩略图分开保存。预览中的标注和高度着色属于数据查看，尺寸测量与生产判定仍由 Workflow 执行。

## 服务接口与版本

- `GET /api/v1/system/bootstrap` 发布四类任务及导入家族 `amvision-media`。沿用 `POST /api/v1/datasets/imports` 的权限、队列、错误报告和取消机制。
- 样本详情 `metadata.sample_media` 提供任务资料和登记的附件键。`GET /api/v1/datasets/{dataset}/versions/{version}/samples/{sample}/image?asset={key}` 按样本身份与读权限获取一个附件。可用键包括 mask、mask-preview、calibration、depth、depth-values、depth-preview、cloud、points；缺少的键返回 404。`depth-values` 是深度图原生行顺序的小端 uint16；`points` 是每点 6 个小端 float32（居中缩放的 XYZ，加上归一化 RGB），物理坐标由 `origin + xyz × scale` 恢复。
- 在当前版本保存增删后 vN 不变。手动创建的新版本独立拥有全部附件。四种原格式导出分别使用 `amvision-anomaly-v1`、`amvision-connector-reference-v1`、`amvision-rgbd-v1`、`amvision-point-cloud-v1`。导出保留原件，重新导入时再生成显示数据。不同批次的同名样本可以并存。导出范围内的配对 ID 重复时分配唯一 ID，并在 `origin_id` 保留原 ID。
- 实施上限为清单 8 MiB、单个源文件 128 MiB、标定 JSON 1 MiB、图片 16,777,216 像素、点云 200 万顶点，单包归一化素材 4 GiB。原有 ZIP 解包及项目空间限制也继续生效。
- 使用已有数据库元数据字段，无表结构迁移。开发环境需使 HTTP 和数据集 worker 同时加载新代码。前端沿用本地 Vue/Three.js 资源，支持离线使用。

## 严格读取与版本比较

- 数据集 PLY 直接复用受控 `trimesh==5.1.1+amvision.2` 的头部和正文读取接口，不自行解析 PLY、不回退其他库。缺失或版本不符属于服务配置错误，不误报为坏文件。开发 conda 与发行自带 Python 均需安装该受控 wheel。
- 拒绝截断、额外记录/尾部数据、重复字段、非法数字、整数越界和浮点溢出；保留声明的字段类型、float32/float64 精度及原文件字节。非有限 XYZ 继续按无效观测计数，但不能借显示过滤跳过 RGB 数据校验。
- 版本比较按稳定样本来源匹配，原始附件逐字节比较。变化类型新增 `cloud`、`depth`、`mask`、`calibration`、`media_metadata`，分别表示原始点云、深度、掩膜、标定文件及公开样本语义变化；保留现有 `image`、`annotations`、`categories`、`split` 等类型。
- `media_metadata` 覆盖单位、深度比例/无效值/配准说明、坐标系、PIN、设计节距、参考测量、异常标签和来源说明等公开字段。排除包内文件路径、样本编号、派生统计和预览字段。
- 点云缩略图和抽样显示重建不代表原云变化；原云不同但预览相同仍须报告变化。登记的原始附件缺失时比较任务失败，不能显示“无变化”。摘要分块读取沿用 worker 的续租与取消检查。
- 比较结果继续使用现有 Task/Outbox/worker 和前端结果组件，中英文显示新增类型，点击样本仍进入被比较版本。该次修复不改变测量算法、训练或模型推理实现。
- 已导入的数据不自动重写或删除；历史点云如需确认正文完整性，应经严格入口重新导入验证。共享依赖校验移至后端基础设施层，三维节点和数据集调用同一版本检查；受影响的既有三维发布继续按平台指纹规则校验，失配时审核重发，不绕过准入。

## 本轮修复验证（2026-11-12）

- Windows 后端组合回归 214 项通过，覆盖数据集导入/导出、原始附件比较、选择和工作区操作、草稿生命周期、项目删除、维护及受控 PLY；独立三维发布输入错误与恢复链路另有 1 项通过。
- HTTP 草稿上传、正式导入 worker、坏文件失败且不生成版本、正常点云导出重读、派生版本原云变化的比较任务均由隔离数据库和受管存储验证，不以替换处理函数的夹具冒充实际链路。
- 草稿测试包含跨项目/用户隔离、跨进程活动锁、子进程异常退出、失败归还、过期分组回收、旧目录退役、维护入口和项目删除准入。
- 前端数据集模块 21 个测试文件、48 项通过；新增比较类型覆盖中文/英文、目标版本跳转。测试样例补齐公开任务字段后，新增 2 项再次通过。
- Vue/TypeScript 类型检查、变更 Python 文件 Ruff 和 `git diff --check` 均通过。未运行性能和长稳测试；验收使用的临时数据库、输入文件和进程在结束后清理。
- 本轮未重新执行 WSL、性能或长稳验收，也未修改生产数据库、受控 wheel 或既有发行包。
