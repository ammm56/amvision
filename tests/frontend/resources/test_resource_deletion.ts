import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import { i18n, setI18nLocale } from '@/platform/i18n'
import ResourceDeleteButton from '@/shared/ui/components/ResourceDeleteButton.vue'
import ResourceCleanupPanel from '@/shared/ui/components/ResourceCleanupPanel.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import { ApiError } from '@/shared/api/error'

const mocks = vi.hoisted(() => ({ submit: vi.fn(), list: vi.fn(), retry: vi.fn(), permission: vi.fn(() => true) }))
vi.mock('@/app/stores/session.store', () => ({ useSessionStore: () => ({ hasScopes: mocks.permission }) }))
vi.mock('@/shared/api/resource-deletion', () => ({ submitResourceDeletion: mocks.submit, listResourceDeletions: mocks.list, retryResourceDeletion: mocks.retry, deletionRevision: ref(0) }))
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers(); document.body.innerHTML = ''; setI18nLocale('zh-CN') })

describe('resource deletion', () => {
  it('confirms the captured target once and shows dependency IDs without claiming deletion', async () => {
    mocks.submit.mockRejectedValueOnce(new ApiError(409, { message: '资源仍被使用', details: { blockers: [{ resource_id: 'dependent-deployment' }] } }))
    const wrapper = mount(ResourceDeleteButton, { props: { kind: 'task', resourceId: 'task-one', projectId: 'project-one' }, attachTo: document.body, global: { plugins: [i18n] } })
    await wrapper.get('button').trigger('click')
    await wrapper.setProps({ projectId: 'project-two' })
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm')
    await flushPromises()
    expect(mocks.submit).toHaveBeenCalledWith('task', 'task-one', 'project-one')
    expect(document.body.textContent).toContain('dependent-deployment')
    expect(wrapper.emitted('accepted')).toBeUndefined()
    mocks.submit.mockResolvedValueOnce({ state: 'committed', operation_id: 'op' })
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm')
    await flushPromises()
    expect(wrapper.emitted('accepted')).toHaveLength(1)
    expect(wrapper.findComponent(ConfirmDialog).exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows persistent cleanup failure and retries without needing the deleted task', async () => {
    vi.useFakeTimers()
    mocks.list.mockResolvedValueOnce([{ operation_id: 'op', project_id: 'project', resource_id: 'deleted-task', resource_kind: 'task', state: 'committed', error: 'occupied' }]).mockResolvedValue([])
    mocks.retry.mockResolvedValue(undefined)
    const wrapper = mount(ResourceCleanupPanel, { props: { projectId: 'project' }, global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('清理未完成')
    expect(wrapper.text()).toContain('occupied')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(mocks.retry).toHaveBeenCalledWith('op')
    expect(wrapper.emitted('settled')).toHaveLength(1)
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not expose deletion without permission', () => {
    mocks.permission.mockReturnValueOnce(false)
    const wrapper = mount(ResourceDeleteButton, { props: { kind: 'dataset', resourceId: 'dataset', projectId: 'project' }, global: { plugins: [i18n] } })
    expect(wrapper.find('button').exists()).toBe(false)
    wrapper.unmount()
  })
})
