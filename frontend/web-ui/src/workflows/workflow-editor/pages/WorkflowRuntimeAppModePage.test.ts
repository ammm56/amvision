import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { shallowRef, ref, reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionStore } from '@/app/stores/session.store'
import { ApiError } from '@/shared/api/error'
import { i18n } from '@/platform/i18n'
import type { RuntimePreviewSnapshot } from '../preview/useRuntimePreview'
import WorkflowRuntimeAppModePage from './WorkflowRuntimeAppModePage.vue'

const mocks = vi.hoisted(() => ({ preview: vi.fn(), invoke: vi.fn(), load: vi.fn(), route: { params: { workflowRuntimeId: 'runtime' } }, build: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => mocks.route,
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('../preview/useRuntimePreview', () => ({ useRuntimePreview: mocks.preview }))
vi.mock('../services/workflow-runtime.service', () => ({ invokeWorkflowAppRuntime: mocks.invoke }))
vi.mock('../app-mode/useWorkflowAppModeInputs', async (importOriginal) => {
  const original = await importOriginal<typeof import('../app-mode/useWorkflowAppModeInputs')>()
  return { useWorkflowAppModeInputs: () => {
    const form = original.useWorkflowAppModeInputs()
    return { ...form, build: (...args: Parameters<typeof form.build>) => mocks.build(...args) ?? form.build(...args) }
  } }
})

// 使用真实输入组件验证零输入仍可执行，以及权限和 Runtime 状态的调用边界。
function setupPage(canInvoke: boolean, withInput = false) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  session.$patch({ currentUser: {
    principal_id: 'operator', principal_type: 'user', project_ids: ['p'],
    scopes: ['workflows:read', ...(canInvoke ? ['workflows:invoke'] : [])],
    allowed_pages: ['workflow-app-mode'],
  } })
  const snapshot = shallowRef({
    workflow_runtime_id: 'runtime', workflow_runtime_revision_id: 'revision', runtime_generation: 1, worker_instance_id: 'worker',
    workflow_app_version_id: 'version', observed_state: 'running', active: true,
    app_mode: { format_id: 'amvision.workflow-app-mode.v1', title: '现场显示', displays: [] },
    application: { bindings: [] },
    contract: { inputs: withInput ? [{
      binding_id: 'text', template_port_id: 'text', payload_type_id: 'text.v1',
      required: false, config: {}, transports: [], allowed_media_types: [],
    }] : [] },
    template: { nodes: [], template_inputs: [] },
  } as unknown as RuntimePreviewSnapshot)
  const status = ref('waiting')
  mocks.preview.mockReturnValue({
    snapshot, status, error: ref(''), loading: ref(false), lastRun: ref(null), load: mocks.load,
    displays: {
      previewNodeDisplays: ref({}), activeImageViewer: ref(null),
      activePreviewTable: ref(null), activePreviewJson: ref(null),
    },
  })
  const wrapper = mount(WorkflowRuntimeAppModePage, {
    global: { plugins: [pinia, i18n], stubs: { WorkflowPreviewViewers: true } },
  })
  return { wrapper, session, snapshot, status }
}

describe('Runtime 应用模式输入和权限布局', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.build.mockReset()
    mocks.invoke.mockReset().mockResolvedValue({ state: 'succeeded', error: null })
    mocks.route = reactive({ params: { workflowRuntimeId: 'runtime' } })
  })

  it('失败回执不依赖预览，工作进程恢复后仍显示明确错误', async () => {
    let finish!: (value: unknown) => void
    mocks.invoke.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const { wrapper, snapshot } = setupPage(true)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    snapshot.value = { ...snapshot.value, runtime_generation: 2, worker_instance_id: 'new-worker' }
    finish({ state: 'failed', error: { message: '等待工作进程回复超时' } })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toBe('等待工作进程回复超时')
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it.each(['route', 'version', 'worker', 'permission', 'unmount'])('输入晚完成时不向已改变的上下文发起调用：%s', async (change) => {
    let finish!: (value: unknown) => void
    mocks.build.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const { wrapper, snapshot, session } = setupPage(true)
    await wrapper.find('form').trigger('submit')
    if (change === 'route') mocks.route.params.workflowRuntimeId = 'other'
    if (change === 'version') snapshot.value = { ...snapshot.value, workflow_app_version_id: 'next-version' }
    if (change === 'worker') snapshot.value = { ...snapshot.value, runtime_generation: 2, worker_instance_id: 'next-worker' }
    if (change === 'permission') session.$patch({ currentUser: { ...session.currentUser!, scopes: ['workflows:read'] } })
    if (change === 'unmount') wrapper.unmount()
    finish({ inputBindings: {}, fileUploads: [] })
    await flushPromises()
    expect(mocks.invoke).not.toHaveBeenCalled()
    if (change !== 'unmount') wrapper.unmount()
  })

  it.each(['failed', 'reject'])('旧调用晚返回不覆盖新 Runtime 的输入或错误：%s', async (result) => {
    let finish!: (value: unknown) => void
    let reject!: (cause: Error) => void
    mocks.invoke.mockReturnValueOnce(new Promise((resolve, fail) => { finish = resolve; reject = fail }))
    const { wrapper, snapshot } = setupPage(true, true)
    await wrapper.find('textarea').setValue('old input')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    mocks.route.params.workflowRuntimeId = 'other'
    snapshot.value = { ...snapshot.value, workflow_runtime_id: 'other' }
    await flushPromises()
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('')
    await wrapper.find('textarea').setValue('new input')
    if (result === 'failed') finish({ state: 'failed', error: { message: 'old failure' } })
    else reject(new Error('old failure'))
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('new input')
    expect(mocks.invoke).toHaveBeenCalledTimes(1)
    expect(mocks.invoke.mock.calls[0]![0]).toBe('runtime')
    wrapper.unmount()
  })

  it('卸载后忽略晚返回的授权错误，不刷新已离开页面的权限', async () => {
    let reject!: (cause: Error) => void
    mocks.invoke.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail }))
    const { wrapper, session } = setupPage(true)
    const refresh = vi.spyOn(session, 'refreshPermissions').mockResolvedValue()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    wrapper.unmount()
    reject(new ApiError(403, { message: 'late failure' }))
    await flushPromises()
    expect(refresh).not.toHaveBeenCalled()
  })

  it.each([false, true])('有执行权限时保留输入区，存在输入：%s', async (withInput) => {
    const { wrapper } = setupPage(true, withInput)
    expect(wrapper.find('form.app-mode-inputs').exists()).toBe(true)
    expect(wrapper.find('.runtime-app-mode__body').classes())
      .not.toContain('runtime-app-mode__body--read-only')
    expect(wrapper.find('.runtime-app-mode__body').classes().includes('runtime-app-mode__body--without-inputs'))
      .toBe(!withInput)
    if (!withInput) {
      await wrapper.find('form').trigger('submit')
      await flushPromises()
      expect(mocks.invoke).toHaveBeenCalledWith('runtime', expect.objectContaining({
        executionMetadata: { workflow_run_record_mode: 'none' },
      }))
    }
    wrapper.unmount()
  })

  it.each([false, true])('只读账号使用单个结果区且不执行，存在输入：%s', (withInput) => {
    const { wrapper } = setupPage(false, withInput)
    expect(wrapper.find('form.app-mode-inputs').exists()).toBe(false)
    expect(wrapper.find('.runtime-app-mode__body').classes()).toContain('runtime-app-mode__body--read-only')
    expect(wrapper.find('.runtime-app-mode__body').element.children).toHaveLength(1)
    expect(mocks.invoke).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('撤销执行权限后移除运行面板，不重放流程', async () => {
    const { wrapper, session } = setupPage(true)
    session.$patch({ currentUser: { ...session.currentUser!, scopes: ['workflows:read'] } })
    await flushPromises()
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.find('.runtime-app-mode__body').classes()).toContain('runtime-app-mode__body--read-only')
    expect(mocks.invoke).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('停止或停用的 Runtime 拒绝执行', async () => {
    const { wrapper, snapshot } = setupPage(true)
    for (const state of [{ observed_state: 'stopped', active: true }, { observed_state: 'running', active: false }]) {
      snapshot.value = { ...snapshot.value, ...state } as RuntimePreviewSnapshot
      await flushPromises()
      expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeDefined()
      await wrapper.find('form').trigger('submit')
      await flushPromises()
      expect(mocks.invoke).not.toHaveBeenCalled()
    }
    wrapper.unmount()
  })

  it('显示观察断线、停止和认证失败状态，不把旧画面冒充实时结果', async () => {
    const { wrapper, status } = setupPage(true)
    for (const state of ['disconnected', 'stopped', 'authUnavailable', 'capacityExceeded', 'connecting', 'waiting', 'live']) {
      status.value = state
      await flushPromises()
      expect(wrapper.find('[role="status"]').text()).toBe(i18n.global.t(`workflowEditor.runtimePreview.${state}`))
    }
    expect(mocks.invoke).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
