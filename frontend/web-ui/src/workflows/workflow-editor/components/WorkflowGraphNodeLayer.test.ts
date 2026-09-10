import { mount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'
import { expect, it, vi } from 'vitest'
import WorkflowGraphNodeLayer from './WorkflowGraphNodeLayer.vue'
import WorkflowNodeParameterWidgets from './WorkflowNodeParameterWidgets.vue'

vi.mock('@/platform/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

it('updates only the changed node and preserves node and parameter events', async () => {
  const statuses = reactive(new Map<string, string>())
  const nodes = ['a', 'b'].map(node_id => ({ node: { node_id, node_type_id: 'test', enabled: true }, x: 0, y: 0, width: 200 }))
  const readPortRows = vi.fn(() => [])
  const field = { name: 'text' }
  const props: any = {
    nodes, selectedNodeId: null, lastPreviewFailureNodeId: null,
    readNodeHeight: () => 200, readTitle: (node: any) => node.node.node_id, readPortRows,
    readPortLabel: () => '', isPortConnected: () => false, isSelectedEdgeEndpoint: () => false, isDraftAnchorPort: () => false,
    readParameterFields: () => [field], readParameterLabel: () => '', readParameterEnumIndex: () => '', readParameterEnumOptions: () => [],
    isBooleanParameter: () => false, readParameterBooleanValue: () => false, isNumberParameter: () => false,
    readParameterTextValue: () => '', isStringParameter: () => true, isColorMapParameter: () => false, readParameterValue: () => '',
    isJsonParameter: () => false, readParameterJsonTextValue: () => '', readParameterJsonPlaceholder: () => '', readInputSourceLabel: () => '',
    readPreviewDisplay: () => null, readPreviewDisplayTooltip: () => '', readPreviewDurationMs: () => null,
    readPreviewStatus: (id: string) => statuses.get(id) ?? '',
  }
  const wrapper = mount(WorkflowGraphNodeLayer, { props, global: { stubs: { WorkflowNodeParameterWidgets: true, WorkflowNodePreviewDisplay: true } } })
  readPortRows.mockClear()
  statuses.set('a', 'running')
  await nextTick()
  expect(readPortRows.mock.calls.map((call: any) => call[0].node.node_id)).toEqual(['a'])
  expect(wrapper.findAll('.workflow-graph-node')[0]!.text()).toContain('running')
  await wrapper.findAll('.workflow-graph-node')[1]!.trigger('click')
  expect(wrapper.emitted('nodeClick')?.[0]).toEqual(['b'])
  wrapper.findAllComponents(WorkflowNodeParameterWidgets)[1]!.vm.$emit('update-value', nodes[1], field, 'new')
  expect(wrapper.emitted('updateValueParameter')?.[0]).toEqual([nodes[1], field, 'new'])
  wrapper.unmount()
})
