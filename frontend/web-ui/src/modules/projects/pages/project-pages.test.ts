import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import { useSessionStore } from '@/app/stores/session.store'
import { useProjectStore } from '@/app/stores/project.store'
import { i18n } from '@/platform/i18n'
import { ApiError } from '@/shared/api/error'
import ProjectListPage from './ProjectListPage.vue'
import ProjectOverviewPage from './ProjectOverviewPage.vue'
import ProjectDialogs from '../components/ProjectDialogs.vue'
import { listProjects, getProject, getProjectOverview } from '../services/project.service'

vi.mock('../services/project.service', () => ({ listProjects: vi.fn(), getProject: vi.fn(), getProjectOverview: vi.fn(), getProjectSummary: vi.fn() }))
const project = { project_id: 'project-1', display_name: '真实项目', resource_counts: { datasets: 2, models: 3, apps: 4, deployments: 5 } }
const page = { items: [project], pagination: { offset: 0, limit: 20, totalCount: 1, hasMore: false, nextOffset: null } }
const overview = { recent: [{ resource_id: 'task-1', name: '训练任务', kind: 'yolo11-training', state: 'succeeded', occurred_at: '2026-11-04T01:00:00Z' }], active: [], total: 21, offset: 0, limit: 5, checked_at: '2026-11-04T01:00:00Z', access: { datasets: true, models: true, apps: true, deployments: true, runtimes: true, tasks: true } }
let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  setActivePinia(createPinia())
  useSessionStore().currentUser = { principal_id: 'admin', scopes: ['*'], project_ids: [], allowed_pages: null } as never
  vi.mocked(listProjects).mockResolvedValue(page)
  vi.mocked(getProject).mockResolvedValue(project)
  vi.mocked(getProjectOverview).mockResolvedValue(overview)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; document.body.innerHTML = ''; sessionStorage.clear(); vi.resetAllMocks() })
async function open(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects', component: ProjectListPage }, { path: '/projects/:projectId', component: ProjectOverviewPage }] })
  await router.push(path); await router.isReady()
  wrapper = mount(RouterView, { attachTo: document.body, global: { plugins: [i18n, router] } }); await flushPromises()
  return router
}
it('列表刷新失败保留上次结果；首次失败不能显示没有项目', async () => {
  await open('/projects'); expect(wrapper!.text()).toContain('真实项目')
  vi.mocked(listProjects).mockRejectedValue(new Error('离线'))
  await wrapper!.findAll('button').find(button => button.text() === '刷新')!.trigger('click'); await flushPromises()
  expect(wrapper!.text()).toContain('真实项目'); expect(wrapper!.text()).toContain('保留上次结果')
  expect(wrapper!.find('.project-empty').exists()).toBe(false)
  wrapper!.unmount(); await open('/projects?q=空')
  expect(wrapper!.text()).toContain('请求失败'); expect(wrapper!.text()).not.toContain('未找到匹配项目')
})
it('同一列表组件恢复 URL 筛选和分页，不显示上一查询的行', async () => {
  const router = await open('/projects?q=旧&offset=20&limit=50')
  expect(listProjects).toHaveBeenLastCalledWith({ includeSummary: true, q: '旧', offset: 20, limit: 50 })
  await router.push('/projects?q=新&limit=100'); await flushPromises()
  expect(wrapper!.get('input').element.value).toBe('新')
  expect(listProjects).toHaveBeenLastCalledWith({ includeSummary: true, q: '新', offset: 0, limit: 100 })
  router.back(); await new Promise(resolve => setTimeout(resolve, 0)); await flushPromises()
  expect(wrapper!.get('input').element.value).toBe('旧')
})
it('概览展开为独立全宽分页，刷新失败保留数据，失权清空数据', async () => {
  await open('/projects/project-1')
  await wrapper!.findAll('button').find(button => button.text().includes('查看全部'))!.trigger('click'); await flushPromises()
  expect(wrapper!.find('.project-activity-filters').exists()).toBe(true)
  expect(wrapper!.find('.project-overview-panels').exists()).toBe(false)
  expect(vi.mocked(getProjectOverview).mock.calls.at(-1)![1]).toMatchObject({ limit: 20, offset: 0 })
  vi.mocked(getProjectOverview).mockRejectedValue(new Error('离线'))
  await wrapper!.get('button[aria-label="刷新"]').trigger('click'); await flushPromises()
  expect(wrapper!.text()).toContain('训练任务'); expect(wrapper!.text()).toContain('保留上次结果')
  vi.mocked(getProject).mockRejectedValue(new ApiError(403, { message: '无权访问' }))
  await wrapper!.get('button[aria-label="刷新"]').trigger('click'); await flushPromises()
  expect(wrapper!.text()).not.toContain('训练任务'); expect(wrapper!.text()).not.toContain('真实项目')
})
it('受限账号保留项目与数据集入口，隐藏 SDK 和无权动作', async () => {
  useSessionStore().currentUser = { principal_id: 'reader', scopes: ['datasets:read'], project_ids: ['project-1'], allowed_pages: ['projects', 'datasets'] } as never
  vi.mocked(getProject).mockResolvedValue({ ...project, resource_counts: { datasets: 2 } })
  vi.mocked(getProjectOverview).mockResolvedValue({ ...overview, recent: [], total: 0, access: { datasets: true } })
  await open('/projects/project-1')
  expect(wrapper!.text()).toContain('真实项目'); expect(wrapper!.text()).toContain('数据集')
  expect(wrapper!.text()).not.toContain('SDK'); expect(wrapper!.text()).not.toContain('创建部署'); expect(wrapper!.text()).not.toContain('编辑项目')
})

it.each([403, 404])('概览 %s 隐藏旧信息并能返回列表', async status => {
  vi.mocked(getProject).mockRejectedValue(new ApiError(status, { message: '不应回显的内部详情' }))
  const router = await open('/projects/project-1')
  expect(wrapper!.text()).toContain('无法打开此项目')
  expect(wrapper!.text()).not.toContain('内部详情')
  await wrapper!.findAll('button').find(item => item.text() === '返回项目列表')!.trigger('click'); await flushPromises()
  expect(router.currentRoute.value.path).toBe('/projects')
})

it('名称按钮仅选择，查看独立导航；隐藏的当前项目可定位', async () => {
  const store = useProjectStore()
  const hidden = { project_id: 'project-hidden', display_name: '范围外项目' }
  store.projects = [hidden]; store.selectedProjectId = hidden.project_id
  const router = await open('/projects?q=真实')
  expect(wrapper!.text()).toContain('范围外项目')
  await wrapper!.findAll('button').find(item => item.text() === '定位')!.trigger('click'); await flushPromises()
  expect(router.currentRoute.value.query.q).toBe(hidden.project_id)
  await wrapper!.get('.project-name-button').trigger('click'); await flushPromises()
  expect(router.currentRoute.value.path).toBe('/projects')
  expect(store.selectedProjectId).toBe(project.project_id)
  expect(wrapper!.get('.project-name-button').attributes('aria-pressed')).toBe('true')
  await wrapper!.get('.project-link').trigger('click'); await flushPromises()
  expect(router.currentRoute.value.path).toBe('/projects/project-1')
})

it('创建成功留在列表并定位、提供查看；同名行显示可区分的 ID', async () => {
  vi.mocked(listProjects).mockResolvedValue({ ...page, items: [project, { ...project, project_id: 'project-2' }] })
  const router = await open('/projects')
  expect(wrapper!.findAll('.project-disambiguation').map(item => item.text())).toEqual(['project-1', 'project-2'])
  await wrapper!.findAll('button').find(item => item.text() === '新建项目')!.trigger('click'); await flushPromises()
  wrapper!.findComponent(ProjectDialogs).vm.$emit('created', project); await flushPromises()
  expect(router.currentRoute.value.path).toBe('/projects')
  expect(router.currentRoute.value.query.q).toBe(project.project_id)
  expect(wrapper!.find('.project-notice').text()).toContain('项目已创建')
})
