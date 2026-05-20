import type { LGraphEventMap } from "./LGraphEventMap"
import type { INodeInputSlot } from "@litegraph/litegraph"
import type { SubgraphInput } from "@litegraph/subgraph/SubgraphInput"
import type { IBaseWidget } from "@litegraph/types/widgets"

export interface SubgraphInputEventMap extends LGraphEventMap {
  "input-connected": {
    input: INodeInputSlot
    widget: IBaseWidget
  }

  "input-disconnected": {
    input: SubgraphInput
  }
}
