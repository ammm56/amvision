import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ImportedModelAssets from '@/modules/models/components/ImportedModelAssets.vue'
import ResourceCleanupPanel from '@/shared/ui/components/ResourceCleanupPanel.vue'
import { apiRequest } from '@/shared/api/http-client'
import * as cleanup from '@/shared/api/resource-deletion'
import { i18n } from '@/platform/i18n'

vi.mock('@/shared/api/http-client', () => ({ apiRequest: vi.fn() }))
vi.mock('@/shared/api/resource-deletion', async () => {
  const original = await vi.importActual<typeof cleanup>('@/shared/api/resource-deletion')
  return { ...original, listResourceDeletions: vi.fn(), retryResourceDeletion: vi.fn() }
})
afterEach(() => vi.resetAllMocks())

describe('资源管理的项目切换', () => {
  it.each([false, true])('导入模型丢弃旧项目返回，失败：%s', async (fails) => {
    let resolve!: (value: unknown) => void
    let reject!: (error: Error) => void
    vi.mocked(apiRequest).mockReturnValueOnce(new Promise((ok, fail) => { resolve = ok; reject = fail })).mockResolvedValue([])
    const wrapper = mount(ImportedModelAssets, { props: { projectId: 'old' } })
    await wrapper.setProps({ projectId: 'new' })
    if (fails) reject(new Error('old error'))
    else resolve([{ resource_id: 'old-id', model_name: 'old model', byte_size: 1 }])
    await flushPromises()
    expect(wrapper.text()).not.toContain('old')
    wrapper.unmount()
  })

  it('切换项目时立即清空旧模型，避免在新项目删除旧条目', async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce([{ resource_id: 'old-id', model_name: 'old model', byte_size: 1 }]).mockReturnValue(new Promise(() => {}))
    const wrapper = mount(ImportedModelAssets, { props: { projectId: 'old' } })
    await flushPromises()
    expect(wrapper.text()).toContain('old model')
    await wrapper.setProps({ projectId: 'new' })
    expect(wrapper.text()).not.toContain('old model')
    expect(wrapper.findAll('button')).toHaveLength(0)
    wrapper.unmount()
  })

  it.each([false, true])('清理重试结束不能修改新项目，失败：%s', async (fails) => {
    let resolve!: () => void
    let reject!: (error: Error) => void
    vi.mocked(cleanup.listResourceDeletions).mockResolvedValueOnce([{ operation_id: 'op', project_id: 'old', resource_id: 'old-id', resource_kind: 'task', state: 'committed', error: null }]).mockResolvedValue([])
    vi.mocked(cleanup.retryResourceDeletion).mockReturnValue(new Promise((ok, fail) => { resolve = ok; reject = fail }))
    const wrapper = mount(ResourceCleanupPanel, { props: { projectId: 'old' }, global: { plugins: [i18n] } })
    await flushPromises()
    await wrapper.get('button').trigger('click')
    await wrapper.setProps({ projectId: 'new' })
    await flushPromises()
    const requests = vi.mocked(cleanup.listResourceDeletions).mock.calls.length
    if (fails) reject(new Error('old error'))
    else resolve()
    await flushPromises()
    expect(wrapper.text()).not.toContain('old error')
    expect(cleanup.listResourceDeletions).toHaveBeenCalledTimes(requests)
    wrapper.unmount()
  })
})
