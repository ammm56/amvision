# LiteGraph API 说明

本文档记录当前导入快照中较重要的 LiteGraph API 变化，供 workflow editor adapter 接入时参考。本文不定义 amvision 的公开保存格式；前端保存与加载仍以后端 `WorkflowGraphTemplate` 和 `FlowApplication` 为准。

## CanvasPointer API

`CanvasPointer` 替代了原有较分散的 pointer 处理逻辑，为 click、double-click 和 drag 提供统一的交互入口。

### 默认行为变化

- 多选拖拽不再要求一直按住 `Shift`。
- 当多个 node 或其他元素已选中时，点击单个元素仍会取消其他选中项。
- 点击已连接 input 上的 link 不再自动断开并重新连接。
- double-click 要求两次点击位置足够接近。
- pointer 行为更容易通过配置和回调扩展。

### 已修复行为

- 点击 node 时偶发轻微位移的问题。
- `Alt` 点击添加 reroute 时生成两次 undo step 的问题。

### 多选操作

- `Ctrl + drag`：开始多选。
- `Ctrl + Shift + drag`：追加到当前选择。
- `Ctrl + drag` 后按 `Shift`：追加到当前选择。
- `Ctrl + drag` 后按 `Alt`：从当前选择中移除。

### Click drift

`CanvasPointer` 会在 `pointerdown` 与 `pointerup` 之间保留一小段缓冲，减少轻微移动导致的误拖拽。

- `bufferTime`：允许忽略微小移动的最长时间，默认 150ms。
- `maxClickDrift`：click 可以偏移的最大距离，默认 6px。

### Double-click

double-click 触发时，普通 click 回调可能已经执行一次。当前行为下，如果第二次点击转为 drag，则 double-click 事件失效。

- `doubleClickTime`：两次 `pointerdown` 之间允许的最长时间，默认 300ms。
- 两次点击距离必须小于 `3 * maxClickDrift`。

### 配置示例

```ts
CanvasPointer.bufferTime = 150
CanvasPointer.maxClickDrift = 6
CanvasPointer.doubleClickTime = 300
```

## Pointer 回调

click、double-click 和 drag 都可以在初始 `pointerdown` 阶段配置，LiteGraph 会在后续事件阶段执行对应回调。

```ts
const { pointer } = this

pointer.onClick = (event) => node.executeClick(event)
pointer.onDoubleClick = node.gotDoubleClick

pointer.onDragStart = (event) => {
  node.isBeingDragged = true
  canvas.startedDragging(event)
}
pointer.onDrag = () => {}
pointer.onDragEnd = () => {}

pointer.finally = () => {
  node.isBeingDragged = false
}
```

## Widgets

node widget 增加了 `onPointerDown` 回调，用于统一处理 click、double-click 和 drag。

主要收益：

- 使用方式更直接。
- 暴露 double-click 等回调，减少手写时间和距离判断。
- 与 LiteGraph 其他 pointer 行为保持一致。
- 遵循用户系统中的 click speed 与 pointer accuracy 设置。

示例：

```ts
widget.onPointerDown = function (pointer, node) {
  const event = pointer.eDown
  const offsetFromNode = [event.canvasX - node.pos[0], event.canvasY - node.pos[1]]

  pointer.onClick = (upEvent) => {
    console.log(pointer.eDown)
    console.log(pointer.eMove ?? 'Pointer did not move')
    console.log(upEvent)
    console.log(offsetFromNode)
  }
  pointer.onDoubleClick = (upEvent) => this.customFunction(upEvent)
  pointer.onDragStart = () => {}
  pointer.onDrag = () => {}
  pointer.onDragEnd = () => {}
  pointer.finally = () => {}

  return true
}
```

## TypeScript 与 JSDoc

TypeScript 类型可在主流编辑器中使用。JavaScript 项目可以通过 JSDoc 引入类型。

```ts
/** @import { IWidget } from './path/to/@comfyorg/litegraph/litegraph.d.ts' */
/** @type IWidget */
const widget = node.widgets[0]
widget.onPointerDown = function (pointer, node, canvas) {}
```

## Hovering over

LiteGraph 暴露 canvas hover 状态，便于下游自定义 cursor。

```ts
type LGraphCanvasState = {
  shouldSetCursor: boolean
  hoveringOver: CanvasItem
}

canvas.state.shouldSetCursor = false

if (canvas.state.hoveringOver & CanvasItem.ResizeSe) {
  element.style.cursor = 'se-resize'
}
```

## 已移除或不维护的公开接口

当前快照中移除或不再维护下面这些接口。adapter 接入时不要依赖这些能力。

- Live mode
- Subgraph
- `dragged_node`
- `addNodeMethod`
- `compareObjects`
- `auto_sort_node_types`

如后续 workflow editor 需要类似能力，应在本项目 adapter 层重新评估并实现，不直接扩大 LiteGraph 对业务层的暴露面。
