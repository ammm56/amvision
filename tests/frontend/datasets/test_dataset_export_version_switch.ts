import { expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetTransferPage from '../../../frontend/web-ui/src/modules/datasets/pages/DatasetTransferPage.vue'

const route = { path: '/datasets/export', query: { dataset: 'd', version: 'id2' } }
const api = vi.hoisted(() => ({
  getDatasetWorkspace: vi.fn(), getDatasetCategories: vi.fn(),
  listDatasetCatalog: vi.fn(), listDatasetVersionPage: vi.fn(),
}))
vi.mock('../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service', () => api)
vi.mock('../../../frontend/web-ui/src/modules/datasets/services/dataset.service', () => ({
  getDatasetExportFormats: async () => ({ format_types_by_task_type: { detection: ['coco-detection-v1'] } }),
}))
vi.mock('../../../frontend/web-ui/src/app/stores/project.store', () => ({ useProjectStore: () => ({ selectedProjectId: 'p' }) }))
vi.mock('../../../frontend/web-ui/src/app/stores/session.store', () => ({ useSessionStore: () => ({ hasScopes: () => true }) }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({}), onBeforeRouteLeave: vi.fn(), onBeforeRouteUpdate: vi.fn() }))

it('列表失败重试仍选择链接指定的版本，连续切换时保留表格、忽略旧响应', async () => {
  const rows = [1, 2, 3].map(n => ({
    dataset_id: 'd', dataset_version_id: 'id' + n, version_number: n, display_name: '零件',
    task_type: 'detection', sample_count: n, object_count: n, category_count: 1,
    categories: [{ category_id: 0, name: '物体' }], metadata: {}, split_counts: { train: n },
  }))
  api.listDatasetCatalog.mockResolvedValue({ total: 1, items: [rows[0]] })
  api.listDatasetVersionPage.mockRejectedValueOnce(new Error('暂不可用')).mockResolvedValue({ total: 3, items: rows })
  api.getDatasetCategories.mockResolvedValue({ items: [] })
  let resolveFirst!: (row: typeof rows[number]) => void
  api.getDatasetWorkspace.mockImplementation((_dataset, id) => id === 'id1'
    ? new Promise(resolve => { resolveFirst = resolve })
    : Promise.resolve(rows.find(r => r.dataset_version_id === id)))
  const w = shallowMount(DatasetTransferPage, { global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
    stubs: { ResourceTable: { template: '<table><slot /></table>' }, Button: { template: '<button><slot /></button>' } },
  } })
  try {
    await flushPromises()
    expect(api.getDatasetWorkspace).not.toHaveBeenCalled()
    await w.findAll('button').find(b => b.text() === '重试加载列表')!.trigger('click')
    await flushPromises()
    expect(w.get('.source-choice').text()).toContain('v2')
    const table = w.get('table').element
    await w.get('input[aria-label="零件 v1"]').trigger('click')
    expect(w.get('.source-choice').text()).toContain('v1')
    expect(w.get('fieldset').attributes('disabled')).toBeUndefined()
    expect(w.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    const pendingSignal = api.getDatasetWorkspace.mock.lastCall![2] as AbortSignal
    await w.get('input[aria-label="零件 v3"]').trigger('click')
    await flushPromises()
    expect(pendingSignal.aborted).toBe(true)
    resolveFirst(rows[0])
    await flushPromises()
    expect(w.get('table').element).toBe(table)
    expect(w.get('.source-choice').text()).toContain('v3')
    expect(w.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
  } finally { w.unmount() }
})
