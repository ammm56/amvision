import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSessionStore } from '@/app/stores/session.store'
import { i18n } from '@/platform/i18n'
import TrainingTaskDetailPage from '@/modules/models/pages/TrainingTaskDetailPage.vue'
import ConversionTaskDetailPage from '@/modules/models/pages/ConversionTaskDetailPage.vue'
import ResourceMenu from '@/shared/ui/components/ResourceMenu.vue'
import * as service from '@/modules/models/services/model.service'
import { conversionTask, deferred, outputFile, TaskTestSocket, trainingTask } from './task_lifecycle_support'

vi.mock('@/modules/models/services/model.service', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/modules/models/services/model.service')>(),
  getModelTrainingTaskDetail: vi.fn(), listModelTrainingOutputFiles: vi.fn(), getModelTrainingOutputFileDetail: vi.fn(),
  downloadModelTrainingOutputFile: vi.fn(),
  requestModelTrainingTaskAction: vi.fn(), registerModelTrainingLatestCheckpoint: vi.fn(), deleteModelTrainingTask: vi.fn(),
  previewModelTrainingResume: vi.fn(),
  getModelConversionTaskDetail: vi.fn(), deleteModelConversionTask: vi.fn(), downloadModelConversionReport: vi.fn(), downloadModelConversionBuildFile: vi.fn(),
}))

enableAutoUnmount(afterEach)
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
beforeEach(() => {
  vi.resetAllMocks()
  TaskTestSocket.instances = []
  vi.stubGlobal('WebSocket', TaskTestSocket)
  vi.mocked(service.getModelTrainingTaskDetail).mockImplementation(async (type, id) => trainingTask(id, type))
  vi.mocked(service.listModelTrainingOutputFiles).mockResolvedValue([])
  vi.mocked(service.getModelTrainingOutputFileDetail).mockImplementation(async (_type, id, name) => outputFile(id, name))
  vi.mocked(service.getModelConversionTaskDetail).mockImplementation(async (_type, id) => conversionTask(id))
  vi.mocked(service.previewModelTrainingResume).mockResolvedValue({ checkpoint_name: 'latest.pt', dataset_export_id: 'export' })
})

type Kind = 'training' | 'conversion'
const url = (kind: Kind, id: string, type = 'classification') => `/models/${type}/${kind}-tasks/${id}`

async function openPage(kind: Kind, type = 'classification') {
  const pinia = createPinia()
  const session = useSessionStore(pinia)
  vi.spyOn(session, 'isAuthenticated', 'get').mockReturnValue(true)
  vi.spyOn(session, 'hasScopes').mockReturnValue(true)
  session.websocketQueryTokenEnabled = true
  session.accessToken = 'test-only'
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/models/:taskType/training-tasks/:taskId', component: TrainingTaskDetailPage },
    { path: '/models/:taskType/conversion-tasks/:taskId', component: ConversionTaskDetailPage },
    { path: '/models', component: { template: '<p>models list</p>' } },
    { path: '/tasks/:taskId', component: { template: '<p>task status</p>' } },
  ] })
  await router.push(url(kind, 'a', type))
  await router.isReady()
  const wrapper = mount(defineComponent({ render: () => h(RouterView) }), {
    global: { plugins: [pinia, i18n, router], stubs: { TrainingMetricsCharts: true, teleport: true } },
  })
  return { wrapper, router }
}

function button(wrapper: VueWrapper, label: string) {
  const match = wrapper.findAll('button').find((item) => item.text() === label
    || (label === '删除' && item.text() === '删除任务记录'))
  if (!match) throw new Error(`Missing button: ${label}`)
  return match
}

async function confirmDelete(wrapper: VueWrapper) {
  await openDelete(wrapper)
  await wrapper.get('[role="dialog"] .ui-button--danger').trigger('click')
}

async function openDelete(wrapper: VueWrapper) {
  if (wrapper.findComponent(ConversionTaskDetailPage).exists()) {
    const menu = wrapper.getComponent(ResourceMenu)
    const action = menu.props('items').find(item => item.id === 'delete')
    expect(action?.disabled).toBe(false)
    menu.vm.$emit('action', 'delete')
    await wrapper.vm.$nextTick()
  } else {
    await button(wrapper, '删除').trigger('click')
  }
}

it('shows conversion stages only as completed when the task report confirms them', async () => {
  vi.mocked(service.getModelConversionTaskDetail).mockResolvedValue({
    ...conversionTask('a'),
    task_spec: { planned_steps: [{ kind: 'export-onnx' }, { kind: 'build-openvino-ir' }] },
    report_summary: { executed_step_kinds: ['export-onnx'], validation_summary: { stage: 'validate-onnx', allclose: false, max_abs_diff: 0.012 } },
  })
  const { wrapper } = await openPage('conversion')
  await flushPromises()
  const stages = wrapper.findAll('.conversion-stage-timeline li')
  expect(stages).toHaveLength(4)
  expect(stages[0]!.text()).toContain('已完成')
  expect(stages[1]!.text()).toContain('未执行')
  expect(stages[1]!.classes()).not.toContain('is-done')
  expect(wrapper.find('.conversion-validation').text()).toContain('未通过')
  expect(wrapper.find('.conversion-validation').text()).toContain('0.012')
  expect(wrapper.find('.conversion-validation').text()).toContain('—')
})

it('shows the loading panel before opening conversion details in separate drawers', async () => {
  const pending = deferred<service.ModelConversionTaskDetail>()
  vi.mocked(service.getModelConversionTaskDetail).mockReturnValueOnce(pending.promise)
  const { wrapper, router } = await openPage('conversion')
  expect(wrapper.get('.loading-panel').text()).toContain('正在加载转换详情')
  expect(wrapper.find('.conversion-output').exists()).toBe(false)

  pending.resolve({
    ...conversionTask('a'),
    runtime_profile_id: 'openvino-cpu',
    report_summary: { validation_summary: { allclose: true, target_runtime: 'OpenVINO' } },
    events: [{ task_id: 'a', event_id: 'log-1', event_type: 'status', message: 'conversion succeeded', created_at: '2026-10-21T00:00:00Z', payload: {} }],
  })
  await flushPromises()
  expect(wrapper.find('.loading-panel').exists()).toBe(false)
  const output = wrapper.get('.conversion-output')
  expect(output.get('h2').text()).toBe('输出文件')
  expect(output.text()).not.toContain('conversion succeeded')

  await button(wrapper, '运行日志').trigger('click')
  expect(wrapper.get('[role="dialog"]').text()).toContain('conversion succeeded')
  await wrapper.get('[role="dialog"] .side-drawer__close').trigger('click')
  await button(wrapper, '参数配置').trigger('click')
  expect(wrapper.get('[role="dialog"]').text()).toContain('转换设置')
  expect(wrapper.get('[role="dialog"]').text()).toContain('openvino-cpu')
  await wrapper.get('[role="dialog"] .side-drawer__close').trigger('click')
  await button(wrapper, '环境信息').trigger('click')
  expect(wrapper.get('[role="dialog"]').text()).toContain('运行时校验通过')
  expect(wrapper.findAll('[role="dialog"]')).toHaveLength(1)
  expect(wrapper.find('.conversion-output').exists()).toBe(true)

  await router.push(url('conversion', 'b'))
  await flushPromises()
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
})

it('shows the cancelled stage, unstarted publication, elapsed duration, and log from the task record', async () => {
  const base = conversionTask('a')
  vi.mocked(service.getModelConversionTaskDetail).mockResolvedValue({
    ...base, state: 'cancelled', produced_formats: [],
    started_at: '2026-11-19T01:00:00Z', finished_at: '2026-11-19T01:01:19Z',
    progress: { stage: 'build-tensorrt-engine' }, report_summary: { executed_step_kinds: ['export-onnx'] },
    task_spec: { planned_steps: ['export-onnx', 'build-tensorrt-engine'].map(kind => ({ kind })) },
    events: [{ task_id: 'a', event_id: 'event-1', event_type: 'status', created_at: '2026-11-19T01:01:19Z', message: 'Task cancelled', payload: {} }],
  })
  const { wrapper } = await openPage('conversion')
  await flushPromises()
  const stages = wrapper.findAll('.conversion-stage-timeline li')
  expect(stages.map(stage => stage.classes().find(name => name.startsWith('is-')))).toEqual(['is-done', 'is-cancelled', 'is-skipped'])
  expect(wrapper.find('.conversion-terminal-summary').text()).toContain('1分钟 19秒')
  expect(wrapper.text()).toContain('没有新增可用产物')
  expect(wrapper.findAll('button').some(item => /下载/.test(item.text()))).toBe(false)
  await button(wrapper, '查看日志').trigger('click')
  expect(wrapper.get('[role="dialog"]').text()).toContain('Task cancelled')
})

it('cancels a conversion report download when switching tasks', async () => {
  vi.mocked(service.getModelConversionTaskDetail).mockImplementation(async (_type, id) => ({
    ...conversionTask(id), result: { report_object_key: `task-runs/conversion/${id}/artifacts/reports/conversion-report.json` },
  }))
  const pending = deferred<Blob>()
  vi.mocked(service.downloadModelConversionReport).mockReturnValue(pending.promise)
  const { wrapper, router } = await openPage('conversion')
  await flushPromises()
  expect(wrapper.get('.conversion-output table').text()).toContain('conversion-report.json')
  await button(wrapper, '下载报告').trigger('click')
  const signal = vi.mocked(service.downloadModelConversionReport).mock.calls[0]?.[2]
  await router.push(url('conversion', 'b'))
  await flushPromises()
  expect(signal?.aborted).toBe(true)
  pending.resolve(new Blob(['old task']))
  await flushPromises()
  expect(wrapper.text()).not.toContain('报告下载失败')
})

it('downloads OpenVINO weights separately and cancels them on task switch', async () => {
  vi.mocked(service.getModelConversionTaskDetail).mockImplementation(async (_type, id) => ({
    ...conversionTask(id), builds: [{ model_build_id: 'build-1', build_format: 'openvino-ir', runtime_backend: 'openvino', runtime_precision: 'fp32', build_file_id: 'file-1', build_file_uri: 'model.xml', metadata: { weights_object_uri: 'model.bin' } }],
  }))
  const pending = deferred<Blob>()
  vi.mocked(service.downloadModelConversionBuildFile).mockReturnValue(pending.promise)
  const { wrapper, router } = await openPage('conversion')
  await flushPromises()
  await button(wrapper, '下载权重').trigger('click')
  expect(service.downloadModelConversionBuildFile).toHaveBeenCalledWith('classification', 'a', 'build-1', 'weights', expect.any(AbortSignal))
  const signal = vi.mocked(service.downloadModelConversionBuildFile).mock.calls[0]?.[4]
  await router.push(url('conversion', 'b'))
  await flushPromises()
  expect(signal?.aborted).toBe(true)
  pending.resolve(new Blob(['old weights']))
  await flushPromises()
  expect(wrapper.text()).not.toContain('文件下载失败')
})

describe.each<Kind>(['training', 'conversion'])('%s task route ownership', (kind) => {
  const detail = () => kind === 'training'
    ? vi.mocked(service.getModelTrainingTaskDetail)
    : vi.mocked(service.getModelConversionTaskDetail)

  it('includes task type in ownership but does not reload for unrelated query changes', async () => {
    const { wrapper, router } = await openPage(kind)
    await flushPromises()
    await router.push(`${url(kind, 'a')}?view=summary`)
    await flushPromises()
    expect(detail()).toHaveBeenCalledTimes(1)
    const oldSockets = [...TaskTestSocket.instances]
    await router.push(url(kind, 'a', 'detection'))
    await flushPromises()
    expect(detail().mock.lastCall?.slice(0, 3)).toEqual(['detection', 'a', expect.any(AbortSignal)])
    expect(oldSockets.every((socket) => socket.closed)).toBe(true)
    expect(wrapper.text()).toContain(`${kind} a`)
    await confirmDelete(wrapper)
    expect(kind === 'training' ? service.deleteModelTrainingTask : service.deleteModelConversionTask)
      .toHaveBeenCalledWith('detection', 'a')
  })

  it('reuses the component but clears old data and dialog before loading the next task', async () => {
    const { wrapper, router } = await openPage(kind)
    await flushPromises()
    const pageId = wrapper.findComponent(kind === 'training' ? TrainingTaskDetailPage : ConversionTaskDetailPage).vm.$.uid
    await openDelete(wrapper)
    const pending = deferred<ReturnType<typeof trainingTask>>()
    // 两类详情返回结构分别由各自 service mock 保持；此处只延迟完成。
    detail().mockImplementationOnce(() => pending.promise as never)
    await router.push(url(kind, 'b', 'detection'))
    expect(wrapper.text()).not.toContain(`${kind} a`)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.findAll('button').some((item) => item.text() === '删除')).toBe(false)
    expect(TaskTestSocket.active()).toHaveLength(0)
    pending.resolve((kind === 'training' ? trainingTask('b', 'detection') : conversionTask('b')) as ReturnType<typeof trainingTask>)
    await flushPromises()
    expect(wrapper.findComponent(kind === 'training' ? TrainingTaskDetailPage : ConversionTaskDetailPage).vm.$.uid).toBe(pageId)
    expect(wrapper.text()).toContain(`${kind} b`)
    expect(detail().mock.lastCall?.slice(0, 3)).toEqual(['detection', 'b', expect.any(AbortSignal)])
    await confirmDelete(wrapper)
    await flushPromises()
    expect(kind === 'training' ? service.deleteModelTrainingTask : service.deleteModelConversionTask)
      .toHaveBeenCalledWith('detection', 'b')
    expect(router.currentRoute.value.path).toBe('/models')
  })

  it.each(['resolve', 'reject'] as const)('ignores a late %s after A -> B -> A and aborts the old read', async (completion) => {
    const pending = deferred<ReturnType<typeof trainingTask>>()
    detail().mockImplementationOnce(() => pending.promise as never)
    const { wrapper, router } = await openPage(kind)
    const signal = detail().mock.calls[0]?.[2]
    await router.push(url(kind, 'b'))
    await flushPromises()
    await router.push(url(kind, 'a'))
    await flushPromises()
    const currentReads = detail().mock.calls.length
    if (completion === 'reject') pending.reject(new Error('stale read failure'))
    else pending.resolve({ ...(kind === 'training' ? trainingTask('a') : conversionTask('a')), display_name: 'stale response' } as ReturnType<typeof trainingTask>)
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    expect(wrapper.text()).toContain(`${kind} a`)
    expect(wrapper.text()).not.toContain('stale')
    expect(detail()).toHaveBeenCalledTimes(currentReads)
    expect(TaskTestSocket.active()).toHaveLength(kind === 'training' ? 2 : 0)
  })

  it.each(['resolve', 'reject'] as const)('does not navigate or change the next task after a late deletion %s', async (completion) => {
    const deletion = kind === 'training' ? vi.mocked(service.deleteModelTrainingTask) : vi.mocked(service.deleteModelConversionTask)
    const pending = deferred<void>()
    deletion.mockReturnValueOnce(pending.promise)
    const { wrapper, router } = await openPage(kind)
    await flushPromises()
    await confirmDelete(wrapper)
    expect(deletion).toHaveBeenCalledWith('classification', 'a')
    await router.push(url(kind, 'b'))
    await flushPromises()
    await openDelete(wrapper)
    if (completion === 'reject') pending.reject(new Error('old deletion failed'))
    else pending.resolve()
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(url(kind, 'b'))
    expect(wrapper.text()).toContain(`${kind} b`)
    expect(wrapper.text()).not.toContain('old deletion failed')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
  })

  it.each(['resolve', 'reject'] as const)('does not revive requests or connections after unmount and late %s', async (completion) => {
    const pending = deferred<ReturnType<typeof trainingTask>>()
    detail().mockImplementationOnce(() => pending.promise as never)
    const { wrapper } = await openPage(kind)
    const signal = detail().mock.calls[0]?.[2]
    wrapper.unmount()
    if (completion === 'reject') pending.reject(new Error('unmounted request'))
    else pending.resolve((kind === 'training' ? trainingTask('a') : conversionTask('a')) as ReturnType<typeof trainingTask>)
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    expect(TaskTestSocket.instances).toHaveLength(0)
    expect(service.getModelTrainingOutputFileDetail).not.toHaveBeenCalled()
  })

  it('does not navigate after a deletion completes on an unmounted page', async () => {
    const deletion = kind === 'training' ? vi.mocked(service.deleteModelTrainingTask) : vi.mocked(service.deleteModelConversionTask)
    const pending = deferred<void>()
    deletion.mockReturnValueOnce(pending.promise)
    const { wrapper, router } = await openPage(kind)
    await flushPromises()
    await confirmDelete(wrapper)
    const push = vi.spyOn(router, 'push')
    wrapper.unmount()
    pending.resolve()
    await flushPromises()
    expect(push).not.toHaveBeenCalled()
    expect(TaskTestSocket.active()).toHaveLength(0)
  })
})

describe('training task nested reads and operations', () => {
  it('keeps same-task subscriptions and commits only the latest overlapping refresh', async () => {
    const action = deferred<service.ModelTrainingTaskDetail>()
    const oldRead = deferred<service.ModelTrainingTaskDetail>()
    vi.mocked(service.requestModelTrainingTaskAction).mockReturnValueOnce(action.promise)
    const { wrapper } = await openPage('training')
    await flushPromises()
    const sockets = [...TaskTestSocket.instances]
    await button(wrapper, '保存').trigger('click')
    vi.mocked(service.getModelTrainingTaskDetail).mockReturnValueOnce(oldRead.promise)
    await button(wrapper, '刷新').trigger('click')
    const oldSignal = vi.mocked(service.getModelTrainingTaskDetail).mock.calls[1]?.[2]
    action.resolve(trainingTask('a'))
    await flushPromises()
    oldRead.resolve({ ...trainingTask('a'), display_name: 'outdated snapshot' })
    await flushPromises()
    expect(oldSignal?.aborted).toBe(true)
    expect(wrapper.text()).toContain('training a')
    expect(wrapper.text()).not.toContain('outdated snapshot')
    expect(TaskTestSocket.instances).toHaveLength(2)
    expect(sockets.every((socket) => !socket.closed)).toBe(true)
    expect(button(wrapper, '保存').attributes('disabled')).toBeUndefined()
  })

  it.each(['switch', 'unmount'] as const)('ignores late action errors after %s', async (exit) => {
    const pending = deferred<service.ModelTrainingTaskDetail>()
    vi.mocked(service.requestModelTrainingTaskAction).mockReturnValueOnce(pending.promise)
    const { wrapper, router } = await openPage('training')
    await flushPromises()
    await button(wrapper, '暂停').trigger('click')
    if (exit === 'switch') { await router.push(url('training', 'b')); await flushPromises() }
    else wrapper.unmount()
    pending.reject(new Error('obsolete action failure'))
    await flushPromises()
    expect(service.getModelTrainingTaskDetail).toHaveBeenCalledTimes(exit === 'switch' ? 2 : 1)
    if (exit === 'switch') expect(wrapper.text()).not.toContain('obsolete action failure')
    else expect(TaskTestSocket.active()).toHaveLength(0)
  })
  it.each([
    ['pause', '暂停'], ['save', '保存'], ['terminate', '取消训练'], ['resume', '恢复'],
  ] as const)('pins %s to the displayed task and ignores its late response', async (action, label) => {
    const pending = deferred<service.ModelTrainingTaskDetail>()
    vi.mocked(service.requestModelTrainingTaskAction).mockReturnValueOnce(pending.promise)
    const { wrapper, router } = await openPage('training')
    await flushPromises()
    await button(wrapper, label).trigger('click')
    if (action === 'resume') {
      await flushPromises()
      await wrapper.get('[role="dialog"] .ui-button--primary').trigger('click')
    } else if (action === 'terminate') {
      await wrapper.get('[role="dialog"] .ui-button--danger').trigger('click')
    }
    expect(service.requestModelTrainingTaskAction).toHaveBeenCalledWith('classification', 'a', action)
    await router.push(url('training', 'b', 'pose'))
    await flushPromises()
    pending.resolve(trainingTask('a'))
    await flushPromises()
    expect(service.getModelTrainingTaskDetail).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('training b')
    await button(wrapper, label).trigger('click')
    if (action === 'resume') {
      await flushPromises()
      await wrapper.get('[role="dialog"] .ui-button--primary').trigger('click')
    } else if (action === 'terminate') {
      await wrapper.get('[role="dialog"] .ui-button--danger').trigger('click')
    }
    expect(service.requestModelTrainingTaskAction).toHaveBeenLastCalledWith('pose', 'b', action)
  })

  it('does not overwrite a new task when checkpoint registration returns', async () => {
    const pending = deferred<service.ModelTrainingTaskDetail>()
    vi.mocked(service.registerModelTrainingLatestCheckpoint).mockReturnValueOnce(pending.promise)
    const { wrapper, router } = await openPage('training', 'detection')
    await flushPromises()
    const register = wrapper.findAll('button').find((item) => item.text().includes('登记 latest checkpoint'))
    expect(register).toBeDefined()
    await register!.trigger('click')
    expect(service.registerModelTrainingLatestCheckpoint).toHaveBeenCalledWith('detection', 'a')
    await router.push(url('training', 'b'))
    await flushPromises()
    pending.resolve(trainingTask('a', 'detection'))
    await flushPromises()
    expect(wrapper.text()).toContain('training b')
    expect(service.getModelTrainingTaskDetail).toHaveBeenCalledTimes(2)
  })

  it('retains a successful checkpoint registration if the subsequent refresh fails', async () => {
    const { wrapper } = await openPage('training', 'detection')
    await flushPromises()
    vi.mocked(service.registerModelTrainingLatestCheckpoint).mockResolvedValueOnce({
      ...trainingTask('a', 'detection'), latest_checkpoint_model_version_id: 'registered-version-a',
    })
    vi.mocked(service.getModelTrainingTaskDetail).mockRejectedValueOnce(new Error('refresh unavailable'))
    await button(wrapper, '登记 latest checkpoint').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已登记')
    expect(wrapper.text()).toContain('refresh unavailable')
    expect(button(wrapper, '登记 latest checkpoint').attributes('disabled')).toBeUndefined()
    expect(TaskTestSocket.active()).toHaveLength(2)
  })

  it.each(['switch', 'unmount'] as const)('discards pending metric reads on %s without starting old subscriptions', async (exit) => {
    const pending = deferred<service.ModelTrainingOutputFileDetail>()
    vi.mocked(service.listModelTrainingOutputFiles).mockResolvedValueOnce([outputFile('a', 'train-metrics')])
    vi.mocked(service.getModelTrainingOutputFileDetail).mockReturnValueOnce(pending.promise)
    const { wrapper, router } = await openPage('training')
    await flushPromises()
    const signal = vi.mocked(service.getModelTrainingOutputFileDetail).mock.calls[0]?.[3]
    if (exit === 'switch') { await router.push(url('training', 'b')); await flushPromises() }
    else wrapper.unmount()
    pending.resolve({ ...outputFile('a', 'train-metrics'), payload: { final_metrics: { stale_loss: 999 } } })
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    expect(service.getModelTrainingOutputFileDetail).toHaveBeenCalledTimes(1)
    expect(TaskTestSocket.active()).toHaveLength(exit === 'switch' ? 2 : 0)
    if (exit === 'switch') expect(wrapper.text()).not.toContain('stale_loss')
  })

  it('uses the latest selected output, rejecting older preview results and failures', async () => {
    vi.mocked(service.listModelTrainingOutputFiles).mockResolvedValue([outputFile('a', 'first'), outputFile('a', 'second')])
    const pending = deferred<service.ModelTrainingOutputFileDetail>()
    vi.mocked(service.getModelTrainingOutputFileDetail).mockReturnValueOnce(pending.promise)
    const { wrapper } = await openPage('training')
    await flushPromises()
    const rows = wrapper.findAll('.training-output-layout tbody tr')
    await rows[0]!.get('button').trigger('click')
    await flushPromises()
    const firstSignal = vi.mocked(service.getModelTrainingOutputFileDetail).mock.calls[0]?.[3]
    await wrapper.get('[role="dialog"] .side-drawer__close').trigger('click')
    await flushPromises()
    await rows[1]!.get('button').trigger('click')
    await flushPromises()
    pending.reject(new Error('old preview failed'))
    await flushPromises()
    expect(firstSignal?.aborted).toBe(true)
    const preview = wrapper.get('[role="dialog"]')
    expect(preview.get('h2').text()).toBe('second')
    expect(preview.text()).not.toContain('old preview failed')
  })

  it('cancels a file download when leaving the training task', async () => {
    vi.mocked(service.listModelTrainingOutputFiles).mockResolvedValue([outputFile('a', 'first')])
    const pending = deferred<Blob>()
    vi.mocked(service.downloadModelTrainingOutputFile).mockReturnValue(pending.promise)
    const { wrapper, router } = await openPage('training')
    await flushPromises()
    await button(wrapper, '下载').trigger('click')
    const signal = vi.mocked(service.downloadModelTrainingOutputFile).mock.calls[0]?.[3]
    await router.push(url('training', 'b'))
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    pending.resolve(new Blob(['old task']))
    await flushPromises()
    expect(wrapper.text()).not.toContain('下载训练输出文件失败')
  })

  it.each(['switch', 'unmount'] as const)('discards late background file lists and cancels telemetry timers on %s', async (exit) => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const pending = deferred<service.ModelTrainingOutputFileSummary[]>()
    vi.mocked(service.listModelTrainingOutputFiles).mockResolvedValueOnce([]).mockReturnValueOnce(pending.promise)
    const { wrapper, router } = await openPage('training')
    await flushPromises()
    const telemetry = TaskTestSocket.instances.find((socket) => socket.url.includes('/training/telemetry'))!
    telemetry.message({ protocol: 'training.telemetry.v1', task_id: 'a', attempt_no: 1, sequence: 1,
      timestamp: '2026-10-21T00:00:00Z', task_type: 'classification', model_type: 'yolo11',
      stage: 'training', granularity: 'batch', epoch: 2, metrics: {}, runtime: {} }, 'training.batch')
    await vi.advanceTimersByTimeAsync(350)
    const signal = vi.mocked(service.listModelTrainingOutputFiles).mock.calls[1]?.[2]
    if (exit === 'switch') { await router.push(url('training', 'b')); await flushPromises() }
    else wrapper.unmount()
    pending.resolve([outputFile('a', 'obsolete-output')])
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    expect(service.getModelTrainingOutputFileDetail).not.toHaveBeenCalled()
    if (exit === 'switch') expect(wrapper.text()).not.toContain('obsolete-output')
    else expect(TaskTestSocket.active()).toHaveLength(0)
  })

  it('clears histories, late socket events, scheduled refreshes and pending previews on task switch', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    vi.mocked(service.listModelTrainingOutputFiles).mockResolvedValueOnce([outputFile('a', 'first')])
    const pending = deferred<service.ModelTrainingOutputFileDetail>()
    vi.mocked(service.getModelTrainingOutputFileDetail).mockReturnValueOnce(pending.promise)
    const { wrapper, router } = await openPage('training')
    await flushPromises()
    const sockets = [...TaskTestSocket.instances]
    const events = sockets.find((socket) => socket.url.includes('/tasks/events'))!
    events.message({ task_id: 'a', data: { progress: { train_metrics: { stale_loss: 999 } } } }, 'status')
    await router.push(url('training', 'b'))
    await flushPromises()
    events.message({ task_id: 'a', data: { state: 'failed', progress: { train_metrics: { stale_loss: 999 } } } }, 'status')
    pending.resolve(outputFile('a', 'first'))
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(sockets.every((socket) => socket.closed)).toBe(true)
    expect(wrapper.text()).not.toContain('stale_loss')
    expect(wrapper.text()).not.toContain('a/first')
    expect(service.getModelTrainingTaskDetail).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(20000)
    expect(TaskTestSocket.active()).toHaveLength(0)
    expect(vi.getTimerCount()).toBe(0)
  })
})
