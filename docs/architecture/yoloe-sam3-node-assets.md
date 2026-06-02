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

workflow app 侧的受控启用、目标机器接入顺序和运维排障，见 [yoloe-sam3-workflow-app-operations.md](yoloe-sam3-workflow-app-operations.md)。

## 当前状态说明

- `YOLOE` 与 `SAM3` 这部分文档当前先固定资产目录、`manifest.json` 规则和节点输入输出 contract。
- `projectsrc/` 只作为参考源码面，不参与运行时。
- `YOLOE` 当前不会回退到已安装官方包或 `projectsrc` 参考代码执行推理；`prompt-free`、`text-prompt`、`visual-prompt` 三条 project-native runtime 已经接通，后续只继续扩能力面。
- `SAM3` 当前已经接通 `interactive-segment` 和 `semantic-segment` 的 project-native runtime，直接读取本地 `sam3.pt` 执行单图分割；其中 `interactive` 当前阶段支持 `box / point / polygon / mask`，`semantic` 当前支持按 `prompt_id` 聚合的 positive/negative `text-prompts.v1`。

## 适用范围

- `custom_nodes/yoloe_open_vocab_nodes`
- `custom_nodes/sam3_segment_nodes`
- `data/files/models/pretrained/yoloe`
- `data/files/models/pretrained/sam3`

## 核心结论

- `YOLOE` 和 `SAM3` 第一阶段都应作为 `custom node` 扩展能力接入，不直接并入当前核心模型主链。
- 大权重和附属模型资产继续统一放在 `data/files/models/pretrained/` 下，不放进 `custom_nodes/`。
- `YOLOE` 第一阶段先使用官方 segmentation 权重接 open vocabulary detection 节点，`SAM3` 第一阶段先只开 image segmentation。
- `YOLOE text-prompt` 第一阶段默认文本编码器固定为本地 `mobileclip_blt.ts`，并复用本地 `CLIP` tokenizer/BPE 资产。
- `YOLOE text-prompt` 当前支持同一 `prompt_id` 下多条 positive/negative 文本组合，运行时会先按 `prompt_id` 聚合，再生成单个类别原型。
- `YOLOE` 和 `SAM3` 在 workflow 中的第一阶段运行形态应为：`WorkflowAppRuntime` 进程内按需首次加载并缓存，runtime 停止时释放；不是每次调用重新加载，也不是一开始就做成正式 `DeploymentInstance` 常驻服务。当前 `YOLOE / SAM3` 都已经补了 CPU 会话缓存复用回归。
- `YOLOE` 第一阶段节点同时输出 `detections.v1` 和 `regions.v1`；`SAM3` 输出也应使用 `regions.v1`，不要硬塞进 `detections.v1`。

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
- 第一阶段 custom node 先同时开放 detection 与 region 输出，既保留 bbox 结果，也把 mask/region 结果纳入正式 contract。
- 第一阶段不直接接训练、转换、`DeploymentInstance` 主链。

#### 为什么目录放在 segmentation，而节点先做 detection 输出

- 目录的 `task_type` 表达的是权重本身的真实属性，不是第一阶段节点的输出形式。
- 官方 `YOLOE` 预训练权重文件名就是 `*-seg.pt` / `*-seg-pf.pt`，对应的是 open-vocabulary instance segmentation 权重。
- 这些权重在一次前向里同时包含 bbox、score、label，以及可继续扩展使用的 mask 相关能力。
- 第一阶段 custom node 同时开放 detection 风格输出 `detections.v1` 与 region 风格输出 `regions.v1`，因为当前平台既需要稳定的开放词汇检测链，也需要把 segmentation 权重的原生结果接进节点边界。
- 因此：
  - 磁盘资产目录保持 `yoloe/segmentation/...`
  - 节点输出 contract 第一阶段同时提供 `detections.v1` 和 `regions.v1`
- 不能因为节点要兼容 detection 下游，就把官方 segmentation 权重误记成 detection 目录；那样会在后续扩充分割能力时造成理解混乱。

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

### 共享文本编码器资产

`YOLOE text-prompt` 和 `SAM3` 第一阶段都应复用本地 `text-encoders` 资产目录，不再依赖外部 `clip` 或 `mobileclip` Python 包的在线安装和在线下载逻辑。

推荐目录如下：

```text
data/files/models/pretrained/
└─ text-encoders/
   ├─ clip/
   │  ├─ tokenizer/
   │  │  └─ bpe_simple_vocab_16e6.txt.gz
   │  └─ vit-b-32/
   │     └─ ViT-B-32.pt
   └─ mobileclip/
      └─ blt/
         └─ mobileclip_blt.ts
```

说明：

- `bpe_simple_vocab_16e6.txt.gz` 是共享 tokenizer 资产，`YOLOE text-prompt` 和 `SAM3` 都会使用。
- `mobileclip_blt.ts` 是 `YOLOE text-prompt` 第一阶段默认文本编码器。
- `ViT-B-32.pt` 当前不是 `YOLOE text-prompt` 默认链路的硬依赖，但作为后续支持 `clip:ViT-B/32` 的预留资产保留在本地目录中。
- `simple_tokenizer.py` 这类加载与编码逻辑属于项目代码，不属于磁盘模型资产。

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
- 当前 `YOLOE prompt-free`、`YOLOE text-prompt`、`YOLOE visual-prompt` 都已经接通 project-native runtime；`YOLOE visual-prompt` 当前已开放 `box / point / polygon / mask` 四类提示，并支持同一 `prompt_id` 下混合多种视觉提示后合并成一个 prompt 原型。

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
- 第一阶段节点同时输出 `detections.v1` 和 `regions.v1`，这样既能直接接现有 detection 下游，也不会丢掉 segmentation 权重的原生 region 能力。
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

运行时约定：

- 同一 `prompt_id` 可出现多条记录。
- `negative=false` 的文本会作为 positive 文本集合。
- `negative=true` 的文本会作为 negative 文本集合。
- `YOLOE text-prompt` 会先按 `prompt_id` 聚合，再把 positive 文本均值作为主方向，并把 negative 文本作为抑制项并入同一个类别原型。
- `SAM3 semantic-segment` 当前也采用同样的 grouped positive/negative 语义：同一 `prompt_id` 至少要有一条 positive 文本，negative 文本会作为抑制项并入同一个语义原型。

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
  - 输出：`detections.v1`、`regions.v1`、`value.v1`
- `custom.yoloe.visual-prompt-detect`
  - 输入：`image-ref.v1`、`image-ref.v1(prompt_image)`、`prompt-regions.v1`
  - 输出：`detections.v1`、`regions.v1`、`value.v1`
- `custom.yoloe.prompt-free-detect`
  - 输入：`image-ref.v1`
  - 输出：`detections.v1`、`regions.v1`、`value.v1`

### SAM3

- `custom.sam3.semantic-segment`
  - 输入：`image-ref.v1`、`text-prompts.v1`
  - 输出：`regions.v1`、`value.v1`
- `custom.sam3.interactive-segment`
  - 输入：`image-ref.v1`、`prompt-regions.v1`
  - 输出：`regions.v1`、`value.v1`

说明：

- `interactive-segment` 当前已经接通 project-native runtime。
- 当前阶段支持 `box`、`point`、`polygon`、`mask` prompt。
- `semantic-segment` 当前也已接通 project-native runtime。
- `semantic-segment` 当前支持按 `prompt_id` 聚合的 `text-prompts.v1`，同组内可混合 positive/negative 文本。

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
