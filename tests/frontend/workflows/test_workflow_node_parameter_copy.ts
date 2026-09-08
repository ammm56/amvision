import { ref } from 'vue'
import { expect, it, vi } from 'vitest'
import { useWorkflowNodeParameters } from '@/workflows/workflow-editor/parameters/useWorkflowNodeParameters'
import type { NodeDefinition, NodeParameterUiField, WorkflowGraphNode } from '@/workflows/workflow-editor/types'

it('单节点提交后保留其他节点的 JSON 编辑标记', () => {
  const field: NodeParameterUiField = { parameter_name: 'config', display_name: 'Config', description: '', group_id: 'default', order: 0, required: false, hidden: false, readonly: false, default_value: {}, enum_options: [], widget: 'auto', json_schema: { type: 'object' } }
  const definition = { parameter_ui_schema: { fields: [field], groups: [] } } as unknown as NodeDefinition
  const makeNode = (node_id: string) => ({ definition, node: { node_id, node_type_id: 'custom', parameters: {}, enabled: true, metadata: {}, ui_state: {} } as WorkflowGraphNode })
  const a = makeNode('a'), b = makeNode('b')
  const error = vi.fn()
  const parameters = useWorkflowNodeParameters({ complexParameterDrafts: ref({}), readNodeTitle: view => view.node.node_id, readParameterLabel: () => 'Config', setStatusMessage: vi.fn(), setErrorMessage: error })
  function edit(node: typeof a, value: string) {
    const target = document.createElement('textarea'); target.value = value
    const event = new Event('input'); Object.defineProperty(event, 'target', { value: target })
    parameters.updateNodeParameterJsonDraft(node, field, event)
  }
  edit(a, '{"value":1}'); edit(b, '{')
  expect(parameters.commitPendingNodeParameterDrafts([a])).toBe(true)
  expect(a.node.parameters).toEqual({ config: { value: 1 } })
  expect(parameters.hasPendingNodeParameterDrafts()).toBe(true)
  expect(parameters.commitPendingNodeParameterDrafts([a, b])).toBe(false)
  expect(error).toHaveBeenCalledOnce()
  edit(b, '{"value":2}')
  expect(parameters.commitPendingNodeParameterDrafts([a, b])).toBe(true)
  expect(b.node.parameters).toEqual({ config: { value: 2 } })
  expect(parameters.hasPendingNodeParameterDrafts()).toBe(false)
})
