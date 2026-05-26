import type { ConnectingLink } from "@litegraph/interfaces"
import type { LGraph } from "@litegraph/LGraph"
import type { LGraphButton } from "@litegraph/LGraphButton"
import type { LGraphGroup } from "@litegraph/LGraphGroup"
import type { LGraphNode } from "@litegraph/LGraphNode"
import type { Subgraph } from "@litegraph/subgraph/Subgraph"
import type { CanvasPointerEvent } from "@litegraph/types/events"

export interface LGraphCanvasEventMap {
  /** The active graph has changed. */
  "litegraph:set-graph": {
    /** The new active graph. */
    newGraph: LGraph | Subgraph
    /** The old active graph, or `null` if there was no active graph. */
    oldGraph: LGraph | Subgraph | null | undefined
  }

  "litegraph:canvas":
    | { subType: "before-change" | "after-change" }
    | {
      subType: "empty-release"
      originalEvent?: CanvasPointerEvent
      linkReleaseContext?: { links: ConnectingLink[] }
    }
    | {
      subType: "group-double-click"
      originalEvent?: CanvasPointerEvent
      group: LGraphGroup
    }
    | {
      subType: "empty-double-click"
      originalEvent?: CanvasPointerEvent
    }
    | {
      subType: "node-double-click"
      originalEvent?: CanvasPointerEvent
      node: LGraphNode
    }

  /** A title button on a node was clicked. */
  "litegraph:node-title-button-clicked": {
    node: LGraphNode
    button: LGraphButton
  }
}
