# 节点包边界和节点分类

## 目的

本文档固定 core node、custom node、node pack、节点分类和代码目录之间的关系。节点目录不再按历史开发批次或单个业务场景拆包。

## 四个不同概念

- `implementation_kind` 区分 core node 和 custom node。
- `node_pack_id` 标识可独立安装、启用、禁用、版本化和回滚的能力包。
- `category` 是节点包内严格两级的功能分类，不是 node pack。公开 key 使用
  `<namespace>.<root>.<child>`。
- 代码目录反映包内实现边界，不参与公开工作流标识。

`node_type_id` 是工作流保存的节点标识。开发阶段发生职责或命名调整时，直接更新节点定义、模板、应用、测试和文档，不保留隐藏兼容节点。进入正式发布阶段后，再通过显式版本迁移管理公开 id 变化。

## node pack 拆分规则

一个 node pack 应对应一个稳定的技术域、能力提供方或需要独立管理的运行时边界。

以下情况放在同一个 pack：

- 使用同一基础库并共享大部分 payload、runtime helper 和权限，例如 OpenCV。
- 使用同一协议，但包含多种常用操作，例如 HTTP request、response 解析和鉴权。
- 属于同一设备域，但需要适配多个 provider，例如 USB/UVC、Hikvision MVS 相机。
- 属于同一数据访问域，但需要适配多个 backend，例如 SQL 和 Redis。

以下情况才拆成不同 pack：

- 依赖、许可证、运行环境或故障边界必须独立管理。
- 权限范围明显不同，不能安全地一起启用。
- 版本和发布周期长期独立。
- 实现来自不同厂商，且安装一个 provider 不应加载另一个 provider 的 SDK。此时可以拆 provider pack；目录和分类仍保持统一命名。

禁止按 basic、geometry、measurement、单个协议或某个业务场景直接创建一级 pack。这些名称应是包内分类、provider 或 protocol。

## custom_nodes 目录规则

### 按实现模块分类

OpenCV 和 Barcode 采用 `categories`。物理目录用于组织实现模块，不直接决定公开
`category`。一个实现模块可以包含多个公开的两级分类：

```text
custom_nodes/opencv_nodes/
├─ manifest.json
├─ backend/entry.py
├─ workflow/catalog.json
├─ shared/
└─ categories/
   ├─ basic/
   ├─ geometry/
   ├─ shape/
   ├─ matching/
   ├─ measurement/
   ├─ defect/
   └─ render/

custom_nodes/barcode_nodes/
├─ manifest.json
├─ shared/
└─ categories/
   ├─ decode/
   ├─ compose/
   ├─ logic/
   ├─ render/
   ├─ transform/
   └─ display/
```

### 按实现后端分类

Camera 和 Database 采用 `providers`：

```text
custom_nodes/camera_nodes/providers/
├─ usb_uvc/
└─ hikvision_mvs/

custom_nodes/database_nodes/providers/
├─ sql/
└─ redis/
```

未实现的 provider 不放入 NodeDefinition，不伪造可执行能力。SQL provider 当前覆盖 SQLite、MySQL 和 PostgreSQL 的受限 upsert。Redis 只有在依赖、连接规则、key namespace 和超时规则全部实现后才可加入 catalog。

### 按协议分类

PLC 采用 `protocols`：

```text
custom_nodes/plc_nodes/
├─ manifest.json
└─ protocols/
   └─ modbus_tcp/
```

### 按通用操作分类

HTTP 采用 `categories`：

```text
custom_nodes/http_nodes/
├─ manifest.json
└─ categories/
   └─ request/
```

HTTP Request 是通用节点。MES 提交只是 URL、鉴权和字段映射的一种配置，不形成独立代码目录或 node type。

## manifest 规则

统一 pack 使用以下显式字段：

- `categoryRoot`：包内所有节点 `category` 的命名空间。
- `implementationLayout`：`flat`、`categories`、`providers`、`protocols` 或 `recipes`。

加载器校验每个节点的 `category` 必须位于 `categoryRoot` 下。Core 与 OpenCV
公开分类采用 `<categoryRoot>.<root>.<child>`，例如 `core.model.inference` 和
`opencv.image.color`。`categoryRoot` 是内部命名空间，不在第二列重复显示。
分类不得包含 `/`，也不得在二级分类后继续增加层级。

## OpenCV 两级分类

OpenCV 现行 133 个节点固定归入以下 10 个一级分类、27 个二级分类：

| 一级分类 | 二级分类 | category | 节点数 |
| --- | --- | --- | ---: |
| Image | Color | `opencv.image.color` | 5 |
| Image | Enhancement | `opencv.image.enhancement` | 7 |
| Image | Filter | `opencv.image.filter` | 6 |
| Image | Edge | `opencv.image.edge` | 4 |
| Image | Threshold | `opencv.image.threshold` | 4 |
| Image | Transform | `opencv.image.transform` | 13 |
| Mask | Operation | `opencv.mask.operation` | 7 |
| Mask | Morphology | `opencv.mask.morphology` | 2 |
| Segmentation | Image | `opencv.segmentation.image` | 4 |
| Segmentation | Region | `opencv.segmentation.region` | 5 |
| Feature | Detection | `opencv.feature.detection` | 6 |
| Matching | Feature | `opencv.matching.feature` | 2 |
| Matching | Template | `opencv.matching.template` | 3 |
| Matching | Registration | `opencv.matching.registration` | 3 |
| Geometry | Detection | `opencv.geometry.detection` | 7 |
| Geometry | Contour | `opencv.geometry.contour` | 5 |
| Geometry | Shape | `opencv.geometry.shape` | 10 |
| Calibration | Camera | `opencv.calibration.camera` | 5 |
| Calibration | Pose | `opencv.calibration.pose` | 4 |
| Measurement | Edge | `opencv.measurement.edge` | 2 |
| Measurement | Circle | `opencv.measurement.circle` | 3 |
| Measurement | Geometry | `opencv.measurement.geometry` | 5 |
| Inspection | Statistics | `opencv.inspection.statistics` | 2 |
| Inspection | Batch | `opencv.inspection.batch` | 5 |
| Inspection | Difference | `opencv.inspection.difference` | 3 |
| Output | Render | `opencv.output.render` | 9 |
| Output | Workflow | `opencv.output.workflow` | 2 |

节点标题固定使用 catalog 中的 English `display_name`。语言切换只影响说明、端口、
参数和错误信息，不替换节点标题。

## core node 边界

core 只保留工作流引擎稳定运行所需的通用数据、控制、平台服务和视觉规则，不直接承载第三方 SDK 或外部系统协议。

Core 现行 160 个节点固定归入以下 9 个一级分类、30 个二级分类：

- IO：Image、File、Input、Response、Video。
- UI：Preview。
- Logic：Condition、Collection、Branch、Iteration、Parallel、Object、Transform、
  Variable、Rule。
- Model：Inference、Lifecycle。
- Dataset：Import、Export。
- Deployment：Runtime。
- Task：Observation。
- Inspection：Record。
- Vision：ROI、Region、Geometry、Position、Assembly、Continuity、Defect、Video。

内部 key 统一使用 `core.<root>.<child>`，例如 `core.model.inference` 和
`core.vision.continuity`。

`support` 目录只放实现 helper，不生成节点，不出现在目录。

core 物理目录必须与公开分类同义。当前输出节点归入：

```text
backend/nodes/core_nodes/io/output/
├─ records/
├─ response/
├─ storage/
```

规则节点归入 `backend/nodes/core_nodes/logic/rules/`。HTTP 调用统一使用 `custom.http.request`，core 不再重复实现外部协议节点。

## 节点选择器

节点目录固定为三列：

1. Source：选择 Core Nodes 或完整 node pack。
2. Category：一级分类显示为不可点击的分组标题，二级分类显示为缩进的可选项。
3. Node：显示所选二级分类中的固定 English 节点名、分类路径、可本地化说明和稳定
   `node_type_id`。

`core`、`opencv` 等 namespace 不在第二列重复显示。界面可以用 `Root / Child`
展示节点所属路径，但 `/` 只用于展示，不写入 `category`。

当前开发阶段的 catalog 只包含现行节点定义，不登记已删除 pack、旧 node type 或隐藏兼容副本。

## 设计参考

- [ComfyUI Custom Nodes](https://docs.comfy.org/custom-nodes/walkthrough) 使用 category 决定节点菜单位置；本项目将公开目录限制为两级，避免无限加深。
- [Dify Tool Plugin](https://docs.dify.ai/en/develop-plugin/dev-guides-and-walkthroughs/tool-plugin) 将一个 provider 和多个 tools 放在同一个插件工程中。
- [HALCON Operator Reference](https://www.mvtec.com/doc/halcon/2511/en/index.html) 使用稳定的功能层级组织大量视觉算子，而不是把每个小分类变成独立插件。
