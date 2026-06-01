# YOLOE 与 SAM3 节点资产规范

## 文档目的

本文档用于固定 `YOLOE` 和 `SAM3` 第一阶段作为 `custom node` 接入时的磁盘资产规则、`manifest.json` 最低字段，以及 workflow 节点输入输出 contract。

本文档只讨论：

- 预训练模型和附属资产放在哪里
- 目录层级和命名怎么定
- `manifest.json` 至少要写什么
- `custom node` 第一阶段应使用哪些 payload contract
- preview run、`WorkflowAppRuntime` 和 `DeploymentInstance` 三种运行形态的关系

本文档不展开：

- 节点推理代码实现细节
- workflow app 改造
- 核心模型主链的训练、转换、发布接入

## 适用范围

- `custom_nodes/yoloe_open_vocab_nodes`
- `custom_nodes/sam3_segment_nodes`
- `data/files/models/pretrained/yoloe`
- `data/files/models/pretrained/sam3`

## 核心结论

- `YOLOE` 和 `SAM3` 第一阶段都应作为 `custom node` 扩展能力接入，不直接并入当前核心模型主链。
- 大权重和附属模型资产继续统一放在 `data/files/models/pretrained/` 下，不放进 `custom_nodes/`。
- `YOLOE` 第一阶段先使用官方 segmentation 权重接 open vocabulary detection 节点，`SAM3` 第一阶段先只开 image segmentation。
- `YOLOE` 和 `SAM3` 在 workflow 中的第一阶段运行形态应为：`WorkflowAppRuntime` 进程内按需首次加载并缓存，runtime 停止时释放；不是每次调用重新加载，也不是一开始就做成正式 `DeploymentInstance` 常驻服务。
- `YOLOE` 第一阶段节点输出继续复用 `detections.v1`；`SAM3` 输出应使用新的 `regions.v1`，不要硬塞进 `detections.v1`。

## 参考实现来源

### YOLOE

- `projectsrc/ultralytics/ultralytics/models/yolo/yoloe/predict.py`
- `projectsrc/ultralytics/ultralytics/nn/tasks.py`
- `projectsrc/ultralytics/ultralytics/nn/modules/head.py`
- `projectsrc/ultralytics/ultralytics/nn/modules/block.py`

### SAM3

- `projectsrc/ultralytics/ultralytics/models/sam/build_sam3.py`
- `projectsrc/ultralytics/ultralytics/models/sam/sam3/sam3_image.py`
- `projectsrc/ultralytics/ultralytics/models/sam/predict.py`

## 与现有模型主链的关系

### YOLOE

- 与现有 `YOLOv8/11/26` 有结构血缘关系，但不是当前核心 detection 主链里的同层正式模型分类。
- `text prompt`、`visual prompt`、`prompt-free` 是节点运行模式，不是三套独立平台模型分类。
- 官方当前提供的是 `-seg` 权重，它本质上是 open-vocabulary instance segmentation 模型。
- 第一阶段 custom node 先把它作为 detection 节点使用，直接复用 bbox 结果，先不把 mask 输出开放到平台正式 contract。
- 第一阶段不直接接训练、转换、`DeploymentInstance` 主链。

#### 为什么目录放在 segmentation，而节点先做 detection 输出

- 目录的 `task_type` 表达的是权重本身的真实属性，不是第一阶段节点的输出形式。
- 官方 `YOLOE` 预训练权重文件名就是 `*-seg.pt` / `*-seg-pf.pt`，对应的是 open-vocabulary instance segmentation 权重。
- 这些权重在一次前向里同时包含 bbox、score、label，以及可继续扩展使用的 mask 相关能力。
- 第一阶段 custom node 先只开放 detection 风格输出，也就是 `detections.v1`，因为当前平台先需要稳定的文本提示、视觉提示和 prompt-free 检测节点。
- 因此：
  - 磁盘资产目录保持 `yoloe/segmentation/...`
  - 节点输出 contract 第一阶段仍然可以是 `detections.v1`
- 不能因为当前节点先只输出 bbox，就把官方 segmentation 权重误记成 detection 目录；那样会在后续开放 mask 输出、补 `regions.v1` 或继续做 `YOLOE segmentation` 节点时造成理解混乱。

### SAM3

- 不属于现有 `yolo_primary segmentation` 的同层实现。
- `semantic` 和 `interactive` 是节点运行模式，不是两套独立权重目录。
- 第一阶段不直接接训练、转换、`DeploymentInstance` 主链。

## 磁盘资产放置规则

- 所有大权重、tokenizer、embedding 缓存和配置文件都放在 `data/files/models/pretrained/` 下。
- `custom_nodes/` 目录只放节点包源码、catalog、schema 和文档，不放大权重。
- `data/files/models/pretrained/` 属于本地数据目录，仓库只保留生成规则和维护命令，不把大权重和生成产物纳入源码提交。
- 目录规则保持和项目现有预训练模型目录一致：

```text
{root}/{model_type}/{task_type}/{scale}/{variant}/manifest.json
{root}/{model_type}/{task_type}/{scale}/{variant}/checkpoints/{file}
```

- 第一阶段继续使用统一 scale 命名：
  - `nano`
  - `tiny`
  - `s`
  - `m`
  - `l`
  - `x`
  - `xx`
- 不再引入旧的 `n`。

## 官方权重名与项目目录的关系

- `YOLOE` 官方文档直接提供权重文件，例如：
  - `yoloe-v8s-seg.pt`
  - `yoloe-11s-seg.pt`
  - `yoloe-26n-seg.pt`
  - prompt-free 变体使用 `*-seg-pf.pt`
- `SAM3` 第一阶段按官方单权重文件 `sam3.pt` 组织。

这里要分清两层：

- 权重文件名：尽量保持官方文件名不变，方便直接下载后放入目录
- 节点运行模式：`text prompt`、`visual prompt`、`semantic`、`interactive` 这些属于节点使用方式，不应全部编码进磁盘目录层级

因此第一阶段目录只对“真正需要不同权重的变体”做区分：

- `YOLOE default`
- `YOLOE prompt-free`
- `SAM3 default`

## 第一阶段目录规则

### YOLOE

第一阶段先创建已确认的最小目录骨架：

```text
data/files/models/pretrained/
└─ yoloe/
   └─ segmentation/
      ├─ s/
      │  ├─ v8-default/
      │  │  ├─ manifest.json
      │  │  └─ checkpoints/
      │  │     └─ yoloe-v8s-seg.pt
      │  ├─ v8-prompt-free/
      │  │  ├─ manifest.json
      │  │  └─ checkpoints/
      │  │     └─ yoloe-v8s-seg-pf.pt
      │  ├─ 11-default/
      │  │  ├─ manifest.json
      │  │  └─ checkpoints/
      │  │     └─ yoloe-11s-seg.pt
      │  └─ 11-prompt-free/
      │     ├─ manifest.json
      │     └─ checkpoints/
      │        └─ yoloe-11s-seg-pf.pt
      └─ nano/
         ├─ 26-default/
         │  ├─ manifest.json
         │  └─ checkpoints/
         │     └─ yoloe-26n-seg.pt
         └─ 26-prompt-free/
            ├─ manifest.json
            └─ checkpoints/
               └─ yoloe-26n-seg-pf.pt
```

说明：

- `v8-default` 和 `11-default` 供文本提示、视觉提示节点共用。
- `v8-prompt-free`、`11-prompt-free`、`26-prompt-free` 对应真正不同的 prompt-free 权重。
- `YOLOE` 的官方权重是 segmentation 权重。
- 第一阶段节点仍先输出 `detections.v1`，原因是当前扩展节点主线先落文本提示、视觉提示和 prompt-free 检测。
- 后续如果开放 `YOLOE` 的 mask 输出，同一批权重目录可以继续复用，不需要再换一套资产规范。
- 后续如果补 `m / l / x` 等其他官方权重，继续沿同一规则扩展，不另起新目录规范。

### SAM3

第一阶段先创建已确认的最小目录骨架：

```text
data/files/models/pretrained/
└─ sam3/
   └─ segmentation/
      └─ l/
         └─ default/
            ├─ manifest.json
            └─ checkpoints/
               └─ sam3.pt
```

说明：

- `semantic` 和 `interactive` 先共用同一份 `sam3.pt`。
- 如果后续出现新的正式上游权重，再按同一规则追加 variant。

## manifest.json 最低字段

`YOLOE` 与 `SAM3` 第一阶段都使用项目现有的预训练目录 `manifest.json` 约定，不引入新的 `variant.json`。

最低字段如下：

- `model_name`
- `model_scale`
- `task_type`
- `model_version_id`
- `checkpoint_file_id`
- `checkpoint_path`
- `metadata`

### 字段说明

| 字段 | 说明 |
| --- | --- |
| `model_name` | 预训练模型家族名，例如 `yoloe-v8`、`yoloe-11`、`yoloe-26`、`sam3` |
| `model_scale` | 项目统一 scale，例如 `nano`、`s`、`l` |
| `task_type` | `YOLOE` 与 `SAM3` 第一阶段都固定写 `segmentation` |
| `model_version_id` | 预训练目录的稳定 `ModelVersion` id |
| `checkpoint_file_id` | 预训练 checkpoint 的稳定文件 id |
| `checkpoint_path` | 相对 `manifest.json` 的 checkpoint 路径 |
| `metadata.catalog_name` | 当前目录使用的变体名 |
| `metadata.entry_name` | 当前条目显示名 |
| `metadata.source` | 当前来源，建议固定写 `local-pretrained` |
| `metadata.upstream_weight_name` | 官方权重文件名 |
| `metadata.upstream_mode` | 官方或项目约定的权重模式，例如 `default`、`prompt-free` |

### YOLOE manifest.json 示例

```json
{
  "model_name": "yoloe-v8",
  "model_scale": "s",
  "task_type": "segmentation",
  "model_version_id": "mv-pretrained-yoloe-v8-segmentation-s",
  "checkpoint_file_id": "mf-pretrained-yoloe-v8-segmentation-s-checkpoint",
  "checkpoint_path": "checkpoints/yoloe-v8s-seg.pt",
  "metadata": {
    "catalog_name": "v8-default",
    "entry_name": "v8-default",
    "source": "local-pretrained",
    "upstream_weight_name": "yoloe-v8s-seg.pt",
    "upstream_mode": "default"
  }
}
```

### SAM3 manifest.json 示例

```json
{
  "model_name": "sam3",
  "model_scale": "l",
  "task_type": "segmentation",
  "model_version_id": "mv-pretrained-sam3-segmentation-l",
  "checkpoint_file_id": "mf-pretrained-sam3-segmentation-l-checkpoint",
  "checkpoint_path": "checkpoints/sam3.pt",
  "metadata": {
    "catalog_name": "default",
    "entry_name": "default",
    "source": "local-pretrained",
    "upstream_weight_name": "sam3.pt",
    "upstream_mode": "default"
  }
}
```

## 与当前预训练自动登记链的关系

- 当前核心平台自动扫描并登记的预训练目录仍然是 `yolox / yolov8 / yolo11 / yolo26 / rfdetr`。
- `YOLOE` 和 `SAM3` 第一阶段只是 custom node 使用的中心化磁盘资产，不进入当前核心模型自动登记链。
- 也就是说，本文件定义的是“节点运行时如何找权重”，不是“当前平台把它们当正式核心模型分类管理”。
- 如果需要批量校验和重生这两类目录的 `manifest.json`，统一通过 `python -m backend.maintenance.main sync-extension-pretrained-manifests` 执行。

## 第一阶段 payload contract

第一阶段先固定三种扩展 payload contract：

- `text-prompts.v1`
- `prompt-regions.v1`
- `regions.v1`

### text-prompts.v1

用途：

- `YOLOE` 文本提示检测
- `SAM3` 语义分割

最小字段建议：

- `items`
- 每项包含：
  - `prompt_id`
  - `text`
  - `display_name`
- 可选：
  - `language`
  - `negative`

### prompt-regions.v1

用途：

- `YOLOE` 视觉提示检测
- `SAM3` 交互分割

最小字段建议：

- `source_image`
- `items`
- 每项包含：
  - `prompt_id`
  - `prompt_kind`
  - `point_xy`
  - `point_label`
  - `bbox_xyxy`
  - `polygon_xy`
  - `mask_image`

说明：

- `prompt_kind` 允许：
  - `point`
  - `box`
  - `polygon`
  - `mask`
- `mask_image` 建议继续复用 `image-ref.v1`，不要把整张 mask 内联到 JSON。

### regions.v1

用途：

- `SAM3` 输出
- 后续也可给其他 region/mask 类扩展节点复用

最小字段建议：

- `source_image`
- `count`
- `items`
- 每项包含：
  - `region_id`
  - `score`
  - `class_name`
  - `bbox_xyxy`
  - `polygon_xy`
  - `mask_image`
  - `area`

说明：

- `mask_image` 建议继续使用 `image-ref.v1`
- `polygon_xy` 供独立预览节点、结果导出节点和规则节点复用

## 节点输入输出 contract

### YOLOE

- `custom.yoloe.text-prompt-detect`
  - 输入：`image-ref.v1`、`text-prompts.v1`
  - 输出：`detections.v1`、`value.v1`
- `custom.yoloe.visual-prompt-detect`
  - 输入：`image-ref.v1`、`image-ref.v1(prompt_image)`、`prompt-regions.v1`
  - 输出：`detections.v1`、`value.v1`
- `custom.yoloe.prompt-free-detect`
  - 输入：`image-ref.v1`
  - 输出：`detections.v1`、`value.v1`

### SAM3

- `custom.sam3.semantic-segment`
  - 输入：`image-ref.v1`、`text-prompts.v1`
  - 输出：`regions.v1`、`value.v1`
- `custom.sam3.interactive-segment`
  - 输入：`image-ref.v1`、`prompt-regions.v1`
  - 输出：`regions.v1`、`value.v1`

## 运行形态约定

### preview run

- 单次执行
- 允许一次性加载和释放模型

### WorkflowAppRuntime

- runtime 进程长期运行
- 模型会话应在当前 runtime 进程内按需首次加载并缓存
- runtime 停止时统一释放
- 不做跨 runtime 共享

### DeploymentInstance

- 第一阶段不作为 `YOLOE` 和 `SAM3` 的默认接入方式
- 只有当输入输出语义、现场调用模式和资源占用都稳定后，才考虑把某个固定变体提升为正式长期运行推理服务

## 第一阶段不做的事

- 不把 `YOLOE` 和 `SAM3` 并入当前核心模型训练、转换、`DeploymentInstance` 主链
- 不做 workflow app 文档或旧模板修补
- 不在节点中内置预览、overlay 或 debug 叠图逻辑
- 不实现视频版 `SAM3`
- 不在第一阶段接 `YOLOE segmentation`

## 后续实现顺序

1. 固定本文件中的磁盘资产规则、`manifest.json` 字段和 payload contract
2. 先做 `YOLOE custom node`
3. 再做 `SAM3 custom node`
4. 运行边界稳定后，再评估是否把某些固定变体提升为正式长期运行服务
