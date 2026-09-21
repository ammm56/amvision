import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useWorkflowNodeDrag } from './useWorkflowNodeDrag'
import type { WorkflowGraphGroup } from '../types'

function createNode() {
  return {
    node: { node_id: 'node-1', ui_state: {} },
    x: 10,
    y: 20,
    width: 256,
  }
}

describe('useWorkflowNodeDrag', () => {
  it('完整片段的多个组框与节点只移动一次，保留锁定和相对位置', () => {
    const nodes = ref([createNode(), { ...createNode(), node: { node_id: 'node-2', ui_state: {} }, x: 110, y: 220 }])
    const graphGroups = ref<WorkflowGraphGroup[]>(['a', 'b', 'outside'].map((group_id, i) => ({ group_id, name: group_id,
      rect: { x: i * 100, y: i * 200, width: 400, height: 400 }, member_node_ids: [`node-${i + 1}`], member_note_ids: [],
      enabled: true, locked: true, collapsed: false, membership_policy: 'full-containment', metadata: {} })))
    const drag = useWorkflowNodeDrag({ graphNodes: nodes, graphGroups, selectedGroupIds: ref(new Set(['a', 'b'])),
      selectedNodeIds: ref(new Set(['node-1', 'node-2'])), connectionDraft: ref(null), selectNode: vi.fn(), screenToWorld: (x, y) => ({ x, y }) })
    drag.startNodeDrag(new MouseEvent('mousedown'), nodes.value[0]!)
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 30, clientY: 40 }))
    document.dispatchEvent(new MouseEvent('mouseup'))
    expect(nodes.value.map(n => [n.x, n.y])).toEqual([[40, 60], [140, 260]])
    expect(graphGroups.value.map(g => [g.rect.x, g.rect.y, g.locked])).toEqual([[30, 40, true], [130, 240, true], [200, 400, true]])
  })
  it('整体移动保留选择、相对位置，并抑制结束后的单选 click', () => {
    const nodes = ref([createNode(), { ...createNode(), node: { node_id: 'node-2', ui_state: {} }, x: 110, y: 220 }])
    const selectedNodeIds = ref(new Set(['node-1', 'node-2']))
    const selectNode = vi.fn(), onMoved = vi.fn(), onStop = vi.fn()
    const drag = useWorkflowNodeDrag({ graphNodes: nodes, connectionDraft: ref(null), selectedNodeIds, selectNode,
      screenToWorld: (x, y) => ({ x: x / 2, y: y / 2 }), onMoved, onStop })
    drag.startNodeDrag(new MouseEvent('mousedown', { clientX: 20, clientY: 40 }), nodes.value[0]!)
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 60, clientY: 80 }))
    document.dispatchEvent(new MouseEvent('mouseup'))
    expect(nodes.value.map(n => [n.x, n.y])).toEqual([[30, 40], [130, 240]])
    expect(selectNode).not.toHaveBeenCalled()
    expect(onMoved).toHaveBeenCalledOnce()
    expect(onStop).toHaveBeenCalledOnce()
    drag.startNodeDrag(new MouseEvent('mousedown', { ctrlKey: true }), nodes.value[0]!)
    expect(drag.nodeDragState.value).toBeNull()
  })
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
