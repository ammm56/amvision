import type { FloatingRenderLink } from "@litegraph/canvas/FloatingRenderLink"
import type { MovingInputLink } from "@litegraph/canvas/MovingInputLink"
import type { MovingOutputLink } from "@litegraph/canvas/MovingOutputLink"
import type { RenderLink } from "@litegraph/canvas/RenderLink"
import type { ToInputFromIoNodeLink } from "@litegraph/canvas/ToInputFromIoNodeLink"
import type { ToInputRenderLink } from "@litegraph/canvas/ToInputRenderLink"
import type { LGraphNode } from "@litegraph/LGraphNode"
import type { LLink } from "@litegraph/LLink"
import type { Reroute } from "@litegraph/Reroute"
import type { SubgraphInputNode } from "@litegraph/subgraph/SubgraphInputNode"
import type { SubgraphOutputNode } from "@litegraph/subgraph/SubgraphOutputNode"
import type { CanvasPointerEvent } from "@litegraph/types/events"
import type { IWidget } from "@litegraph/types/widgets"

export interface LinkConnectorEventMap {
  "reset": boolean

  "before-drop-links": {
    renderLinks: RenderLink[]
    event: CanvasPointerEvent
  }
  "after-drop-links": {
    renderLinks: RenderLink[]
    event: CanvasPointerEvent
  }

  "before-move-input": MovingInputLink | FloatingRenderLink
  "before-move-output": MovingOutputLink | FloatingRenderLink

  "input-moved": MovingInputLink | FloatingRenderLink | ToInputFromIoNodeLink
  "output-moved": MovingOutputLink | FloatingRenderLink

  "link-created": LLink | null | undefined

  "dropped-on-reroute": {
    reroute: Reroute
    event: CanvasPointerEvent
  }
  "dropped-on-node": {
    node: LGraphNode
    event: CanvasPointerEvent
  }
  "dropped-on-io-node": {
    node: SubgraphInputNode | SubgraphOutputNode
    event: CanvasPointerEvent
  }
  "dropped-on-canvas": CanvasPointerEvent

  "dropped-on-widget": {
    link: ToInputRenderLink
    node: LGraphNode
    widget: IWidget
  }
}
