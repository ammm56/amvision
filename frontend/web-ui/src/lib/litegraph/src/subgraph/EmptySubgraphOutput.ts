import type { SubgraphOutputNode } from "./SubgraphOutputNode"
import type { INodeOutputSlot, Point } from "@litegraph/interfaces"
import type { LGraphNode } from "@litegraph/LGraphNode"
import type { RerouteId } from "@litegraph/Reroute"

import { LLink } from "@litegraph/LLink"
import { nextUniqueName } from "@litegraph/strings"
import { zeroUuid } from "@litegraph/utils/uuid"

import { SubgraphOutput } from "./SubgraphOutput"

/**
 * A virtual slot that simply creates a new output slot when connected to.
 */
export class EmptySubgraphOutput extends SubgraphOutput {
  declare parent: SubgraphOutputNode

  constructor(parent: SubgraphOutputNode) {
    super({
      id: zeroUuid,
      name: "",
      type: "",
    }, parent)
  }

  override connect(slot: INodeOutputSlot, node: LGraphNode, afterRerouteId?: RerouteId): LLink | undefined {
    const { subgraph } = this.parent
    const existingNames = subgraph.outputs.map(x => x.name)

    const name = nextUniqueName(slot.name, existingNames)
    const output = subgraph.addOutput(name, String(slot.type))
    return output.connect(slot, node, afterRerouteId)
  }

  override get labelPos(): Point {
    const [x, y, , height] = this.boundingRect
    return [x, y + height * 0.5]
  }
}
