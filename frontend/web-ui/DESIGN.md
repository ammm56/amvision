---
version: 0.1.4
name: AMVision-frontend-design-system
description: AMVision 前端设计规则，面向本地优先的工业视觉平台、工作站界面和流程编排场景，统一定义默认 Light 与可切换 Dark 主题下的色彩、排版、间距、组件层级和交互状态。界面强调信息密度、操作稳定性、低延迟反馈和长时间使用的可读性，不采用营销站式视觉表达。

theme:
  default: light
  supported:
    - light
    - dark

colors:
  brand:
    primary: "#00d992"
    primary-soft: "#2fd6a1"
    primary-deep: "#10b981"
    primary-text-light: "#087a56"
    on-primary: "#101010"

  light:
    page: "#f6f7f9"
    surface: "#ffffff"
    surface-soft: "#ffffff"
    surface-muted: "#eceff2"
    surface-raised: "#ffffff"
    text: "#344054"
    text-strong: "#171a1f"
    text-muted: "#667085"
    text-disabled: "#98a2b3"
    border: "#e4e7ec"
    border-strong: "#d0d5dd"
    input: "#ffffff"
    sidebar: "#ffffff"
    sidebar-active: "#eaf6f1"
    table-header: "#ffffff"
    row-hover: "#f5faf8"
    row-selected: "#eaf6f1"
    overlay: "rgba(17, 24, 39, 0.44)"
    code-surface: "#f2f4f7"
    code-text: "#344054"
    action-primary: "#087a56"
    action-primary-hover: "#066647"
    action-primary-active: "#05543c"
    action-soft: "#eaf6f1"
    on-action: "#ffffff"

  dark:
    page: "#101010"
    surface: "#171918"
    surface-soft: "#1a1a1a"
    surface-muted: "#242825"
    surface-raised: "#202321"
    text: "#f2f2f2"
    text-strong: "#ffffff"
    text-muted: "#a7b0ab"
    text-disabled: "#747d78"
    border: "#3d3a39"
    border-strong: "#5a5754"
    input: "#141615"
    sidebar: "#101010"
    sidebar-active: "#1c2c26"
    table-header: "#1a1a1a"
    row-hover: "#202622"
    row-selected: "#17352b"
    overlay: "rgba(0, 0, 0, 0.72)"
    code-surface: "#111312"
    code-text: "#f5f6f7"

  semantic:
    light:
      success:
        text: "#176b4d"
        icon: "#14835c"
        surface: "#e6f7ef"
        border: "#9bd8bf"
      warning:
        text: "#805300"
        icon: "#a36c00"
        surface: "#fff4d8"
        border: "#e4c472"
      danger:
        text: "#a52d36"
        icon: "#bf3c46"
        surface: "#fff0f1"
        border: "#efb2b7"
      info:
        text: "#245f9e"
        icon: "#2f73bd"
        surface: "#e8f2fd"
        border: "#abc9ea"
      neutral:
        text: "#475467"
        icon: "#667085"
        surface: "#ffffff"
        border: "#d9dee5"
    dark:
      success:
        text: "#62d5a9"
        icon: "#45c997"
        surface: "#17342a"
        border: "#2d6b53"
      warning:
        text: "#e2b75f"
        icon: "#d7a044"
        surface: "#392f1a"
        border: "#735d2d"
      danger:
        text: "#ef8c92"
        icon: "#e07176"
        surface: "#3a2023"
        border: "#804148"
      info:
        text: "#8dbbed"
        icon: "#76a9e5"
        surface: "#203248"
        border: "#3d6087"
      neutral:
        text: "#bdc6c1"
        icon: "#a7b0ab"
        surface: "#2a2e2c"
        border: "#494f4c"

  progress:
    light:
      fill: "#087a56"
      text: "#087a56"
      track: "#e7eeeb"
    dark:
      fill: "#00d992"
      text: "#62d5a9"
      track: "#27312d"

  graph:
    light:
      canvas: "#ffffff"
      shell: "#edf2f0"
      toolbar: "#ffffff"
      panel: "#ffffff"
      panel-strong: "#ffffff"
      panel-soft: "#ffffff"
      node: "#ffffff"
      node-header: "#fdfefd"
      node-border: "#c8d4d0"
      text: "#1b2923"
      text-strong: "#0d1712"
      text-muted: "#607068"
      grid-minor: "rgba(27, 41, 35, 0.07)"
      grid-major: "rgba(27, 41, 35, 0.13)"
      link: "#d99018"
      link-hover: "#b87300"
      link-selected: "#10b981"
      selected: "#10b981"
      control-checked: "#087a56"
      on-control-checked: "#ffffff"
      input-port: "#bd4865"
      output-port: "#287fb8"
      control-port: "#9a6b20"
      invalid: "#bf3c46"
    dark:
      canvas: "#171a18"
      shell: "#101210"
      toolbar: "#202421"
      panel: "#242925"
      panel-strong: "#1d211e"
      panel-soft: "#191d1a"
      node: "#2a302c"
      node-header: "#343b36"
      node-border: "#4a554e"
      text: "#e8eeea"
      text-strong: "#f6faf7"
      text-muted: "#a9b5ad"
      grid-minor: "rgba(255, 255, 255, 0.035)"
      grid-major: "rgba(255, 255, 255, 0.075)"
      link: "#f2b84b"
      link-hover: "#ffd166"
      link-selected: "#00d992"
      selected: "#00d992"
      control-checked: "#00d992"
      on-control-checked: "#101010"
      input-port: "#d5657b"
      output-port: "#69addf"
      control-port: "#d4a84e"
      invalid: "#e07176"
    node-category:
      input-output: "#2f8dbd"
      vision: "#00a9a5"
      model: "#8a70d6"
      transform: "#b8792d"
      logic: "#477fd1"
      integration: "#c9653d"
      utility: "#6f7d75"
    group:
      mint: "#10b981"
      cyan: "#00b8d9"
      azure: "#2f80ed"
      violet: "#7c5cfc"
      magenta: "#d946ef"
      amber: "#f5a524"

typography:
  display-xl:
    fontFamily: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif
    fontSize: 60px
    fontWeight: 400
    lineHeight: 60px
    letterSpacing: -0.65px
  display-lg:
    fontFamily: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif
    fontSize: 36px
    fontWeight: 400
    lineHeight: 40px
    letterSpacing: -0.9px
  display-md:
    fontFamily: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif
    fontSize: 24px
    fontWeight: 700
    lineHeight: 32px
    letterSpacing: -0.6px
  display-sm:
    fontFamily: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif
    fontSize: 20px
    fontWeight: 600
    lineHeight: 28px
  eyebrow-mono:
    fontFamily: Inter, system-ui, -apple-system, sans-serif
    fontSize: 14px
    fontWeight: 600
    lineHeight: 20px
    letterSpacing: 2.52px
  eyebrow-uppercase:
    fontFamily: Inter, system-ui, -apple-system, sans-serif
    fontSize: 18px
    fontWeight: 600
    lineHeight: 28px
    letterSpacing: 0.45px
  body-lg:
    fontFamily: Inter, system-ui, -apple-system, sans-serif
    fontSize: 18px
    fontWeight: 400
    lineHeight: 28px
  body-md:
    fontFamily: Inter, system-ui, -apple-system, sans-serif
    fontSize: 16px
    fontWeight: 400
    lineHeight: 26px
  body-md-strong:
    fontFamily: Inter, system-ui, -apple-system, sans-serif
    fontSize: 16px
    fontWeight: 600
    lineHeight: 24px
  body-sm:
    fontFamily: Inter, system-ui, -apple-system, sans-serif
    fontSize: 14px
    fontWeight: 400
    lineHeight: 20px
  body-sm-strong:
    fontFamily: Inter, system-ui, -apple-system, sans-serif
    fontSize: 14px
    fontWeight: 600
    lineHeight: 23px
  caption:
    fontFamily: Inter, system-ui, -apple-system, sans-serif
    fontSize: 12px
    fontWeight: 400
    lineHeight: 16px
  caption-strong:
    fontFamily: Inter, system-ui, -apple-system, sans-serif
    fontSize: 12px
    fontWeight: 500
    lineHeight: 16px
  code:
    fontFamily: SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace
    fontSize: 13px
    fontWeight: 400
    lineHeight: 18px
  code-strong:
    fontFamily: SFMono-Regular, Menlo, Monaco, Consolas, monospace
    fontSize: 13px
    fontWeight: 550
    lineHeight: 16px
  button-md:
    fontFamily: Inter, system-ui, -apple-system, sans-serif
    fontSize: 16px
    fontWeight: 600
    lineHeight: 24px

rounded:
  none: 0px
  xs: 4px
  sm: 6px
  md: 8px
  pill: 9999px
  full: 9999px

spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 20px
  2xl: 24px
  3xl: 32px
  4xl: 40px
  5xl: 48px
  6xl: 64px

components:
  nav-link:
    textColor:
      light: "{colors.light.text-muted}"
      dark: "{colors.dark.text-muted}"
    activeBackgroundColor:
      light: "{colors.light.sidebar-active}"
      dark: "{colors.dark.sidebar-active}"
    activeIndicator: "{colors.brand.primary}"
    typography: "{typography.body-sm}"
  button-primary:
    backgroundColor:
      light: "{colors.light.action-primary}"
      dark: "{colors.brand.primary}"
    textColor:
      light: "{colors.light.on-action}"
      dark: "{colors.brand.on-primary}"
    typography: "{typography.button-md}"
    rounded: "{rounded.sm}"
    padding: "{spacing.md} {spacing.lg}"
  button-secondary:
    backgroundColor:
      light: "{colors.light.surface}"
      dark: "{colors.dark.surface}"
    textColor:
      light: "{colors.light.text}"
      dark: "{colors.dark.text}"
    borderColor:
      light: "{colors.light.border}"
      dark: "{colors.dark.border}"
    typography: "{typography.button-md}"
    rounded: "{rounded.sm}"
    padding: "{spacing.md} {spacing.lg}"
  button-ghost:
    backgroundColor: transparent
    textColor:
      light: "{colors.light.action-primary}"
      dark: "{colors.brand.primary-soft}"
    typography: "{typography.button-md}"
    rounded: "{rounded.sm}"
    padding: "{spacing.md} {spacing.lg}"
  button-pill-tag:
    backgroundColor:
      light: "{colors.light.surface-soft}"
      dark: "{colors.dark.surface-soft}"
    textColor:
      light: "{colors.light.text}"
      dark: "{colors.dark.text}"
    borderColor:
      light: "{colors.light.border}"
      dark: "{colors.dark.border}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.pill}"
    padding: "{spacing.xs} {spacing.md}"
  text-input:
    backgroundColor:
      light: "{colors.light.input}"
      dark: "{colors.dark.input}"
    textColor:
      light: "{colors.light.text}"
      dark: "{colors.dark.text}"
    borderColor:
      light: "{colors.light.border-strong}"
      dark: "{colors.dark.border-strong}"
    focusBorderColor:
      light: "{colors.light.action-primary}"
      dark: "{colors.brand.primary}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.sm}"
    padding: "{spacing.md} {spacing.lg}"
  card-feature:
    backgroundColor:
      light: "{colors.light.surface}"
      dark: "{colors.dark.surface}"
    textColor:
      light: "{colors.light.text}"
      dark: "{colors.dark.text}"
    borderColor:
      light: "{colors.light.border}"
      dark: "{colors.dark.border}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: "{spacing.2xl}"
  card-feature-emphasized:
    backgroundColor:
      light: "{colors.light.surface}"
      dark: "{colors.dark.surface-raised}"
    textColor:
      light: "{colors.light.text}"
      dark: "{colors.dark.text}"
    borderColor: "{colors.brand.primary}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: "{spacing.xl}"
  code-mockup:
    backgroundColor:
      light: "{colors.light.code-surface}"
      dark: "{colors.dark.code-surface}"
    textColor:
      light: "{colors.light.code-text}"
      dark: "{colors.dark.code-text}"
    borderColor:
      light: "{colors.light.border}"
      dark: "{colors.dark.border}"
    typography: "{typography.code}"
    rounded: "{rounded.md}"
    padding: "{spacing.xl}"
  code-inline-chip:
    backgroundColor:
      light: "{colors.light.code-surface}"
      dark: "{colors.dark.code-surface}"
    textColor:
      light: "{colors.light.code-text}"
      dark: "{colors.dark.code-text}"
    typography: "{typography.code}"
    rounded: "{rounded.sm}"
    padding: "{spacing.xxs} {spacing.sm}"
---


## 概述

AMVision 是面向本地部署、工业工作站和边缘设备的视觉处理平台。前端主要承载项目、数据集、任务、模型、部署、推理、图编辑、应用、集成、自定义节点和设置等工作流，不按营销站、内容站或通用 SaaS Dashboard 的方式组织界面。

设计目标是让操作者在长时间运行、较高信息密度和弱网或离线环境下，仍能快速判断系统状态并完成关键操作。视觉语言以稳定的表面层级、清晰的边界、有限的强调色和紧凑但不拥挤的布局为主。装饰只用于强化结构和状态，不与业务内容争夺注意力。

本文档中的 token 名称、组件名、框架名、协议名和字体名保留英文；面向产品、交互、用途和约束的说明使用中文。YAML 区域是可供工具读取的基础 token，正文用于解释这些 token 在 AMVision 中的使用方式。`theme.default` 固定为 `light`，用户主动切换后才使用 `dark`。

### 适用范围

- 浏览器工作台和本地工作站界面。
- 项目、数据集、任务、模型、部署和推理管理页面。
- Workflow 图编辑器、节点面板、属性面板和执行预览。
- 自定义节点、协议集成、运行时配置和系统设置页面。
- standalone、workstation、edge 与后续 online 形态中的同一套 Vue 3 前端。

### 核心特征

- 品牌识别统一使用 `{colors.brand.primary}`（`#00d992`），但交互色按主题适配。Light 主要操作使用更深的 `{colors.light.action-primary}`，Dark 主要操作使用品牌色；错误、警告和信息状态必须使用独立的 Semantic color，不得全部替换为品牌色。
- 同时支持 Light 与 Dark 主题，并以 Light 作为默认外观。Dark 是完整的等价主题，不是只供 Workflow 使用的特殊模式；两种主题必须保持相同的信息层级与交互语义。
- 通过表面明度差、留白和必要的 1 px hairline 建立层级。一个层级不同时叠加明显底色、边框和阴影；阴影只用于真正浮动的内容。
- Inter 承担界面正文和标题，SF Mono 仅用于 ID、路径、协议值、日志、代码、模型输入输出和其他机器可读内容。
- 按钮使用 `{rounded.sm}`，卡片和浮动面板使用 `{rounded.md}`，`{rounded.pill}` 只用于状态、计数和短标签。
- 所有状态同时通过文字、图标或形状表达，不只依赖颜色。

## 色彩

### 品牌色与强调色

- **Primary**（`{colors.brand.primary}` — `#00d992`）：Logo、品牌标记、Dark 主题主要操作和必要的运行反馈。Light 主题不直接把该亮绿色用于大面积按钮或选中背景。
- **Primary Soft**（`{colors.brand.primary-soft}` — `#2fd6a1`）：Dark 主题中的 hover、focus、轻量提示和低强度强调。
- **Primary Deep**（`{colors.brand.primary-deep}` — `#10b981`）：选中边框、按压状态和需要更稳定轮廓的品牌色。
- **Primary Text Light**（`{colors.brand.primary-text-light}` — `#087a56`）：Light 主题中作为链接或文字使用的品牌色，避免直接使用亮绿色正文导致对比度不足。
- **On Primary**（`{colors.brand.on-primary}` — `#101010`）：位于 primary 背景上的文字和图标颜色。

### Light 主题

Light 是 AMVision 默认外观，适用于常规工作站、数据管理、配置、任务监控和明亮环境。主要层级如下：

- `{colors.light.page}`：页面大面积背景。
- `{colors.light.surface}`：Card、表格、侧面内容区和普通面板。
- `{colors.light.surface-soft}`：与主表面保持一致的白色次级区域；通过留白和必要的 hairline 表达结构，不通过连续灰色块堆叠层级。
- `{colors.light.surface-muted}`：只读区和需要比 soft 更明确但仍不应形成 Card 的弱表面；可操作表格行的悬停状态使用独立的 `row-hover`。
- `{colors.light.surface-raised}`：Modal、Popover、Dropdown 和其他浮动层。
- `{colors.light.text}`、`text-strong`、`text-muted`、`text-disabled`：四级文字层级。
- `{colors.light.border}` 与 `border-strong`：普通分隔和交互控件边界。
- `{colors.light.sidebar}` 与 `sidebar-active`：左侧 App Sidebar 使用白色默认表面，当前路由使用低强度品牌色背景。
- `{colors.light.table-header}`、`row-hover` 与 `row-selected`：表头使用白色，通过字重和底部 hairline 建立列结构；悬停行使用接近白色的低强度反馈，选中行使用低强度品牌色背景。
- `{colors.light.action-primary}`、`action-primary-hover`、`action-primary-active` 与 `on-action`：Light 主题主要操作的完整状态。它们与品牌亮绿色分离，以保证白色页面上的稳定对比度。
- `{colors.light.action-soft}`：当前 Tab、当前选项和低强度品牌强调，不用于成功状态。

Light 页面使用偏中性的冷灰页面背景和白色内容表面。Sidebar、表头、摘要区和普通面板默认保持白色，层级主要依靠留白、文字权重和必要的 1 px hairline；只有 hover、只读或明确需要弱强调的区域才使用 muted surface。长期显示的一级 Card 可以使用极淡边框，同一区域不得连续嵌套多个带边框 Card。普通信息分组依靠标题、留白和圆角，不使用连续灰色块或横线模拟结构。

### Dark 主题

Dark 是完整外观，适用于低照度环境、长时间监控和偏好深色界面的操作者。它必须覆盖全部页面与组件，不允许只对背景反色。主要层级如下：

- `{colors.dark.page}`：页面大面积近黑背景。
- `{colors.dark.surface}`、`surface-soft`、`surface-raised`：普通、次级和浮动表面。
- `{colors.dark.text}`、`text-strong`、`text-muted`、`text-disabled`：四级文字层级。
- `{colors.dark.border}` 与 `border-strong`：Dark 下的 hairline 和交互边界。
- `{colors.dark.sidebar}` 与 `sidebar-active`：Dark App Sidebar 的默认和当前路由状态。
- `{colors.dark.table-header}`、`row-hover` 与 `row-selected`：Dark 数据表格的结构、悬停和选中状态。
- `{colors.dark.code-surface}` 与 `code-text`：日志、代码和机器可读值。

### Semantic color 是什么

Semantic color 不是一个独立外观，也不是 Workflow 专用颜色，而是表达业务含义的状态色。`colors.semantic.light` 和 `colors.semantic.dark` 分别提供 `success`、`warning`、`danger`、`info`、`neutral` 的 text、icon、surface 和 border。组件只引用含义，不直接判断具体色值。

- `success`：成功、健康、在线、已完成。
- `warning`：等待、配置不完整、资源不足、需要注意。
- `danger`：失败、离线、校验错误、破坏性操作。
- `info`：普通通知、进行中的非危险阶段、可查看详情。
- `neutral`：未开始、已停止、无状态或普通元数据。

训练失败、部署异常、连接断开和表单校验错误必须使用 danger；等待资源、未完成配置和即将超时使用 warning；不要用 brand primary 代替全部业务状态。

### Progress color 是什么

Progress color 表示可量化任务的完成比例，不等同于 Semantic info。Light 使用较深的 action green，Dark 使用品牌绿色；轨道使用低对比度中性绿色。训练、转换、导入、导出和部署进度统一引用 `colors.progress`，不得复用蓝色 info token。任务的 running Badge 仍使用 Semantic info，以保持“当前阶段”和“完成比例”两种信息边界清楚。

### Graph color 是什么

Graph color 是 Workflow 图编辑器的场景 token。Workflow 画布同时包含网格、连接线、端口、节点、节点组、浮动工具条和运行状态，普通页面的 `surface`、`border` 无法完整表达这些层级，因此需要 `colors.graph.light` 和 `colors.graph.dark`。

Graph 不是第三种主题。当前外观为 Light 时使用 `colors.graph.light`，当前外观为 Dark 时使用 `colors.graph.dark`。Graph token 只负责画布场景，应用的其余区域仍使用对应的 Light/Dark token。

#### Workflow Node 差异

Workflow Node 需要区分“类别”“端口方向”“交互状态”和“运行状态”，四者不能混在同一颜色上：

- `node-category`：通过类别文字、图标或节点目录中的小标签区分 input-output、vision、model、transform、logic、integration、utility。画布中的普通节点使用统一的 graph node surface 和中性边框，不持续显示类别色边框，避免普通节点长期处于强调状态。
- `input-port`、`output-port`、`control-port`：区分输入、输出和控制连接。若后续按数据类型着色，应在公开 schema 稳定后增加 data-type token，不能临时硬编码。
- `selected`、`link-hover`、`link-selected`、`invalid`：分别表示节点或工具选中、连线 hover、连线选中和非法连接等交互状态。普通连线使用高能量金色，形成独立的数据流语义；连线选中回到品牌绿色，和节点、节点组及画布工具的选中语义保持一致。普通连线色不复用 Semantic warning 或节点组选色。
- `control-checked`、`on-control-checked`：用于画布节点、属性面板和应用边界中的勾选控件。Light 使用较深的绿色底和白色图标，Dark 使用品牌绿色底和深色图标；不能依赖浏览器原生 `accent-color`，避免不同平台出现黑色对勾或对比度漂移。
- 节点运行状态继续引用 Semantic color：running 使用 brand primary，success 使用 semantic success，warning 使用 semantic warning，failed 使用 semantic danger，disabled 使用 neutral/text-disabled。
- `group`：为节点组提供有限的可选 indicator 色。组颜色只用于标题条、色块、边框或低透明度背景，不覆盖节点状态色；节点组被选中时仍使用品牌绿色外轮廓。

视觉检测叠加层还需要独立的颜色体系，用于搜索区域、参考对象、检测结果、选中结果、拒绝结果和草稿。叠加颜色不得直接复用普通按钮色，并应在 Light、Dark、图像亮区和图像暗区上保持可区分性。

## 排版

### 字体

系统使用两组字体：

1. **Inter**：用于标题、正文、按钮、导航、表格和表单。常用字重为 400、500、600 和 700。
2. **SF Mono**：使用 Menlo、Monaco、Consolas 和 Liberation Mono 作为 fallback，用于代码、日志、路径、命令、UUID、模型版本、端点地址和数值密集内容。

中文文本由 system-ui 的中文字体 fallback 承担。不得为了视觉统一把长段中文、普通按钮文本或导航文本强制设置为 monospace。

### 层级

| Token | 字号 | 字重 | 行高 | 字距 | AMVision 用途 |
|---|---:|---:|---:|---:|---|
| `{typography.display-xl}` | 60px | 400 | 60px | -0.65px | 欢迎页或极少量全屏空状态，不用于常规工作台标题。 |
| `{typography.display-lg}` | 36px | 400 | 40px | -0.9px | 大型独立页面或阶段标题。 |
| `{typography.display-md}` | 24px | 700 | 32px | -0.6px | 页面主标题、属性面板标题。 |
| `{typography.display-sm}` | 20px | 600 | 28px | 卡片组、面板和表格区标题。 |
| `{typography.eyebrow-mono}` | 14px | 600 | 20px | 2.52px | 少量分类标签；中文界面不强制 uppercase。 |
| `{typography.eyebrow-uppercase}` | 18px | 600 | 28px | 0.45px | 大型分区提示；不用于高频页面。 |
| `{typography.body-lg}` | 18px | 400 | 28px | 首要说明和空状态引导。 |
| `{typography.body-md}` | 16px | 400 | 26px | 表单说明、正文和面板内容。 |
| `{typography.body-md-strong}` | 16px | 600 | 24px | 重要字段、选项和摘要值。 |
| `{typography.body-sm}` | 14px | 400 | 20px | 默认界面正文、表格和导航。 |
| `{typography.body-sm-strong}` | 14px | 600 | 23px | 表头、按钮和状态标签。 |
| `{typography.caption}` | 12px | 400 | 16px | 时间、辅助元数据和紧凑提示。 |
| `{typography.caption-strong}` | 12px | 500 | 16px | 需要强调的辅助信息。 |
| `{typography.code}` | 13px | 400 | 18px | 代码、日志、ID、路径和协议值。 |
| `{typography.code-strong}` | 13px | 550 | 16px | 重点机器可读值。 |
| `{typography.button-md}` | 16px | 600 | 24px | 中等尺寸按钮标签。 |

### 排版原则

- 常规业务页面以 14–24 px 为主要字号范围，避免大标题挤占可用工作区。
- 数据表格的列标题、单元格数值和操作项要保持稳定的基线和行高；数字列按需要右对齐。
- 名称与 ID 同时显示时，名称使用 Inter，ID 使用 SF Mono 或 caption，并降低视觉优先级。
- 文本优先使用产品语言中的直白词，例如“训练”“部署”“推理”“保存”“预览”，避免营销式口号和含义模糊的缩写。
- 中英文混排时，专有名词如 Vue 3、FastAPI、WebSocket、ZeroMQ、ONNX、OpenVINO、TensorRT、CoreML、Workflow 和 Preview 保留英文。

### 字体替代

- **Sans**：Inter 不可用时依次使用 system-ui、Segoe UI 和系统默认 sans-serif。
- **Mono**：SF Mono 不可用时依次使用 Menlo、Monaco、Consolas、Liberation Mono；JetBrains Mono 可作为随包提供的替代字体。
- 字体资源必须支持本地分发，不将外网 CDN 作为默认依赖。

## 布局

### 间距系统

- 基础单位为 4 px。
- token 依次为 `{spacing.xxs}` 2 px、`{spacing.xs}` 4 px、`{spacing.sm}` 8 px、`{spacing.md}` 12 px、`{spacing.lg}` 16 px、`{spacing.xl}` 20 px、`{spacing.2xl}` 24 px、`{spacing.3xl}` 32 px、`{spacing.4xl}` 40 px、`{spacing.5xl}` 48 px、`{spacing.6xl}` 64 px。
- 常规页面内容区使用 24–32 px 外边距，紧凑工作台、属性面板和小屏幕可降低到 12–20 px。
- 卡片内部默认使用 `{spacing.2xl}` 24 px；数据表格、工具条和侧边导航使用更紧凑的 8–16 px。

### App Shell

- 左侧导航是全局主导航，包含品牌、主要模块和底部用户入口。展开状态显示图标和文字，折叠状态保留图标。
- 导航收起按钮位于左侧导航顶部；折叠状态下，AM 品牌标记在 hover 或 focus 时切换为展开按钮。
- 用户、语言、外观和退出登录集中在左侧导航底部的用户面板，不在页面顶部重复显示。
- 主内容区不设置所有页面共享的固定顶部栏。各页面只呈现自身需要的标题、筛选、项目选择和主要操作。
- 项目选择只属于项目页面或确实依赖项目上下文的局部区域，不能无条件出现在所有导航页面。

### 内容页面

- 列表页通常由页面标题与操作区、筛选区、数据表格或卡片列表组成。
- 页面主操作靠近标题区域右侧；创建、保存、发布等主要动作在同一区域保持稳定位置。
- 表格容器应优先占据可用宽度，避免无意义的多层 Card 嵌套。
- 页面底部不保留长期占用空间但缺少直接作用的状态栏。后端连接、任务异常等状态应在相关页面、Toast 或全局告警中按需显示。

### Workflow 画布

- Workflow 编辑器使用 full-bleed 内容区，不设置固定 header；网格画布从内容区边缘开始。
- 应用名称作为定位浮层显示在画布左上角，主要工具组悬浮在右上角。
- 工具组按“节点与画布操作 → 预览 → 属性面板 → 保存”的任务顺序组织，保存保持最右侧。
- 属性面板、节点目录和缩略图以浮动面板覆盖画布，不改变画布坐标系，也不挤压主画布尺寸。
- 面板打开时必须保留关闭入口，并避免遮挡主要工具组和关键节点操作。

### 响应式策略

| 名称 | 宽度 | 主要变化 |
|---|---:|---|
| Mobile | < 768px | 左侧导航默认折叠；列表切换为卡片或横向滚动；主要按钮保持可触达。 |
| Tablet | 768–1023px | 左侧导航可自动折叠；双栏区域降为单栏或主次抽屉。 |
| Desktop | ≥ 1024px | 使用完整左侧导航、数据表格和多面板工作区。 |

Mobile 是受支持的查看和轻量操作形态，不要求在窄屏完整复刻桌面级 Workflow 编排体验。复杂图编辑优先保证 Desktop 和工作站分辨率。

### 触控与可点击区域

- 主要按钮和常用图标按钮的可点击高度建议不小于 40 px，触控场景建议达到 44 px。
- 小于 40 px 的紧凑控件必须通过外围 padding 扩大 hit area。
- hover 不能作为唯一入口；所有 hover 显示的操作也必须支持 keyboard focus 和触控方式。

## 层级与深度

| 层级 | 处理方式 | 用途 |
|---|---|---|
| Level 0 — Flat | 无阴影、无边框。 | 页面背景和 Workflow 画布。 |
| Level 1 — Surface | 使用 surface 与 page 的明度差，必要时增加 1 px border。 | 表格、一级 Card、按钮和长驻面板。 |
| Level 2 — Floating | 轻量阴影与清晰边框。 | 悬浮工具条、Dropdown、Popover 和节点选择器。 |
| Level 3 — Modal | `0 20px 60px rgba(0,0,0,0.7)` 外部阴影和细微 inset ring。 | Modal、阻断式确认和最高层级对话框。 |

### 使用原则

- 长驻布局优先使用表面差与留白，只有边界不明确时才增加边框；同一层级不重复叠加边框。阴影只用于真正浮动或临时出现的内容。
- 普通列表、Tab 和导航选中状态优先使用完整的 soft background 与文字权重，不使用单侧色条或额外轮廓。只有表单控件、画布节点和必须强调边界的对象才使用 focus 或 selected border。
- Workflow 画布的浮动工具条应形成一个完整工具组，内部按钮使用分隔线，不为每个按钮叠加独立大阴影。
- Modal、Popover、Dropdown、Toast 和 Tooltip 必须有明确的 z-index 层级，避免属性面板、工具条和节点菜单相互覆盖错误。

## 形状

### 圆角等级

| Token | 数值 | 用途 |
|---|---:|---|
| `{rounded.none}` | 0px | 画布、全宽分区和需要连续边界的表格。 |
| `{rounded.xs}` | 4px | 紧凑控件、代码 chip 和小型标记。 |
| `{rounded.sm}` | 6px | 默认按钮、输入框、Select 和工具条按钮。 |
| `{rounded.md}` | 8px | Card、Popover、Modal 和浮动面板。 |
| `{rounded.pill}` | 9999px | 状态、计数、在线标记和短标签。 |
| `{rounded.full}` | 9999px | Avatar 和圆形图标容器。 |

圆角用于表达组件类型和层级，不追求大面积柔软造型。工作站界面优先紧凑、精确和可预测。

## 组件

### Button

**`button-primary`** — 主要操作按钮。

- Light 背景使用 `{colors.light.action-primary}`，文字使用 `{colors.light.on-action}`；Dark 背景使用 `{colors.brand.primary}`，文字使用 `{colors.brand.on-primary}`。排版使用 `{typography.button-md}`。
- 用于创建、保存、发布、开始训练等每个操作区中最重要的一个动作。
- 同一区域一般只保留一个 primary button，避免多个操作争夺注意力。

**`button-secondary`** — Light 与 Dark 表面上的次要按钮。

- 背景、文字和边框分别使用当前主题的 surface、text 和 border token。
- 用于刷新、打开节点组、取消和其他不会改变主要流程的操作。

**`button-ghost`** — 低层级文字操作。

- Light 文字使用 `{colors.light.action-primary}`，Dark 文字使用 `{colors.brand.primary-soft}`，默认不显示边框。
- 适合“查看详情”“重试”等上下文明确的操作，不用于破坏性行为。

**`button-pill-tag`** — 状态或分类标签。

- 使用 `{rounded.pill}`，只承载短文本、状态和计数。
- 如果可点击，必须提供 hover、focus、active 和 disabled 状态；不可点击时不能呈现为按钮外观。

### Card 与容器

**`card-feature`** — 默认内容卡片。

- 使用当前主题的 surface 背景、`{spacing.2xl}` 内边距和 `{rounded.md}`。一级 Card 在边界不明确时使用 1 px border，嵌套的摘要和选项组改用无边框 surface-soft。
- 适合摘要、配置分组和空状态，不应把表格的每一行转换为独立 Card。

**`card-feature-emphasized`** — 重点卡片。

- 在 `card-feature` 基础上增加更明确的边框或选中 indicator。
- 用于当前选中的部署目标、模型版本或节点，不通过无限放大和强阴影表达强调。

**`code-mockup`** — 代码、日志和结构化内容容器。

- 使用 `{typography.code}`，支持复制、横向滚动、换行策略和必要的语法着色。
- 日志区必须支持大量内容和增量更新，不能用图片模拟文本。

**`code-inline-chip`** — 行内机器可读值。

- 用于短 ID、文件格式、节点类型和协议名；长路径或长 ID 必须支持截断、Tooltip 和复制。

### Input 与表单

**`text-input`** — 标准输入框。

- Light 和 Dark 分别使用对应主题的 input、text 和 border-strong token。
- 必须定义 default、hover、focus、disabled、read-only、invalid 和 loading 状态。
- 带图标的复合输入框只由外层容器绘制 focus ring；内部原生 input 不得重复绘制 border 或 box-shadow。
- Label、帮助文本和错误文本不能只依赖 placeholder；单位和取值范围应靠近字段显示。

表单按照业务分组排列。首次保存、模型转换和部署等高风险操作，在提交前应明确显示缺失字段、输出位置和可能影响。

### Navigation

**`nav-link`** — 导航项。

- 默认使用次级文字色，active 状态同时通过背景、文字或 indicator 表达。
- 图标和文字保持固定对齐，折叠状态提供 Tooltip 或可访问名称。

**`local-tabs`** — 页面内容区内的局部视图切换。

- 只切换当前页面内的同级内容，不承担全局路由导航。Tab 之间保持 8 px 间距，容器不使用连续外框；Light 选中项使用 action-soft 背景和 action-primary 文字，Dark 使用对应主题的强调表面。
- 数量使用 `{rounded.pill}` 的紧凑 count badge，不能让数量成为比标签更强的视觉主体。
- 使用 `tablist`、`tab` 和 `aria-selected` 语义；支持 Left、Right、Home、End 键切换，并跳过 disabled 项。
- 窄屏下允许水平滚动或等宽扩展，不截断到无法识别的图标集合。

**局部目录侧栏** — 节点目录、设置诊断等复杂页面的二级定位区。

- 侧栏与主内容保持同一内容层级，不模拟第二套 App Sidebar；Desktop 可 sticky，窄屏降为普通文档流。
- 当前项使用背景与文字权重表达，不使用单侧 indicator 或额外轮廓，hover 不等同于 selected。
- 长名称允许截断，但必须保留可访问名称；目录数量与名称对齐且使用次级文字色。

### 浮动工具条

- 工具条使用 Level 2 层级，定位在画布右上角并与画布边缘保持 12–16 px 间距。
- 中文界面中 `Preview Run` 显示为“预览”，`Save Application` 显示为“保存”。
- 保存按钮位于最右侧；属性面板按钮位于保存之前。
- disabled 状态必须说明原因，例如尚无节点、必填项未完成或当前任务正在运行。
- 工具条在空间不足时优先隐藏低频文字，保留图标、Tooltip 和主要操作，不允许覆盖侧边导航。

### Workflow 画布导航

- 大型 Workflow 在首次载入和“定位全部节点”时同时计算缩放比例与中心位置，不能只改变画布偏移。
- 画布缩放范围为 15%–240%。缩放按钮、滚轮缩放和“定位全部节点”必须共享同一范围，不能在不同入口产生不同边界。
- 画布右下角使用统一的 Navigation Dock：Minimap 位于上方，紧凑 viewport controls 位于下方，二者与属性面板使用相同的右侧基准并保持 8 px 间距。
- viewport controls 提供缩小、当前比例、放大、定位全部节点和 Minimap 开关；Minimap 隐藏后只保留 controls。
- 当前比例按钮恢复到 100% 和初始位置；缩放以可见画布中心为锚点，滚轮缩放仍以指针位置为锚点。
- Navigation Dock 始终停靠画布最右侧，不因属性面板展开而向左移动。属性面板底部停在 viewport controls 上方，避免长期遮挡缩放操作。
- Minimap 从 viewport controls 上方向上展开，层级高于属性面板；展开时允许覆盖属性面板下部，关闭后不改变 controls 和属性面板的位置。
- Minimap 中的节点缩略图保留主题主色，用于表达 Workflow 内容；当前可视范围框使用独立的中性透明玻璃样式，不得复用主题主色或节点选中色。
- 当前可视范围框在亮色主题中使用半透明白色填充和中性灰边框，在暗色主题中使用低透明白色填充和高对比中性边框；hover 与拖动状态只增强中性边框和阴影，不切换为主题色。
- 窄屏隐藏 Minimap 开关和 Minimap，但保留缩放和定位能力。
- viewport controls 使用 `toolbar` 和明确的 `aria-label`，图标按钮必须提供本地化 Tooltip 和可访问名称。

### Workflow 属性面板

- 属性面板使用单一 Level 2 浮动表面，标题固定在顶部，内容区独立滚动；不能让面板标题随长表单滚出可见区域。
- 当前节点、连线、应用边界或应用摘要与 Preview 输入在同一连续内容区中依次展示，不使用 Tab 隐藏 Preview 输入。图片选择和拖放入口必须始终可直接访问。
- 属性信息使用低对比度 soft surface 分组，通过留白、圆角和文字层级建立关系，不使用连续横线模拟表格。仅保留识别对象和完成操作所需的信息。
- Node type、路径和协议值使用 Mono 字体或紧凑辅助文字；Node ID 等调试信息不作为常驻主内容，需要时通过轻量复制入口提供。
- Preview 输入只显示必要的字段、必填或可选状态和直接校验结果。不得使用感叹号图标或依赖 hover 的说明气泡承载常规帮助文本。
- 没有错误时不额外显示“已就绪”状态；缺少输入时在对应字段附近显示简短 danger 文本，避免重复的全局警告、图标和 Tooltip。

### 数据表格

- 表头使用 `{typography.caption}` 或 `{typography.body-sm-strong}`，表体使用 `{typography.body-sm}`。
- 名称列优先展示可读名称，下一行可显示 ID；状态、数量和时间列保持稳定宽度。
- 可操作行使用 `row-hover` 提供低强度指针反馈；行选中状态只使用 `row-selected` 背景表达，hover 不等同于选中。键盘焦点使用独立的 `focus-visible` 样式。
- 行级操作在需要时显示，破坏性操作必须与常规操作分组，并提供确认或撤销路径。
- 空数据、加载中、请求失败和无筛选结果是四种不同状态，不能共用一段模糊提示。

### 详情与信息列表

- 普通详情、运行配置和诊断信息使用 metadata grid 或 soft surface 分组，不使用每行 `border-bottom` 形成连续横线。
- Label 使用次级文字，Value 使用正文或 Mono；长 URL、路径和 ID 可以跨越整行并提供复制能力。
- 只有具有列语义和需要横向比较的数据才使用 Table 及其行分隔，不能用 Table 外观呈现普通说明文本。

### 状态反馈

- **Toast**：用于短时确认，不承载需要持续阅读或必须处理的信息。
- **Inline message**：用于表单错误、任务失败原因和与当前内容强相关的提示。
- **Badge**：用于任务状态、部署状态、运行时状态和版本标签。
- **Progress**：训练、转换、部署和文件导入应显示可追踪进度；统一使用 Progress token，不使用 Semantic info 蓝色。无法提供百分比时使用明确的阶段文本。
- **Connection state**：只在连接状态影响当前操作时显示，不设置无实际操作价值的固定底栏。

任务状态 Badge 默认只显示状态文字，不显示装饰圆点。圆点只保留给后端在线、设备连接、健康检查等需要表达持续信号的状态，且必须同时提供文字说明。

## 交互与状态

### 基础状态

每个可交互组件至少定义以下状态：

- `default`：正常可用。
- `hover`：指针悬停，不能作为唯一信息来源。
- `focus-visible`：键盘焦点，必须有清晰 outline。
- `active`：按压或当前选中。
- `disabled`：不可操作，并在必要时说明原因。
- `loading`：正在执行，避免重复提交。
- `error`：操作失败或输入无效，提供可执行的恢复方式。

### 危险操作

- 删除数据集版本、模型、部署、节点包或流程前，必须明确目标名称和影响范围。
- 删除、撤销 token 等操作统一使用应用内 ConfirmDialog，不使用浏览器原生 confirm；对话框初始焦点落在取消按钮。
- 请求提交后 ConfirmDialog 保持打开，确认按钮显示 loading，并暂时禁止遮罩、Escape 和关闭按钮取消，直到请求结束。
- 能够撤销或回滚时优先提供恢复路径；不可恢复时使用确认对话框。
- danger button 不使用 primary 色伪装成普通主要操作。

### 异步任务

- 训练、推理、转换、导入、发布和 Workflow 执行不得表现为同步瞬时操作。
- 行级启停、health 刷新和删除只在实际执行的按钮上显示 loading，同行其他操作进入 disabled，避免误判正在执行的动作。
- 提交成功后显示任务 ID、当前阶段、进度和查看详情入口。
- WebSocket 断开时保留最后已知状态并提示状态可能过期；恢复连接后再同步最新状态。

## 可访问性与本地化

- 正文、按钮、表格和输入框满足 WCAG 对比度要求；focus ring 在 Light 与 Dark 主题中都清晰可见。
- 图标按钮必须有 `aria-label`；状态图标必须配合文字或可访问描述。
- 页面可使用键盘完成主要流程，Tab 顺序与视觉顺序一致。
- 不使用仅靠 red/green 区分的状态组合，检测叠加层也需提供文字、编号或形状辅助。
- 中文、English、日本語和한국어文本长度不同，按钮和导航不能依赖固定文字宽度。
- 用户可见文本统一进入 i18n messages；ID、协议名、模型格式、文件扩展名和产品专有名词不强制翻译。
- 日期、数字和单位按 locale 格式化，但后端 API 的公开字段和机器可读值保持稳定。

## 性能与离线约束

- 字体、图标和前端静态资源随本地发行包提供，不依赖外网 CDN。
- 大型表格、图像列表、日志和 Workflow 节点列表按需使用分页、虚拟滚动或增量加载。
- 图像预览提供合理的缩略图和加载状态，避免一次加载原始大图阻塞工作台。
- 动画只用于说明状态变化，持续时间短且支持 `prefers-reduced-motion`。
- 弱网或后端暂时不可用时保留可恢复上下文，避免静默清空表单和编辑中的 Workflow。

## 应当遵循

- 使用当前主题的 action token 强调最重要的操作和选中状态；品牌色只承担品牌识别及 Dark 主题主操作。
- 使用 semantic color 区分 success、warning、danger 和 info。
- 同时维护 Light 与 Dark 主题，组件通过 semantic CSS variable 取色。
- 使用表面差、留白和必要边框建立清晰层级，阴影只用于浮动内容。
- 使用 Inter 表达界面语言，使用 SF Mono 表达机器可读内容。
- 使用页面自身的操作区，不恢复所有页面共享的固定顶部栏或固定底部状态栏。
- 让 Workflow 画布保持 full-bleed，工具条和属性面板以浮动层存在。
- 优先直白、稳定和可预测的工业工作台交互。

## 不应采用

- 不将 AMVision 设计成营销站、品牌展示站或通用 SaaS Dashboard。
- 不把 Dark 主题设为唯一主题，也不为 Light 与 Dark 创建含义不同的交互。
- 不在一个操作区放置多个视觉权重相同的 primary button。
- 不把 primary 色用于大段正文、所有状态或危险操作。
- 不使用大面积渐变、玻璃拟态、强 glow 或无业务含义的装饰动画。
- 不为普通 Card 叠加夸张阴影，也不通过多层 Card 包裹制造层级。
- 不在组件中直接硬编码主题颜色；应通过 token 或 CSS variable 映射。
- 不用颜色作为状态、检测结果和错误提示的唯一表达方式。
- 不引入外网字体、图标或 CDN 作为本地部署前提。
- 不为了移动端形式一致而破坏 Desktop 工作站上的信息密度和 Workflow 操作效率。
