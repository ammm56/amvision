import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import { defineComponent, h } from 'vue'
import { i18n } from '@/platform/i18n'
import { ApiError } from '@/shared/api/error'
import ProjectMetadataDrawer from './ProjectMetadataDrawer.vue'
import ProjectSdkDialog from './ProjectSdkDialog.vue'
import ProjectDeleteDialog from './ProjectDeleteDialog.vue'
import ProjectDialogs from './ProjectDialogs.vue'
import { useFeedbackStore } from '@/app/stores/feedback.store'
import { useSessionStore } from '@/app/stores/session.store'
import { readPendingDeletions, savePendingDeletion, clearPendingDeletion, readPendingCreations } from '../project-recovery'
import { createProject, updateProject, listSdkResources, previewSdkConfigPackage, downloadSdkConfigPackage, deleteProject, previewProjectDeletion, getProjectDeletionResult } from '../services/project.service'

vi.mock('../services/project.service', () => ({ createProject: vi.fn(), updateProject: vi.fn(), getProject: vi.fn(), listSdkResources: vi.fn(), previewSdkConfigPackage: vi.fn(), downloadSdkConfigPackage: vi.fn(), deleteProject: vi.fn(), previewProjectDeletion: vi.fn(), getProjectDeletionResult: vi.fn() }))
beforeEach(() => { setActivePinia(createPinia()) })
const wrappers: Array<{ unmount(): void }> = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = ''; localStorage.clear(); sessionStorage.clear(); vi.resetAllMocks() })
const project = { project_id: 'project-ui', display_name: '测试项目', description: '原说明', revision: 'a'.repeat(64) }
const preview = { project_id: project.project_id, configuration_revision: 'b'.repeat(64), files: [{ path: 'config.json', count: 1 }], notes: [], warnings: [], workflow_runtime_count: 1, model_deployment_count: 0, trigger_source_count: 1 }

describe('项目操作', () => {
  it('删除响应和查询连续失败保留待确认，不误发未受理也不重复 DELETE', async () => {
    vi.mocked(previewProjectDeletion).mockResolvedValueOnce({ project_id: project.project_id, project_source: 'local_disk', protected: false, can_delete: true, blockers: [], resource_counts: {} }).mockRejectedValue(new Error('断线'))
    vi.mocked(deleteProject).mockRejectedValue(new Error('删除响应丢失'))
    vi.mocked(getProjectDeletionResult).mockRejectedValue(new Error('查询断线'))
    const wrapper = mount(ProjectDeleteDialog, { props: { project }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper)
    await flushPromises(); await wrapper.get('input').setValue(project.project_id)
    const button = (name: string) => wrapper.findAll('button').find(item => item.text() === name)!
    await button('删除项目').trigger('click'); await flushPromises()
    expect(wrapper.emitted('unaccepted')).toBeUndefined()
    expect(wrapper.text()).toContain('删除结果尚未确认')
    expect(wrapper.text()).toContain(project.display_name)
    await button('检查清理状态').trigger('click'); await flushPromises()
    expect(deleteProject).toHaveBeenCalledTimes(1)
    expect(getProjectDeletionResult).toHaveBeenCalledTimes(2)
  })

  it('分别保留多个项目的清理回执，清除 B 不会移除 A', () => {
    savePendingDeletion('user', { project, operation_id: 'op-a' })
    savePendingDeletion('user', { project: { project_id: 'project-b', display_name: 'B' }, operation_id: 'op-b' })
    clearPendingDeletion('user', 'project-b')
    expect(readPendingDeletions('user').map(item => item.operation_id)).toEqual(['op-a'])
    expect(readPendingDeletions('other-user')).toEqual([])
  })

  it('刷新脏表单时发出浏览器离页保护，销毁后释放监听', async () => {
    const wrapper = mount(ProjectMetadataDrawer, { props: { mode: 'edit', project }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper)
    await flushPromises()
    const field = document.querySelector('input')!; field.value = '未保存名称'; field.dispatchEvent(new Event('input', { bubbles: true })); await flushPromises()
    const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    wrapper.unmount(); wrappers.pop()
    const after = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(after)
    expect(after.defaultPrevented).toBe(false)
  })
  it('信息切换编辑将焦点放入表单，关闭后恢复原入口', async () => {
    const opener = document.createElement('button'); document.body.append(opener); opener.focus()
    const wrapper = mount(ProjectMetadataDrawer, { props: { mode: 'info', project, editable: true }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper)
    await flushPromises()
    await wrapper.setProps({ mode: 'edit' }); await flushPromises()
    expect(document.activeElement).toBe(document.querySelector('#project-metadata input'))
    wrapper.unmount(); wrappers.pop()
    expect(document.activeElement).toBe(opener)
  })

  it('编辑冲突保留输入，不借新建覆盖元数据；脏表单关闭需要确认', async () => {
    vi.mocked(updateProject).mockRejectedValue(new ApiError(409, { message: '项目已被修改' }))
    const wrapper = mount(ProjectMetadataDrawer, { props: { mode: 'edit', project }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper)
    await flushPromises()
    const input = document.querySelector('input')!; input.value = '保留这个草稿'; input.dispatchEvent(new Event('input', { bubbles: true }))
    document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await flushPromises()
    expect(updateProject).toHaveBeenCalledWith('project-ui', { display_name: '保留这个草稿', description: '原说明', expected_revision: project.revision })
    expect(document.body.textContent).toContain('项目已被修改')
    expect(input.value).toBe('保留这个草稿'); expect(createProject).not.toHaveBeenCalled()
    ;(document.querySelector('.side-drawer__close') as HTMLElement).click(); await flushPromises()
    expect(document.querySelector('.confirm-dialog')?.textContent).toContain('放弃修改')
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('创建结果未知后沿用同一请求身份，防止手动重试产生多个项目', async () => {
    vi.mocked(createProject).mockRejectedValue(new Error('连接中断'))
    const wrapper = mount(ProjectMetadataDrawer, { props: { mode: 'create' }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper); await flushPromises()
    const input = document.querySelector('input')!; input.value = '新项目'; input.dispatchEvent(new Event('input', { bubbles: true }))
    const submit = () => document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    submit(); await flushPromises(); submit(); await flushPromises()
    expect(createProject).toHaveBeenCalledTimes(2)
    expect(vi.mocked(createProject).mock.calls[0][0].request_id).toBe(vi.mocked(createProject).mock.calls[1][0].request_id)
  })

  it('范围搜索保留隐藏选择，Trigger 依赖锁定 Runtime，空范围可以预览但不能下载', async () => {
    vi.mocked(listSdkResources).mockResolvedValue([{ id: 'runtime-1', name: '运行实例', kind: 'runtime', runtime_id: null }, { id: 'trigger-1', name: '触发入口', kind: 'trigger', runtime_id: 'runtime-1' }])
    vi.mocked(previewSdkConfigPackage).mockResolvedValue(preview as never)
    const wrapper = mount(ProjectSdkDialog, { props: { project }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper); await flushPromises()
    const button = (name: string) => wrapper.findAll('button').find(item => item.text() === name)!
    await button('调整范围').trigger('click'); await flushPromises()
    expect(wrapper.findAll('.sdk-resource input')[0].attributes('disabled')).toBeDefined()
    await wrapper.get('.sdk-search').setValue('触发'); expect(wrapper.findAll('.sdk-resource')).toHaveLength(1)
    await button('应用选择').trigger('click'); await flushPromises()
    expect(vi.mocked(previewSdkConfigPackage).mock.calls.at(-1)?.[1]).toMatchObject({ runtime_ids: undefined, trigger_source_ids: undefined })
    await button('调整范围').trigger('click'); await wrapper.get('.sdk-search').setValue(''); await button('取消当前结果').trigger('click')
    vi.mocked(previewSdkConfigPackage).mockResolvedValue({ ...preview, files: [] } as never)
    await button('应用选择').trigger('click'); await flushPromises()
    expect(vi.mocked(previewSdkConfigPackage).mock.calls.at(-1)?.[1]).toMatchObject({ runtime_ids: [], trigger_source_ids: [] })
    expect(button('生成并下载').attributes('disabled')).toBeDefined(); expect(downloadSdkConfigPackage).not.toHaveBeenCalled()
  })

  it('配置选项改变后预览失败，不能使用上次预览下载', async () => {
    vi.mocked(listSdkResources).mockResolvedValue([{ id: 'runtime-1', name: '运行实例', kind: 'runtime', runtime_id: null }])
    vi.mocked(previewSdkConfigPackage).mockResolvedValue(preview as never)
    const wrapper = mount(ProjectSdkDialog, { props: { project }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper); await flushPromises()
    vi.mocked(previewSdkConfigPackage).mockRejectedValue(new Error('连接中断'))
    await wrapper.findAll('.sdk-options input')[0].setValue(false); await flushPromises()
    const download = wrapper.findAll('button').find(item => item.text() === '生成并下载')!
    expect(download.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('连接中断')
    expect(downloadSdkConfigPackage).not.toHaveBeenCalled()
  })
})

it('草稿离开路由须确认，取消离开保留输入', async () => {
  const host = defineComponent({ setup: () => () => h(ProjectMetadataDrawer, { mode: 'edit', project }) })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/edit', component: host }, { path: '/other', component: { template: '<p>其他页面</p>' } }] })
  await router.push('/edit'); await router.isReady()
  const wrapper = mount(RouterView, { attachTo: document.body, global: { plugins: [i18n, router] } }); wrappers.push(wrapper); await flushPromises()
  const input = document.querySelector<HTMLInputElement>('#project-metadata input')!; input.value = '离页保护'; input.dispatchEvent(new Event('input', { bubbles: true }))
  const pending = router.push('/other'); await flushPromises()
  expect(router.currentRoute.value.path).toBe('/edit')
  ;(document.querySelector('[data-confirm-cancel]') as HTMLElement).click(); await pending; await flushPromises()
  expect(router.currentRoute.value.path).toBe('/edit'); expect(input.value).toBe('离页保护')
  const leaving = router.push('/other'); await flushPromises()
  ;(Array.from(document.querySelectorAll<HTMLButtonElement>('.confirm-dialog button')).find(button => button.textContent?.trim() === '放弃修改')!).click()
  await leaving; await flushPromises(); expect(router.currentRoute.value.path).toBe('/other')
})

it('创建请求未知在抽屉重新挂载后沿用身份，不重复产生新身份', async () => {
  vi.mocked(createProject).mockRejectedValue(new Error('连接中断'))
  const first = mount(ProjectMetadataDrawer, { props: { mode: 'create', principalId: 'account-a' }, attachTo: document.body, global: { plugins: [i18n] } }); await flushPromises()
  const input = document.querySelector<HTMLInputElement>('#project-metadata input')!; input.value = '持久创建'; input.dispatchEvent(new Event('input', { bubbles: true }))
  document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await flushPromises()
  const requestId = vi.mocked(createProject).mock.calls.at(-1)![0].request_id
  first.unmount()
  const second = mount(ProjectMetadataDrawer, { props: { mode: 'create', principalId: 'account-a', creation: readPendingCreations('account-a')[0] }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(second); await flushPromises()
  expect(document.querySelector<HTMLInputElement>('#project-metadata input')!.value).toBe('持久创建')
  document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await flushPromises()
  expect(vi.mocked(createProject).mock.calls.at(-1)![0].request_id).toBe(requestId)
})

it('SDK 151 项仅渲染当前 50 项，分页取消不丢失其他页选择', async () => {
  vi.mocked(listSdkResources).mockResolvedValue(Array.from({ length: 151 }, (_, i) => ({ id: `runtime-${i}`, name: `运行 ${i}`, kind: 'runtime' as const, runtime_id: null })))
  vi.mocked(previewSdkConfigPackage).mockResolvedValue(preview as never)
  const wrapper = mount(ProjectSdkDialog, { props: { project }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper); await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '调整范围')!.trigger('click')
  expect(wrapper.findAll('.sdk-resource')).toHaveLength(50)
  await wrapper.findAll('button').find(button => button.text() === '取消当前结果')!.trigger('click')
  await wrapper.findAll('button').find(button => button.text() === '应用选择')!.trigger('click'); await flushPromises()
  expect(vi.mocked(previewSdkConfigPackage).mock.calls.at(-1)![1].runtime_ids).toHaveLength(101)
  expect(vi.mocked(previewSdkConfigPackage).mock.calls.at(-1)![1].runtime_ids).toContain('runtime-150')
})

it('SDK 预览等待可 Esc 关闭，并中止读取；迟到响应不更新界面', async () => {
  vi.mocked(listSdkResources).mockResolvedValue([])
  let resolvePreview!: (value: never) => void
  vi.mocked(previewSdkConfigPackage).mockImplementation(() => new Promise(resolve => { resolvePreview = resolve }))
  const wrapper = mount(ProjectSdkDialog, { props: { project }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper); await flushPromises()
  expect(wrapper.get('.confirm-dialog__close').attributes('disabled')).toBeUndefined()
  await wrapper.get('.confirm-dialog').trigger('keydown', { key: 'Escape' }); await flushPromises()
  expect(wrapper.emitted('close')).toHaveLength(1)
  expect(vi.mocked(previewSdkConfigPackage).mock.calls[0][2]!.aborted).toBe(true)
  resolvePreview(preview as never); await flushPromises()
  expect(wrapper.findAll('.sdk-file')).toHaveLength(0)
})

it('SDK 生成时关闭不触发迟到下载', async () => {
  vi.mocked(listSdkResources).mockResolvedValue([{ id: 'runtime-1', name: '实例', kind: 'runtime', runtime_id: null }])
  vi.mocked(previewSdkConfigPackage).mockResolvedValue(preview as never)
  let resolveDownload!: (value: { blob: Blob }) => void
  vi.mocked(downloadSdkConfigPackage).mockImplementation(() => new Promise(resolve => { resolveDownload = resolve }))
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  const wrapper = mount(ProjectSdkDialog, { props: { project }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper); await flushPromises()
  await wrapper.findAll('button').find(item => item.text() === '生成并下载')!.trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('不取消后台生成')
  await wrapper.get('.confirm-dialog__close').trigger('click'); await flushPromises()
  resolveDownload({ blob: new Blob(['zip']) }); await flushPromises()
  expect(click).not.toHaveBeenCalled(); expect(useFeedbackStore().notices).toHaveLength(0); click.mockRestore()
})

it.each(['edit', 'info'] as const)('从 %s 保存完成才显示项目已更新，等待期间不提前提示', async action => {
  vi.spyOn(useSessionStore(), 'loadBootstrap').mockRejectedValue(new Error('后台刷新暂不可用'))
  let complete!: (value: typeof project) => void
  vi.mocked(updateProject).mockImplementation(() => new Promise(resolve => { complete = resolve }))
  const wrapper = mount(ProjectDialogs, { props: { action, project }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper)
  if (action === 'info') wrapper.getComponent(ProjectMetadataDrawer).vm.$emit('edit')
  await flushPromises()
  const input = document.querySelector<HTMLInputElement>('#project-metadata input')!
  input.value = '更新后的项目'; input.dispatchEvent(new Event('input', { bubbles: true }))
  document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await flushPromises()
  expect(useFeedbackStore().notices).toHaveLength(0)
  expect(wrapper.emitted('close')).toBeUndefined()
  complete({ ...project, display_name: input.value }); await flushPromises()
  expect(wrapper.emitted('close')).toHaveLength(1)
  expect(wrapper.emitted('changed')).toHaveLength(1)
  expect(useFeedbackStore().notices).toMatchObject([{ variant: 'success', title: '项目已更新' }])
})

it('编辑失败和取消不会提示更新成功，创建成功仍使用创建反馈', async () => {
  vi.mocked(updateProject).mockRejectedValue(new ApiError(409, { message: '并发修改' }))
  vi.spyOn(useSessionStore(), 'loadBootstrap').mockRejectedValue(new Error('后台刷新暂不可用'))
  const wrapper = mount(ProjectDialogs, { props: { action: 'edit', project }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper)
  await flushPromises()
  const input = document.querySelector<HTMLInputElement>('#project-metadata input')!
  input.value = '未保存'; input.dispatchEvent(new Event('input', { bubbles: true }))
  document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await flushPromises()
  expect(useFeedbackStore().notices).toHaveLength(0)
  wrapper.getComponent(ProjectMetadataDrawer).vm.$emit('close'); await flushPromises()
  expect(useFeedbackStore().notices).toHaveLength(0)
  await wrapper.setProps({ action: 'create' })
  wrapper.getComponent(ProjectMetadataDrawer).vm.$emit('saved', project); await flushPromises()
  expect(wrapper.emitted('created')).toHaveLength(1)
  expect(useFeedbackStore().notices).toHaveLength(0)
})

it.each(['success', 'request-failure', 'browser-failure'])('SDK 下载反馈正确区分 %s，URL 最终释放', async outcome => {
  vi.mocked(listSdkResources).mockResolvedValue([{ id: 'runtime-1', name: '实例', kind: 'runtime', runtime_id: null }])
  vi.mocked(previewSdkConfigPackage).mockResolvedValue(preview as never)
  if (outcome === 'request-failure') vi.mocked(downloadSdkConfigPackage).mockRejectedValue(new Error('生成失败'))
  else vi.mocked(downloadSdkConfigPackage).mockResolvedValue({ blob: new Blob(['zip']), fileName: 'project.zip' })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {
    expect(useFeedbackStore().notices).toHaveLength(0)
    if (outcome === 'browser-failure') throw new Error('浏览器下载失败')
  })
  const createUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:project-test')
  const revokeUrl = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  const wrapper = mount(ProjectSdkDialog, { props: { project }, attachTo: document.body, global: { plugins: [i18n] } }); wrappers.push(wrapper); await flushPromises()
  vi.useFakeTimers()
  try {
    await wrapper.findAll('button').find(item => item.text() === '生成并下载')!.trigger('click'); await flushPromises()
    if (outcome === 'success') expect(useFeedbackStore().notices).toMatchObject([{ variant: 'success', title: '已开始下载' }])
    else expect(useFeedbackStore().notices).toHaveLength(0)
    if (outcome === 'request-failure') expect(click).not.toHaveBeenCalled()
    else { expect(click).toHaveBeenCalledTimes(1); await vi.advanceTimersByTimeAsync(1000); expect(revokeUrl).toHaveBeenCalledWith('blob:project-test') }
  } finally { vi.useRealTimers(); click.mockRestore(); createUrl.mockRestore(); revokeUrl.mockRestore() }
})
