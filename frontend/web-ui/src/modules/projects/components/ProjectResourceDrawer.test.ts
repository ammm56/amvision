import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { i18n } from '@/platform/i18n'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import ProjectResourceDrawer from './ProjectResourceDrawer.vue'
import { getDatasetVersionRelation } from '@/modules/datasets/services/dataset.service'
import { getDeploymentSourceModelDetail } from '@/modules/models/services/model.service'

vi.mock('@/modules/datasets/services/dataset.service', () => ({ getDatasetVersionRelation: vi.fn() }))
vi.mock('@/modules/models/services/model.service', () => ({ getDeploymentSourceModelDetail: vi.fn() }))
let wrapper: ReturnType<typeof mount> | undefined
afterEach(() => { wrapper?.unmount(); wrapper = undefined; document.body.innerHTML = ''; vi.resetAllMocks() })

it.each(['dataset-version', 'model-version'])('%s 详情关闭后等待退场，保持内容及关闭反馈完整', async kind => {
  vi.mocked(getDatasetVersionRelation).mockResolvedValue({ project_id: 'project-a', dataset_id: 'dataset-a', task_type: 'detection', sample_count: 24, category_count: 2, split_names: ['train', 'val'] } as never)
  vi.mocked(getDeploymentSourceModelDetail).mockResolvedValue({ model_id: 'model-a', task_type: 'detection', model_type: 'yolo11', versions: [{ model_version_id: 'version-a', source_kind: 'training', files: [{ logical_name: 'best.pt' }] }] } as never)
  wrapper = mount(ProjectResourceDrawer, { props: { projectId: 'project-a', item: { resource_id: 'version-a', target_id: 'source-a', kind, name: '验收资源', state: 'available', occurred_at: '2026-11-05T01:00:00Z' } }, attachTo: document.body, global: { plugins: [i18n], stubs: { teleport: true } } })
  await flushPromises()
  expect(wrapper.text()).toContain('验收资源')
  expect(wrapper.text()).toContain(kind === 'dataset-version' ? 'train / val' : 'best.pt')
  if (kind === 'model-version') {
    expect(wrapper.findAll('dt').map(item => item.text())).toContain('文件')
    expect(wrapper.text()).not.toContain('配置文件')
  }
  await wrapper.findAll('button').find(button => button.text() === '关闭')!.trigger('click')
  expect(wrapper.getComponent(SideDrawer).props('open')).toBe(false)
  expect(wrapper.emitted('close')).toBeUndefined()
  wrapper.getComponent(SideDrawer).vm.$emit('after-leave')
  expect(wrapper.emitted('close')).toHaveLength(1)
})
