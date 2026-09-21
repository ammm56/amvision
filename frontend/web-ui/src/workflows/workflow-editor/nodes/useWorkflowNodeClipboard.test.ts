import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useWorkflowNodeClipboard } from './useWorkflowNodeClipboard'
import type { WorkflowGraphNode, WorkflowGraphEdge, WorkflowGraphGroup, NodeDefinition, NodePortDefinition } from '../types'
import type { WorkflowGraphNodeView } from './useWorkflowGraphNodeViews'

const port = { name: 'value', payload_type_id: 'value', multiple: false } as NodePortDefinition
function view(node: WorkflowGraphNode): WorkflowGraphNodeView {
  return { node, x: Number(node.ui_state.x), y: Number(node.ui_state.y), width: 100, title: 'test',
    inputs: [port], outputs: [port], definition: {} as NodeDefinition }
}
function setup() {
  const nodes = ref(['a', 'b', 'outside'].map((id, i) => view({ node_id: id, node_type_id: 'same', enabled: i !== 1, metadata: {},
    parameters: { zero: 0, empty: '', no: false, explicit: null, nested: { value: 1 } }, ui_state: { x: i * 120, y: i * 50, width: 100 } })))
  const edges = ref<WorkflowGraphEdge[]>([
    { edge_id: 'internal', source_node_id: 'a', source_port: 'value', target_node_id: 'b', target_port: 'value', metadata: { order: 1 } },
    { edge_id: 'external', source_node_id: 'b', source_port: 'value', target_node_id: 'outside', target_port: 'value', metadata: {} },
  ])
  const groups = ref<WorkflowGraphGroup[]>([{ group_id: 'g', name: '检测', rect: { x: -10, y: -20, width: 250, height: 200 },
    member_node_ids: ['a', 'b'], member_note_ids: ['note-original'], membership_policy: 'full-containment', color: '#22b8cf', enabled: false, locked: true, collapsed: false, metadata: { value: 1 } }])
  const options = { graphNodes: nodes, graphEdges: edges, graphGroups: groups, isBusy: () => false, commitParameters: () => true,
    createNodeId: () => 'same', buildView: view, readHeight: () => 80, readPastePosition: () => ({ x: 1000, y: 1000 }), onCopied: vi.fn(), onPasted: vi.fn(), onError: vi.fn() }
  return { nodes, edges, groups, options, clipboard: useWorkflowNodeClipboard(options) }
}
describe('fragment clipboard', () => {
  it('完整组选中后保留配置、几何、成员映射，连续粘贴不引用原节点或便签', () => {
    const { nodes, groups, clipboard } = setup()
    expect(clipboard.copy(['a', 'b'], ['g'])).toBe(true)
    groups.value[0]!.name = 'changed'
    clipboard.paste()
    expect(groups.value[1]).toMatchObject({ group_id: 'g_copy', name: '检测', rect: { x: 1000, y: 1000, width: 250, height: 200 },
      member_node_ids: ['same', 'same_2'], member_note_ids: [], enabled: false, locked: true, color: '#22b8cf' })
    expect(nodes.value[3]).toMatchObject({ x: 1010, y: 1020 })
    expect(nodes.value[4]!.node.enabled).toBe(false)
    clipboard.paste()
    expect(groups.value[2]).toMatchObject({ group_id: 'g_copy_2', rect: { x: 1032, y: 1032 }, member_node_ids: ['same_3', 'same_4'] })
    expect(groups.value[0]!.member_node_ids).toEqual(['a', 'b'])
  })
  it('部分节点、未选中组框均不复制组，缺失目录时整批不落图', () => {
    const { nodes, groups, options, clipboard } = setup()
    clipboard.copy(['a'], ['g'])
    clipboard.paste()
    expect(groups.value).toHaveLength(1)
    clipboard.copy(['a', 'b'])
    clipboard.paste()
    expect(groups.value).toHaveLength(1)
    clipboard.copy(['a', 'b'], ['g'])
    options.buildView = node => ({ ...view(node), definition: null })
    const count = nodes.value.length
    expect(clipboard.paste()).toBe(false)
    expect(nodes.value).toHaveLength(count)
    expect(groups.value).toHaveLength(1)
  })
  it('copies only internal edges, preserves values and relative layout, and reserves IDs across repeated types and pastes', () => {
    const { nodes, edges, clipboard } = setup()
    expect(clipboard.copy(['a', 'b'])).toBe(true)
    nodes.value[0]!.node.parameters.zero = 9
    expect(clipboard.paste()).toBe(true)
    expect(nodes.value.slice(3).map(n => [n.node.node_id, n.x, n.y])).toEqual([['same', 1000, 1000], ['same_2', 1120, 1050]])
    expect(nodes.value[3]!.node.parameters).toMatchObject({ zero: 0, no: false, empty: '', explicit: null })
    expect(nodes.value[4]!.node.enabled).toBe(false)
    expect(edges.value.slice(2)).toEqual([{ ...edges.value[0], edge_id: 'internal_copy', source_node_id: 'same', target_node_id: 'same_2' }])
    clipboard.paste()
    expect(nodes.value[5]!.x).toBe(1032)
    expect(new Set(nodes.value.map(n => n.node.node_id)).size).toBe(7)
    expect(new Set(edges.value.map(e => e.edge_id)).size).toBe(4)
    clipboard.clear()
    expect(clipboard.paste()).toBe(false)
  })
  it('does not mutate the graph on missing catalog or invalid ports and preserves the old snapshot after parameter failure', () => {
    const { nodes, edges, options, clipboard } = setup()
    clipboard.copy(['a', 'b'])
    options.commitParameters = () => false
    expect(clipboard.copy(['outside'])).toBe(false)
    options.buildView = node => ({ ...view(node), outputs: [] })
    expect(clipboard.paste()).toBe(false)
    expect(nodes.value.length).toBe(3)
    expect(edges.value.length).toBe(2)
    options.buildView = node => ({ ...view(node), definition: null })
    expect(clipboard.paste()).toBe(false)
    options.buildView = view
    expect(clipboard.paste()).toBe(true)
    expect(nodes.value.length).toBe(5)
  })
})
