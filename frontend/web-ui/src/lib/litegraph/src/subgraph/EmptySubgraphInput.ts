import type { SubgraphInputNode } from "./SubgraphInputNode"
import type { INodeInputSlot, Point } from "@litegraph/interfaces"
import type { LGraphNode } from "@litegraph/LGraphNode"
import type { RerouteId } from "@litegraph/Reroute"

import { LLink } from "@litegraph/LLink"
import { nextUniqueName } from "@litegraph/strings"
import { zeroUuid } from "@litegraph/utils/uuid"

import { SubgraphInput } from "./SubgraphInput"

/**
 * A virtual slot that simply creates a new input slot when connected to.
 */
export class EmptySubgraphInput extends SubgraphInput {
  declare parent: SubgraphInputNode

  constructor(parent: SubgraphInputNode) {
    super({
      id: zeroUuid,
      name: "",
      type: "",
    }, parent)
  }

  override connect(slot: INodeInputSlot, node: LGraphNode, afterRerouteId?: RerouteId): LLink | undefined {
    const { subgraph } = this.parent
    const existingNames = subgraph.inputs.map(x => x.name)

    const name = nextUniqueName(slot.name, existingNames)
    const input = subgraph.addInput(name, String(slot.type))
    return input.connect(slot, node, afterRerouteId)
  }

  override get labelPos(): Point {
    const [x, y, , height] = this.boundingRect
    return [x, y + height * 0.5]
  }
}
