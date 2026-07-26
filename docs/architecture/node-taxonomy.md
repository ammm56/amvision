# 节点包边界和节点分类

## 目的

本文档固定 core node、custom node、node pack、节点分类和代码目录之间的关系。节点目录不再按历史开发批次或单个业务场景拆包。

## 四个不同概念

- `implementation_kind` 区分 core node 和 custom node。
- `node_pack_id` 标识可独立安装、启用、禁用、版本化和回滚的能力包。
- `category` 是节点选择器中的多级功能路径，不是 node pack。
- 代码目录反映包内实现边界，不参与公开工作流标识。

`node_type_id` 是工作流长期保存的稳定标识。目录迁移和节点分类调整不得顺带修改已有 `node_type_id`。需要更名时，旧 id 保留隐藏兼容定义，新 id 作为首选定义。

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

禁止按 basic、geometry、measurement 或某个 MES 场景直接创建一级 pack。这些名称应是包内分类或 recipe。

## custom_nodes 目录规则

### 按算法分类

OpenCV 采用 `categories`：

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

未实现的 provider 只写入规划，不放空节点定义，不伪造可执行能力。SQL provider 当前覆盖 SQLite、MySQL 和 PostgreSQL 的受限 upsert。Redis 需要独立依赖、连接规则、key namespace 和超时规则，完成后再加入 catalog。

### 按业务配置分类

HTTP 采用 `recipes`：

```text
custom_nodes/http_nodes/
├─ backend/
├─ workflow/
└─ recipes/
   └─ mes/
```

HTTP Request 是公开通用节点。MES 提交是参数模板和字段映射场景，不作为 pack 名或首选 node type。旧 `custom.output.mes-http-post` 只用于读取已有流程。

## manifest 规则

统一 pack 使用以下显式字段：

- `categoryRoot`：包内所有节点 `category` 的根路径。
- `implementationLayout`：`flat`、`categories`、`providers` 或 `recipes`。
- `migrationAliases`：被当前 pack 替代的旧 pack id。

加载器校验每个节点的 `category` 必须位于 `categoryRoot` 下。这样可以避免 Database 节点重新落入 `integration.output`，也可以避免 Camera provider 在目录中成为新的一级 pack。

## core node 边界

core 只保留工作流引擎稳定运行所需的通用数据、控制、平台服务和视觉规则，不直接承载第三方 SDK 或外部系统协议。

core 顶层分类固定为：

- `io`：输入、输出、文件、图片、视频、模板边界。
- `logic`：值、布尔、集合、对象、循环、状态和规则。
- `vision`：与具体第三方视觉库无关的 ROI、region、连续性、装配和缺陷规则。
- `model`：已部署模型的通用推理边界。
- `service`：数据集、任务、部署和模型任务等平台服务调用。
- `inspection`：工业结果记录和汇总对象。
- `ui`：预览和调试显示。

`support` 目录只放实现 helper，不生成节点，不出现在目录。

core 物理目录必须与公开分类同义。当前输出节点归入：

```text
backend/nodes/core_nodes/io/output/
├─ records/
├─ response/
├─ storage/
└─ http/        # 仅保留旧流程兼容实现
```

规则节点归入 `backend/nodes/core_nodes/logic/rules/`。旧 core HTTP Post 从节点选择器隐藏，新流程使用 `custom.http.request`。

## 节点选择器

节点选择器固定为三段：

1. 来源：Core Nodes 或一个完整 node pack。
2. 分类树：按 `category` 的根路径和子路径展示。
3. 节点：显示节点名、完整分类、说明和稳定 `node_type_id`。

`metadata.catalogHidden=true` 的兼容节点参与旧流程校验和执行，但不出现在新增节点入口。

## 当前迁移

| 旧 pack | 新 pack | 包内位置 |
| --- | --- | --- |
| `opencv.*-nodes` 七个包 | `opencv.nodes` | `categories/*` |
| `camera.usb-uvc-nodes` | `camera.nodes` | `providers/usb_uvc` |
| `output.local-db-nodes` | `database.nodes` | `providers/sql` |
| `output.mes-http-nodes` | `http.nodes` | `recipes/mes` |

已有 OpenCV 和 Camera 的 `node_type_id` 保持不变。HTTP 新增 `custom.http.request`，Database 新增 `custom.database.sql.upsert`；旧 `custom.output.*` id 均保留隐藏兼容定义。

## 设计参考

- [ComfyUI Custom Nodes](https://docs.comfy.org/custom-nodes/walkthrough) 使用 category 决定节点菜单位置，并支持路径形式的多级分类。
- [Dify Tool Plugin](https://docs.dify.ai/en/develop-plugin/dev-guides-and-walkthroughs/tool-plugin) 将一个 provider 和多个 tools 放在同一个插件工程中。
- [HALCON Operator Reference](https://www.mvtec.com/doc/halcon/2511/en/index.html) 使用稳定的功能层级组织大量视觉算子，而不是把每个小分类变成独立插件。
