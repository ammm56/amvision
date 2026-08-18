import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useWorkflowCanvasPan } from './useWorkflowCanvasPan'
import { useWorkflowNodeDrag } from './useWorkflowNodeDrag'
import { useWorkflowPortConnections } from './useWorkflowPortConnections'

describe('workflow 画布鼠标拖动', () => {
  it('画布只在左键按下期间移动并在窗口失焦时停止', () => {
    const viewportX = ref(10)
    const viewportY = ref(20)
    const pan = useWorkflowCanvasPan({
      viewportX,
      viewportY,
      shouldIgnorePointerTarget: () => false,
    })
    const startEvent = new MouseEvent('mousedown', {
      button: 0,
      clientX: 100,
      clientY: 100,
      cancelable: true,
    })

    pan.startStagePan(startEvent)
    expect(startEvent.defaultPrevented).toBe(true)
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 140, clientY: 130 }))
    expect([viewportX.value, viewportY.value]).toEqual([50, 50])

    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 0, clientX: 180, clientY: 170 }))
    expect([viewportX.value, viewportY.value]).toEqual([50, 50])
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 220, clientY: 210 }))
    expect([viewportX.value, viewportY.value]).toEqual([50, 50])

    pan.startStagePan(new MouseEvent('mousedown', { button: 0, clientX: 220, clientY: 210, cancelable: true }))
    window.dispatchEvent(new Event('blur'))
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 260, clientY: 250 }))
    expect([viewportX.value, viewportY.value]).toEqual([50, 50])
  })

  it('节点忽略非左键并在检测到左键释放后立即结束拖动', () => {
    const node = {
      node: { node_id: 'node-1', ui_state: {} as Record<string, unknown> },
      x: 100,
      y: 80,
      width: 240,
    }
    const onStop = vi.fn()
    const nodeDrag = useWorkflowNodeDrag({
      graphNodes: ref([node]),
      connectionDraft: ref(null),
      screenToWorld: (clientX, clientY) => ({ x: clientX, y: clientY }),
      selectNode: vi.fn(),
      onStop,
    })

    nodeDrag.startNodeDrag(new MouseEvent('mousedown', { button: 2, clientX: 110, clientY: 90 }), node)
    expect(nodeDrag.nodeDragState.value).toBeNull()

    nodeDrag.startNodeDrag(new MouseEvent('mousedown', { button: 0, clientX: 110, clientY: 90, cancelable: true }), node)
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 150, clientY: 130 }))
    expect([node.x, node.y]).toEqual([140, 120])

    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 0, clientX: 190, clientY: 170 }))
    expect(nodeDrag.nodeDragState.value).toBeNull()
    expect([node.x, node.y]).toEqual([140, 120])
    expect(onStop).toHaveBeenCalledOnce()
  })

  it('端口连线丢失 mouseup 时取消草稿而不打开节点选择器', () => {
    const openNodePicker = vi.fn()
    const connections = useWorkflowPortConnections({
      screenToWorld: (clientX, clientY) => ({ x: clientX, y: clientY }),
      connectDraftToPort: vi.fn(() => false),
      openNodePickerFromConnectionDraft: openNodePicker,
      suppressNodeClickOnce: vi.fn(),
      clearNodePicker: vi.fn(),
    })

    connections.startPortConnectionDraft(
      new MouseEvent('mousedown', { button: 0, clientX: 10, clientY: 20, cancelable: true }),
      {
        anchorDirection: 'output',
        anchorNodeId: 'node-1',
        anchorPort: 'image',
        anchorX: 10,
        anchorY: 20,
      },
    )
    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 1, clientX: 30, clientY: 40 }))
    expect(connections.connectionDraft.value?.hasMoved).toBe(true)

    document.dispatchEvent(new MouseEvent('mousemove', { buttons: 0, clientX: 50, clientY: 60 }))
    expect(connections.connectionDraft.value).toBeNull()
    expect(openNodePicker).not.toHaveBeenCalled()
  })
})
