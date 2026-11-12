import { expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { reactive } from 'vue'
import { createI18n } from 'vue-i18n'
import DatasetCatalogPage from '../../../frontend/web-ui/src/modules/datasets/pages/DatasetCatalogPage.vue'
import SelectField from '../../../frontend/web-ui/src/shared/ui/components/Select.vue'

const route = reactive({ query: { tab: 'versions', state: '', offset: '0' } })
const api = vi.hoisted(() => ({ listDatasetVersionPage: vi.fn() }))
vi.mock('../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service', () => api)
vi.mock('../../../frontend/web-ui/src/app/stores/project.store', () => ({ useProjectStore: () => ({ selectedProjectId: 'p' }) }))
vi.mock('../../../frontend/web-ui/src/app/stores/session.store', () => ({ useSessionStore: () => ({ hasScopes: () => true }) }))
vi.mock('../../../frontend/web-ui/src/app/stores/feedback.store', () => ({ useFeedbackStore: () => ({ info: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({
  push: vi.fn(), replace: vi.fn(({ query }) => { Object.assign(route.query, query) }),
}) }))

it('版本筛选传给后端、重置分页，未检查状态不能被显示为可用', async () => {
  api.listDatasetVersionPage.mockResolvedValue({ total: 1, items: [{
    dataset_id: 'd', dataset_version_id: 'v', version_number: 1, display_name: '数据集',
    task_type: 'detection', metadata: {}, split_counts: {}, sample_count: 0, category_count: 0,
  }] })
  const wrapper = shallowMount(DatasetCatalogPage, { global: {
    plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
    stubs: { ResourceTable: { template: '<table><slot /></table>' } },
  } })
  await flushPromises()
  expect(wrapper.findComponent({ name: 'StatusBadge' }).props('label')).toBe('未检查')
  const filter = wrapper.findAllComponents(SelectField).at(-1)
  expect(filter).toBeDefined()
  expect(filter!.props('options').map((item) => item.value)).toContain('missing')
  route.query.offset = '20'
  await flushPromises()
  filter!.vm.$emit('update:modelValue', 'missing')
  await flushPromises()
  expect(api.listDatasetVersionPage).toHaveBeenLastCalledWith(expect.objectContaining({ state: 'missing', offset: 0 }), expect.anything())
  wrapper.unmount()
})
