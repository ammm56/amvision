import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n, setI18nLocale } from '@/platform/i18n'
import { submitResourceDeletion } from '@/shared/api/resource-deletion'
import { ApiError } from '@/shared/api/error'
import DatasetManagerDialog from './DatasetManagerDialog.vue'
import ResourceDeleteButton from '@/shared/ui/components/ResourceDeleteButton.vue'
import type { DatasetVersionRelation } from '../services/dataset.service'

vi.mock('@/shared/api/resource-deletion', () => ({ submitResourceDeletion: vi.fn() }))
vi.mock('@/app/stores/session.store', () => ({ useSessionStore: () => ({ hasScopes: () => true }) }))
enableAutoUnmount(afterEach)
const version: DatasetVersionRelation = {
  dataset_id: 'dataset-tray', dataset_version_id: 'version-retained', project_id: 'project-1',
  task_type: 'classification', sample_count: 12, category_count: 2, split_names: ['train'], metadata: {},
}
function manager(versions = [version]) {
  return mount(DatasetManagerDialog, { attachTo: document.body, props: { projectId: 'project-1', versions, loading: false, loadError: null }, global: { plugins: [createPinia(), i18n], stubs: { teleport: true } } })
}
beforeEach(() => { vi.clearAllMocks(); setI18nLocale('zh-CN') })
afterEach(() => { document.body.innerHTML = ''; document.body.style.overflow = '' })

describe('dataset management', () => {
  it('lists retained versions independently of imports, searches IDs and restores search on cancel', async () => {
    const wrapper = manager([version, { ...version, project_id: 'other', dataset_version_id: 'other-version' }])
    await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('删除整个数据集')
    await wrapper.get('input').setValue('missing')
    expect(wrapper.text()).toContain('没有匹配的数据集')
    await wrapper.get('input').setValue('VERSION-RETAINED')
    await wrapper.get('tbody button').trigger('click')
    expect(wrapper.text()).toContain('存在外部引用时阻止删除')
    expect(document.activeElement).toBe(wrapper.get('[data-confirm-cancel]').element)
    await wrapper.get('[data-confirm-cancel]').trigger('click')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('VERSION-RETAINED')
    expect(submitResourceDeletion).not.toHaveBeenCalled()
  })

  it('retains the target when references block deletion and removes only after acceptance', async () => {
    const wrapper = manager()
    await wrapper.get('tbody button').trigger('click')
    vi.mocked(submitResourceDeletion).mockRejectedValueOnce(new ApiError(409, { message: '资源仍被引用', details: { blockers: [{ resource_id: 'training-1' }] } }))
    await wrapper.get('.confirm-dialog__actions .ui-button--danger').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('training-1')
    expect(wrapper.emitted('changed')).toBeUndefined()
    vi.mocked(submitResourceDeletion).mockResolvedValueOnce({ operation_id: 'delete-1', project_id: 'project-1', resource_kind: 'dataset-version', resource_id: version.dataset_version_id, state: 'committed', error: null })
    await wrapper.get('.confirm-dialog__actions .ui-button--danger').trigger('click')
    await flushPromises()
    expect(submitResourceDeletion).toHaveBeenLastCalledWith('dataset-version', 'version-retained', 'project-1')
    expect(wrapper.emitted('changed')).toHaveLength(1)
    expect(wrapper.findAll('tbody tr')).toHaveLength(0)
    expect(wrapper.text()).toContain('删除已受理')
  })

  it('ignores an in-flight deletion response after the project changes', async () => {
    let resolve!: (value: Awaited<ReturnType<typeof submitResourceDeletion>>) => void
    vi.mocked(submitResourceDeletion).mockReturnValueOnce(new Promise(done => { resolve = done }))
    const wrapper = manager()
    await wrapper.get('tbody button').trigger('click')
    await wrapper.get('.confirm-dialog__actions .ui-button--danger').trigger('click')
    await wrapper.setProps({ projectId: 'project-2' })
    expect(wrapper.emitted('close')).toHaveLength(1)
    resolve({ operation_id: 'delete-1', project_id: 'project-1', resource_kind: 'dataset-version', resource_id: 'version-retained', state: 'committed', error: null })
    await flushPromises()
    expect(wrapper.emitted('changed')).toBeUndefined()
  })

  it('clearly distinguishes import record deletion and submits the import kind', async () => {
    vi.mocked(submitResourceDeletion).mockResolvedValueOnce({ operation_id: 'delete-import', project_id: 'project-1', resource_kind: 'dataset-import', resource_id: 'import-1', state: 'committed', error: null })
    const wrapper = mount(ResourceDeleteButton, { props: { projectId: 'project-1', resourceId: 'import-1', kind: 'dataset-import' }, global: { plugins: [createPinia(), i18n], stubs: { teleport: true } } })
    await wrapper.get('button').trigger('click')
    expect(wrapper.text()).toContain('保留数据集版本、图片和标注')
    await wrapper.get('.confirm-dialog__actions .ui-button--danger').trigger('click')
    await flushPromises()
    expect(submitResourceDeletion).toHaveBeenCalledWith('dataset-import', 'import-1', 'project-1')
  })
})
