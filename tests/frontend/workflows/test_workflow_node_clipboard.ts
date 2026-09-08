import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useWorkflowNodeClipboard } from '@/workflows/workflow-editor/nodes/useWorkflowNodeClipboard'
import { useWorkflowGraphNodeViews } from '@/workflows/workflow-editor/nodes/useWorkflowGraphNodeViews'

function setup() {
  const views = useWorkflowGraphNodeViews({ nodeCatalog: ref(null), graphEdges: ref([]) })
  const source = views.buildGraphNodeView({ node_id: 'source', node_type_id: 'custom.node', parameters: { values: [{ x: 1 }], mask: { path: '/mask.png' } }, enabled: false, ui_state: { x: 10, y: 20, width: 310, collapsed: true }, metadata: { custom: { a: 1 } } }, 0, new Map())
  const graphNodes = ref([source])
  const busy = ref(false)
  const commitParameters = vi.fn(() => true)
  const onPasted = vi.fn()
  const clipboard = useWorkflowNodeClipboard({ graphNodes, isBusy: () => busy.value, commitParameters,
    createNodeId: () => `copy_${graphNodes.value.length}`, buildView: node => views.buildGraphNodeView(node, 0, new Map()),
    readHeight: () => 120, readPastePosition: () => ({ x: 400, y: 200 }), onCopied: vi.fn(), onPasted })
  return { clipboard, graphNodes, busy, commitParameters, onPasted }
}

describe('节点复制快照与粘贴', () => {
  it('保留真实参数、外观和资源引用，源和各副本相互独立', () => {
    const { clipboard, graphNodes } = setup()
    expect(clipboard.copy('source')).toBe(true)
    graphNodes.value[0]!.node.parameters.values = [{ x: 99 }]
    graphNodes.value[0]!.width = 500
    expect(clipboard.paste({ x: 100, y: 150 })).toBe(true)
    expect(clipboard.paste({ x: 100, y: 150 })).toBe(true)
    const [first, second] = graphNodes.value.slice(1)
    expect(first!.node).toMatchObject({ node_id: 'copy_1', node_type_id: 'custom.node', enabled: false, parameters: { values: [{ x: 1 }], mask: { path: '/mask.png' } }, ui_state: { x: 100, y: 150, width: 310, collapsed: true } })
    expect(second!.node.ui_state).toMatchObject({ x: 132, y: 182 })
    ;(first!.node.parameters.values as Array<{ x: number }>)[0]!.x = 42
    expect(second!.node.parameters.values).toEqual([{ x: 1 }])
    expect(first!.node.metadata).not.toBe(second!.node.metadata)
    graphNodes.value.splice(0, 1)
    expect(clipboard.paste({ x: 800, y: 500 })).toBe(true)
    expect(graphNodes.value.at(-1)!.x).toBe(800)
  })

  it('无快照、忙碌和无效坐标不新增节点；清空后不可粘贴', () => {
    const { clipboard, graphNodes, busy } = setup()
    expect(clipboard.paste()).toBe(false)
    busy.value = true
    expect(clipboard.copy('source')).toBe(false)
    busy.value = false
    clipboard.copy('source')
    busy.value = true
    expect(clipboard.paste()).toBe(false)
    busy.value = false
    expect(clipboard.paste({ x: NaN, y: 1 })).toBe(false)
    clipboard.clear()
    expect(clipboard.canPaste.value).toBe(false)
    expect(clipboard.paste()).toBe(false)
    expect(graphNodes.value).toHaveLength(1)
  })

  it('参数提交失败保留上一次快照，键盘位置由当前画布提供', () => {
    const { clipboard, graphNodes, commitParameters } = setup()
    clipboard.copy('source')
    commitParameters.mockReturnValue(false)
    expect(clipboard.copy('source')).toBe(false)
    expect(clipboard.copy('missing')).toBe(false)
    clipboard.paste()
    expect(graphNodes.value.at(-1)!.node.ui_state).toMatchObject({ x: 400, y: 200 })
  })
})
