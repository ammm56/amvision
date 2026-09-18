import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import { i18n } from '@/platform/i18n'
import WorkflowEdgeDetailPanel from './WorkflowEdgeDetailPanel.vue'
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import type { WorkflowGraphEdge } from '../types'

it('连线详情使用端口显示名并保留原始连线标识', () => {
  const edge = { source_node_id: 'values', source_port: 'body', target_node_id: 'image', target_port: 'presentation' } as WorkflowGraphEdge
  const nodes = [
    { node: { node_id: 'values', parameters: { title: '检测结果' } }, outputs: [{ name: 'body', display_name: 'Display Data' }], inputs: [] },
    { node: { node_id: 'image', parameters: {} }, title: 'Image Preview', inputs: [{ name: 'presentation', display_name: 'Display Data' }], outputs: [] },
  ] as unknown as WorkflowGraphNodeView[]
  const wrapper = mount(WorkflowEdgeDetailPanel, { props: { edge, nodes }, global: { plugins: [i18n] } })
  expect(wrapper.findAll('strong').map(item => item.text())).toEqual(['检测结果 · Display Data', 'Image Preview · Display Data'])
  expect(edge.source_port).toBe('body')
  expect(edge.target_port).toBe('presentation')
  wrapper.unmount()
})
