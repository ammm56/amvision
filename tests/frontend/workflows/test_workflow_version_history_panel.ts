import { flushPromises, mount } from '@vue/test-utils'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import { DropdownMenuItem } from 'reka-ui'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import { i18n, setI18nLocale, type SupportedLocale } from '@/platform/i18n'
import WorkflowVersionHistoryPanel from '@/workflows/workflow-editor/components/WorkflowVersionHistoryPanel.vue'
import type { WorkflowAppVersion } from '@/workflows/workflow-editor/types'
describe('version panel locale and actions', () => {
  it.each([['zh-CN', '版本'], ['en-US', 'Versions'], ['ja-JP', 'バージョン'], ['ko-KR', '버전']] as Array<[SupportedLocale, string]>)('renders %s without leaking translation keys and emits direct selection', async (locale, title) => {
    setI18nLocale(locale)
    const version = { workflow_app_version_id: 'v1', version_number: 1, display_version: 'v1', state: 'archived', created_at: '2026-09-07T10:00:00Z', release_notes: 'notes' } as WorkflowAppVersion
    const wrapper = mount(WorkflowVersionHistoryPanel, { attachTo: document.body, global: { plugins: [i18n] }, props: { open: true, versions: [version], loading: false, selectedId: null, error: null, hasMore: true } })
    expect(wrapper.get('aside').text()).toContain(title)
    expect(wrapper.text()).not.toContain('workflowEditor.')
    expect(wrapper.get('.workflow-history__load').text()).toBe('V1')
    expect(wrapper.get('.workflow-history__load').attributes('aria-label')).toBe('V1')
    await wrapper.get('.workflow-history__menu-trigger').trigger('click')
    await flushPromises()
    const items = wrapper.findAllComponents(DropdownMenuItem)
    expect(items).toHaveLength(4)
    expect(items.map(item => item.text()).join(' ')).not.toMatch(/workflowEditor\.|common\./)
    await items[2]!.trigger('click')
    await flushPromises()
    expect(wrapper.emitted('export')).toEqual([[version]])
    await wrapper.get('.workflow-history__load').trigger('click')
    expect(wrapper.emitted('select')).toEqual([[version]])
    await wrapper.setProps({ loading: true })
    expect(wrapper.get('.workflow-history__load').attributes('disabled')).toBeDefined()
    wrapper.unmount()
    setI18nLocale('zh-CN')
  })
})


it('uses a dedicated non-modal panel and exposes rename, export and explicit deletion', async () => {
  setI18nLocale('zh-CN')
  const version = { workflow_app_version_id: 'v1', version_number: 1, display_version: 'v1', state: 'published', created_at: '2026-09-07T10:00:00Z' } as WorkflowAppVersion
  const wrapper = mount(WorkflowVersionHistoryPanel, { attachTo: document.body, global: { plugins: [i18n] }, props: { open: true, versions: [version], loading: false, selectedId: null, error: null, hasMore: false } })
  expect(wrapper.find('[role=dialog]').exists()).toBe(false)
  expect(wrapper.get('aside').classes()).not.toContain('workflow-graph-inspector-panel')
  expect(wrapper.findAll('ol > li')).toHaveLength(2)
  async function choose(label: string) {
    await wrapper.get('.workflow-history__menu-trigger').trigger('click')
    const item = wrapper.findAllComponents(DropdownMenuItem).find(item => item.text() === label)!
    await item.trigger('click')
    await nextTick()
  }
  await choose('命名')
  expect(wrapper.emitted('select')).toBeUndefined()
  const dialog = wrapper.getComponent(ConfirmDialog)
  expect(dialog.props('title')).toBe('版本')
  expect(dialog.text()).not.toMatch(/workflowEditor\.|common\./)
  expect(wrapper.get('aside').find('input').exists()).toBe(false)
  await dialog.get('input').setValue('生产基线')
  await dialog.get('textarea').setValue('现场版本说明')
  await dialog.get('.confirm-dialog__actions button:last-child').trigger('click')
  expect(wrapper.emitted('rename')).toEqual([[version, '生产基线', '现场版本说明']])
  await wrapper.setProps({ loading: true })
  await wrapper.setProps({ loading: false })
  await choose('删除')
  expect(wrapper.emitted('delete')).toBeUndefined()
  expect(wrapper.get('.workflow-history__edit').text()).toContain('删除 v1')
  await wrapper.get('.workflow-history__edit button').trigger('click')
  expect(wrapper.emitted('delete')).toEqual([[version]])
  wrapper.unmount()
})
