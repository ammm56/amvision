import type { INodeInputSlot, INodeOutputSlot, OptionalProps, ReadOnlyPoint } from "@litegraph/interfaces"
import type { LGraphNode } from "@litegraph/LGraphNode"
import type { LinkId } from "@litegraph/LLink"
import type { SubgraphInput } from "@litegraph/subgraph/SubgraphInput"
import type { SubgraphOutput } from "@litegraph/subgraph/SubgraphOutput"
import type { IBaseWidget } from "@litegraph/types/widgets"

import { LabelPosition } from "@litegraph/draw"
import { LiteGraph } from "@litegraph/litegraph"
import { type IDrawOptions, NodeSlot } from "@litegraph/node/NodeSlot"
import { isSubgraphInput } from "@litegraph/subgraph/subgraphUtils"

export class NodeInputSlot extends NodeSlot implements INodeInputSlot {
  link: LinkId | null

  get isWidgetInputSlot(): boolean {
    return !!this.widget
  }

  #widget: WeakRef<IBaseWidget> | undefined

  /** Internal use only; API is not finalised and may change at any time. */
  get _widget(): IBaseWidget | undefined {
    return this.#widget?.deref()
  }

  set _widget(widget: IBaseWidget | undefined) {
    this.#widget = widget ? new WeakRef(widget) : undefined
  }

  get collapsedPos(): ReadOnlyPoint {
    return [0, LiteGraph.NODE_TITLE_HEIGHT * -0.5]
  }

  constructor(slot: OptionalProps<INodeInputSlot, "boundingRect">, node: LGraphNode) {
    super(slot, node)
    this.link = slot.link
  }

  override get isConnected(): boolean {
    return this.link != null
  }

  override isValidTarget(fromSlot: INodeInputSlot | INodeOutputSlot | SubgraphInput | SubgraphOutput): boolean {
    if ("links" in fromSlot) {
      return LiteGraph.isValidConnection(fromSlot.type, this.type)
    }

    if (isSubgraphInput(fromSlot)) {
      return LiteGraph.isValidConnection(fromSlot.type, this.type)
    }

    return false
  }

  override draw(ctx: CanvasRenderingContext2D, options: Omit<IDrawOptions, "doStroke" | "labelPosition">) {
    const { textAlign } = ctx
    ctx.textAlign = "left"

    super.draw(ctx, {
      ...options,
      labelPosition: LabelPosition.Right,
      doStroke: false,
    })

    ctx.textAlign = textAlign
  }
}
