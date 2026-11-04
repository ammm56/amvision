import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { i18n } from '@/platform/i18n'
import { ApiError } from '@/shared/api/error'
import ProjectMetadataDrawer from './ProjectMetadataDrawer.vue'
import { createProject, getProject, updateProject } from '../services/project.service'
import { readPendingCreations, readPendingEdit } from '../project-recovery'

vi.mock('../services/project.service', () => ({ createProject: vi.fn(), updateProject: vi.fn(), getProject: vi.fn() }))
let wrapper: ReturnType<typeof mount> | undefined
const project = { project_id: 'project-recovery', display_name: '原名称', description: '原说明', revision: 'a'.repeat(64) }
afterEach(() => { wrapper?.unmount(); wrapper = undefined; document.body.innerHTML = ''; sessionStorage.clear(); vi.resetAllMocks() })
async function open(mode: 'create' | 'edit' = 'edit') {
  wrapper = mount(ProjectMetadataDrawer, { props: { mode, project: mode === 'edit' ? project : undefined, principalId: 'user' }, attachTo: document.body, global: { plugins: [i18n], stubs: { teleport: true } } })
  await flushPromises()
}
async function submit() { await wrapper!.get('input').setValue('本地修改'); await wrapper!.get('form').trigger('submit'); await flushPromises() }
const button = (label: string) => wrapper!.findAll('button').find(item => item.text() === label)!

it('创建未找到可另建，原请求仍可核对，新请求成功不清掉旧记录', async () => {
  vi.mocked(createProject).mockRejectedValueOnce(new Error('响应丢失')).mockResolvedValue({ ...project, project_id: 'project-new' })
  vi.mocked(getProject).mockRejectedValue(new ApiError(404, { message: '未找到' }))
  await open('create'); await submit()
  const first = readPendingCreations('user')[0]!
  await button('核对结果').trigger('click'); await flushPromises()
  expect(wrapper!.get('input').attributes('disabled')).toBeDefined()
  await button('保留记录，另建项目').trigger('click'); await flushPromises()
  expect(wrapper!.get('input').attributes('disabled')).toBeUndefined()
  expect(wrapper!.get('input').element.value).toBe('')
  await submit()
  expect(vi.mocked(createProject).mock.calls[1][0].request_id).not.toBe(first.request_id)
  expect(readPendingCreations('user')).toEqual([first])
  expect(readPendingCreations('other')).toEqual([])
})

it('保存响应丢失但读回内容相同，按已保存处理，不重复 PATCH', async () => {
  vi.mocked(updateProject).mockRejectedValue(new Error('响应丢失'))
  vi.mocked(getProject).mockResolvedValue({ ...project, display_name: '本地修改', revision: 'b'.repeat(64) })
  await open(); await submit()
  expect(wrapper!.emitted('saved')?.[0][0]).toMatchObject({ display_name: '本地修改' })
  expect(updateProject).toHaveBeenCalledTimes(1)
  expect(readPendingEdit('user', project.project_id)).toBeNull()
})

it('保存与核对均断线，禁止重复保存，重开后仍可核对', async () => {
  vi.mocked(updateProject).mockRejectedValue(new Error('响应丢失'))
  vi.mocked(getProject).mockRejectedValueOnce(new Error('核对断线')).mockResolvedValue(project)
  await open(); await submit()
  expect(button('保存')).toBeUndefined()
  expect(readPendingEdit('user', project.project_id)).not.toBeNull()
  wrapper!.unmount(); await open()
  expect(wrapper!.get('input').element.value).toBe('本地修改')
  await button('核对结果').trigger('click'); await flushPromises()
  expect(wrapper!.text()).toContain('服务器内容尚未变化')
  expect(button('保存').attributes('disabled')).toBeUndefined()
  expect(updateProject).toHaveBeenCalledTimes(1)
})

it('读回其他修改时明确选择保留本地后才能使用新 revision 保存', async () => {
  vi.mocked(updateProject).mockRejectedValueOnce(new Error('断线')).mockResolvedValue({ ...project, display_name: '本地修改', revision: 'c'.repeat(64) })
  vi.mocked(getProject).mockResolvedValue({ ...project, display_name: '其他修改', revision: 'b'.repeat(64) })
  await open(); await submit()
  expect(button('保存').attributes('disabled')).toBeDefined()
  expect(wrapper!.text()).toContain('其他修改')
  await button('保留我的修改').trigger('click'); await wrapper!.get('form').trigger('submit'); await flushPromises()
  expect(vi.mocked(updateProject).mock.calls.at(-1)![1]).toMatchObject({ display_name: '本地修改', expected_revision: 'b'.repeat(64) })
})

it('清空说明后保存和核对均断线，重开仍保留空说明，不恢复旧内容', async () => {
  vi.mocked(updateProject).mockRejectedValue(new Error('响应丢失'))
  vi.mocked(getProject).mockRejectedValueOnce(new Error('核对断线')).mockResolvedValue(project)
  await open(); await wrapper!.get('textarea').setValue(''); await wrapper!.get('form').trigger('submit'); await flushPromises()
  expect(readPendingEdit('user', project.project_id)?.description).toBeNull()
  wrapper!.unmount(); await open()
  expect(wrapper!.get('textarea').element.value).toBe('')
  await button('核对结果').trigger('click'); await flushPromises()
  expect(wrapper!.get('textarea').element.value).toBe('')
  expect(button('保存').attributes('disabled')).toBeUndefined()
})

it('采用服务器内容需要确认；取消保留草稿，确认更新基线不再次提交', async () => {
  vi.mocked(updateProject).mockRejectedValue(new ApiError(409, { message: '冲突' }))
  vi.mocked(getProject).mockResolvedValue({ ...project, display_name: '服务器名称', revision: 'b'.repeat(64) })
  await open(); await submit()
  await button('读取最新信息').trigger('click'); await flushPromises()
  await button('采用服务器内容').trigger('click'); await flushPromises()
  await wrapper!.get('[data-confirm-cancel]').trigger('click')
  expect(wrapper!.get('input').element.value).toBe('本地修改')
  await button('采用服务器内容').trigger('click'); await flushPromises()
  await wrapper!.findAll('.confirm-dialog button').find(item => item.text() === '采用服务器内容')!.trigger('click'); await flushPromises()
  expect(wrapper!.get('input').element.value).toBe('服务器名称')
  expect(button('保存').attributes('disabled')).toBeDefined()
  expect(updateProject).toHaveBeenCalledTimes(1)
})
