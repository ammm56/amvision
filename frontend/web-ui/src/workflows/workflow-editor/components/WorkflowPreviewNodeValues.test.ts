import { mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import WorkflowPreviewNodeValues from './WorkflowPreviewNodeValues.vue'
import type { WorkflowPreviewRun } from '../types'

vi.mock('@/platform/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

function run(value: object, readValue = vi.fn()): WorkflowPreviewRun {
  return { preview_run_id: 'r', values: [{ node_id: 'n', output_port: 'value', revision: 1, value }], readValue } as unknown as WorkflowPreviewRun
}

it('renders false and zero without treating them as missing values', async () => {
  const wrapper = mount(WorkflowPreviewNodeValues, { props: { run: run({ kind: 'inline', value: false }), nodeId: 'n' } })
  expect(wrapper.get('pre').text()).toBe('false')
  await wrapper.setProps({ run: run({ kind: 'inline', value: 0 }) })
  expect(wrapper.get('pre').text()).toBe('0')
  wrapper.unmount()
})

it('reads full JSON through explicit bounded pages and supports nested paths', async () => {
  const readValue = vi.fn().mockResolvedValue({ value: { items: { summary: true } }, children: [{ key: 'items', path: ['items'], total: 2000 }], path: [], offset: 0, limit: 50, total: 1, has_more: false })
  const wrapper = mount(WorkflowPreviewNodeValues, { props: { run: run({ kind: 'json', blob_id: 'blob' }, readValue), nodeId: 'n' } })
  expect(readValue).not.toHaveBeenCalled()
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(readValue).toHaveBeenCalledWith('blob', 0, [])
  await wrapper.findAll('button').find(button => button.text().includes('items'))!.trigger('click')
  expect(readValue).toHaveBeenLastCalledWith('blob', 0, ['items'])
  wrapper.unmount()
})

it('ignores a page returned after switching the selected node', async () => {
  let finish!: (value: unknown) => void
  const readValue = vi.fn(() => new Promise(resolve => { finish = resolve }))
  const wrapper = mount(WorkflowPreviewNodeValues, { props: { run: run({ kind: 'json', blob_id: 'blob' }, readValue), nodeId: 'n' } })
  await wrapper.get('button').trigger('click')
  await wrapper.setProps({ nodeId: 'other' })
  finish({ value: 'stale', children: [], path: [], offset: 0, limit: 50, total: 1, has_more: false })
  await flushPromises()
  expect(wrapper.text()).not.toContain('stale')
  wrapper.unmount()
})
