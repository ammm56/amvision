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
import { listProjects, getProject, getProjectOverview, getProjectSummary } from '../services/project.service'

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
  expect(wrapper!.text()).toContain('真实项目'); expect(wrapper!.find('[role="alert"]').exists()).toBe(true); expect(wrapper!.text()).not.toContain('保留上次结果')
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
  expect(wrapper!.text()).toContain('训练任务'); expect(wrapper!.find('[role="alert"]').exists()).toBe(true); expect(wrapper!.text()).not.toContain('保留上次结果')
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

it('无执行任务时不展示任务分组或占位，保留服务与快捷入口', async () => {
  vi.mocked(getProjectOverview).mockResolvedValue({ ...overview, active: [{ resource_id: 'runtime-1', name: '产线检测', kind: 'runtime', state: 'running', occurred_at: '2026-11-04T01:00:00Z' }] })
  await open('/projects/project-1')
  expect(wrapper!.text()).not.toContain('正在执行的任务')
  expect(wrapper!.text()).not.toContain('暂无执行中的任务')
  expect(wrapper!.text()).toContain('产线检测')
  expect(wrapper!.find('.project-panel-body .project-actions').exists()).toBe(false)
  expect(wrapper!.find('.project-continue-panel h2').exists()).toBe(false)
  expect(wrapper!.findAll('.project-shortcuts button')).toHaveLength(4)
})

it('执行任务显示进度，刷新后任务结束则移除整个分组', async () => {
  vi.mocked(getProjectOverview).mockResolvedValue({ ...overview, active: [{ resource_id: 'task-active', name: '训练进行中', kind: 'yolo11-training', state: 'running', occurred_at: '2026-11-04T01:00:00Z', progress: { percent: 42, stage: '训练' } }] })
  await open('/projects/project-1')
  expect(wrapper!.text()).toContain('正在执行的任务')
  expect(wrapper!.text()).toContain('训练进行中')
  expect(wrapper!.get('progress').attributes('value')).toBe('42')
  vi.mocked(getProjectOverview).mockResolvedValue(overview)
  await wrapper!.get('button[aria-label="刷新"]').trigger('click'); await flushPromises()
  expect(wrapper!.text()).not.toContain('正在执行的任务')
  expect(wrapper!.text()).not.toContain('训练进行中')
  expect(wrapper!.find('progress').exists()).toBe(false)
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
  expect(getProject).not.toHaveBeenCalled()
  await wrapper!.get('.project-row-actions button[aria-label="查看"]').trigger('click'); await flushPromises()
  expect(router.currentRoute.value.path).toBe('/projects/project-1')
  expect(getProject).toHaveBeenCalledTimes(1)
})

it('行切换直接复用列表数据，连续切换和重复点击不请求详情或摘要', async () => {
  const first = { ...project, summary: { project_id: project.project_id, generated_at: '2026-11-05T04:00:00Z' } }
  const second = { ...project, project_id: 'project-2', display_name: '另一个项目', summary: null }
  vi.mocked(listProjects).mockResolvedValue({ ...page, items: [first, second] })
  // 即使详情服务没有响应，本地选中状态也必须立即切换。
  vi.mocked(getProject).mockReturnValue(new Promise(() => {}))
  const store = useProjectStore()
  store.projects = [{ ...project, display_name: '旧名称' }]
  await open('/projects')
  const rows = wrapper!.findAll('.project-table tbody tr')
  await rows[0].trigger('click')
  expect(store.selectedProject).toEqual(first)
  expect(store.selectedSummary).toEqual(first.summary)
  expect(rows[0].classes()).toContain('is-current')
  await rows[1].trigger('click')
  expect(store.selectedProject).toEqual(second)
  expect(store.selectedSummary).toBeNull()
  expect(rows[0].classes()).not.toContain('is-current')
  expect(rows[1].classes()).toContain('is-current')
  await rows[0].trigger('click')
  await rows[0].trigger('click')
  expect(store.selectedProjectId).toBe(first.project_id)
  expect(store.selectedSummary).toEqual(first.summary)
  expect(store.projects).toHaveLength(2)
  expect(getProject).not.toHaveBeenCalled()
  expect(getProjectSummary).not.toHaveBeenCalled()
  expect(listProjects).toHaveBeenCalledTimes(1)
})

it('查看直接进入概览，详情失权仍由概览显示无法访问', async () => {
  const router = await open('/projects')
  vi.mocked(getProject).mockRejectedValue(new ApiError(403, { message: '无权访问' }))
  await wrapper!.get('.project-row-actions button[aria-label="查看"]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/projects/project-1')
  expect(wrapper!.text()).toContain('无法打开此项目')
  expect(wrapper!.text()).not.toContain('真实项目')
  expect(getProject).toHaveBeenCalledTimes(1)
})

it.each(['/projects', '/projects?q=旧筛选&offset=20'])('创建成功恢复完整列表首屏而不按 ID 筛选：%s', async path => {
  vi.mocked(listProjects).mockResolvedValue({ ...page, items: [project, { ...project, project_id: 'project-2' }] })
  const router = await open(path)
  expect(wrapper!.findAll('.project-disambiguation').map(item => item.text())).toEqual(['project-1', 'project-2'])
  await wrapper!.findAll('button').find(item => item.text() === '创建新项目')!.trigger('click'); await flushPromises()
  wrapper!.findComponent(ProjectDialogs).vm.$emit('created', project); await flushPromises()
  expect(router.currentRoute.value.path).toBe('/projects')
  expect(router.currentRoute.value.query.q).toBeUndefined()
  expect(router.currentRoute.value.query.offset).toBeUndefined()
  expect(wrapper!.get<HTMLInputElement>('input[aria-label="搜索项目"]').element.value).toBe('')
  expect(listProjects).toHaveBeenLastCalledWith({ includeSummary: true, offset: 0, limit: 20, q: '' })
  expect(wrapper!.findAll('.project-table tbody tr')).toHaveLength(2)
  expect(useProjectStore().selectedProjectId).toBe(project.project_id)
  expect(wrapper!.find('.project-notice').exists()).toBe(false)
})

it('更多菜单打开对应抽屉，受保护项目不提供删除入口', async () => {
  const editable = { ...project, project_id: 'project-editable', revision: 'revision-1' }
  const protectedProject = { ...project, project_id: 'project-protected', project_source: 'configured' as const, revision: 'revision-2' }
  vi.mocked(listProjects).mockResolvedValue({ ...page, items: [editable, protectedProject] })
  await open('/projects')
  const rows = wrapper!.findAll('.project-table tbody tr')
  expect(rows[0].findAll('.project-row-actions button').map(button => button.attributes('aria-label'))).toEqual(['查看', '更多操作'])
  await rows[0].get('button[aria-haspopup="menu"]').trigger('keydown', { key: 'Enter' }); await flushPromises()
  expect(Array.from(document.querySelectorAll('[role="menuitem"]')).map(item => item.textContent)).toEqual(['详情', '编辑', '删除'])
  expect(document.querySelector('[role="menu"]')!.textContent).not.toContain('SDK')
  ;(document.querySelectorAll('[role="menuitem"]')[0] as HTMLElement).click(); await flushPromises()
  expect(wrapper!.getComponent(ProjectDialogs).props()).toMatchObject({ action: 'info', project: editable })
  wrapper!.getComponent(ProjectDialogs).vm.$emit('close'); await flushPromises()
  await rows[0].get('button[aria-haspopup="menu"]').trigger('keydown', { key: 'Enter' }); await flushPromises()
  ;(document.querySelectorAll('[role="menuitem"]')[1] as HTMLElement).click(); await flushPromises()
  expect(wrapper!.getComponent(ProjectDialogs).props()).toMatchObject({ action: 'edit', project: editable })
  expect(useProjectStore().selectedProjectId).not.toBe(editable.project_id)
  wrapper!.getComponent(ProjectDialogs).vm.$emit('close'); await flushPromises()
  await rows[1].get('button[aria-haspopup="menu"]').trigger('keydown', { key: 'Enter' }); await flushPromises()
  expect(Array.from(document.querySelectorAll('[role="menuitem"]')).map(item => item.textContent)).toEqual(['详情', '编辑'])
})

it('列表只读账号仅保留查看和信息操作，选中行不增加文字', async () => {
  useSessionStore().currentUser = { principal_id: 'reader', scopes: ['datasets:read'], project_ids: ['project-1'], allowed_pages: ['projects'] } as never
  const store = useProjectStore(); store.projects = [project]; store.selectedProjectId = project.project_id
  await open('/projects')
  expect(wrapper!.findAll('.project-row-actions button').map(button => button.attributes('aria-label'))).toEqual(['查看', '更多操作'])
  await wrapper!.get('button[aria-haspopup="menu"]').trigger('keydown', { key: 'Enter' }); await flushPromises()
  expect(Array.from(document.querySelectorAll('[role="menuitem"]')).map(item => item.textContent)).toEqual(['详情'])
  expect(wrapper!.get('.project-table tbody tr').text()).not.toContain('当前项目')
  expect(wrapper!.get('input[aria-label="搜索项目"]').attributes('placeholder')).toBeUndefined()
})

it.each([
  { totalCount: 0, offset: 0, hasMore: false, visible: false },
  { totalCount: 20, offset: 0, hasMore: false, visible: false },
  { totalCount: 21, offset: 0, hasMore: true, visible: true },
  { totalCount: null, offset: 0, hasMore: true, visible: true },
  { totalCount: null, offset: 20, hasMore: false, visible: true },
])('分页仅在存在跨页数据时显示：$totalCount / $offset / $hasMore', async ({ totalCount, offset, hasMore, visible }) => {
  vi.mocked(listProjects).mockResolvedValue({ items: totalCount === 0 ? [] : [project], pagination: { ...page.pagination, totalCount, offset, hasMore } })
  await open(offset ? `/projects?offset=${offset}` : '/projects')
  expect(wrapper!.find('.project-pagination').exists()).toBe(visible)
})
