import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useWorkflowNodeDrag } from './useWorkflowNodeDrag'

function createNode() {
  return {
    node: { node_id: 'node-1', ui_state: {} },
    x: 10,
    y: 20,
    width: 256,
  }
}

describe('useWorkflowNodeDrag', () => {
  it('普通单击不触发节点组成员重算', () => {
    const onStop = vi.fn()
    const drag = useWorkflowNodeDrag({
      graphNodes: ref([createNode()]),
      connectionDraft: ref(null),
      screenToWorld: (clientX, clientY) => ({ x: clientX, y: clientY }),
      selectNode: () => undefined,
      onStop,
    })

    drag.startNodeDrag(new MouseEvent('mousedown', { button: 0, clientX: 15, clientY: 25, cancelable: true }), createNode())
    document.dispatchEvent(new MouseEvent('mouseup', { button: 0, clientX: 15, clientY: 25 }))

    expect(onStop).not.toHaveBeenCalled()
  })

  it('节点位置实际变化后触发节点组成员重算', () => {
    const node = createNode()
    const onStop = vi.fn()
    const drag = useWorkflowNodeDrag({
      graphNodes: ref([node]),
      connectionDraft: ref(null),
      screenToWorld: (clientX, clientY) => ({ x: clientX, y: clientY }),
      selectNode: () => undefined,
      onStop,
    })

    drag.startNodeDrag(new MouseEvent('mousedown', { button: 0, clientX: 15, clientY: 25, cancelable: true }), node)
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 25, clientY: 35 }))
    document.dispatchEvent(new MouseEvent('mouseup', { button: 0, clientX: 25, clientY: 35 }))

    expect(node).toMatchObject({ x: 20, y: 30 })
    expect(onStop).toHaveBeenCalledTimes(1)
  })
})
