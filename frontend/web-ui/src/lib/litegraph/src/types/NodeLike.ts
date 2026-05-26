import type { INodeInputSlot, INodeOutputSlot } from "@litegraph/interfaces"
import type { NodeId } from "@litegraph/LGraphNode"
import type { SubgraphIO } from "@litegraph/types/serialisation"

export interface NodeLike {
  id: NodeId

  canConnectTo(
    node: NodeLike,
    toSlot: INodeInputSlot | SubgraphIO,
    fromSlot: INodeOutputSlot | SubgraphIO,
  ): boolean
}
