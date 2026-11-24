import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import TrainingTaskDetailPage from './TrainingTaskDetailPage.vue'
import TrainingMetricsCharts from '../components/TrainingMetricsCharts.vue'
import { estimateTrainingRemainingSeconds } from '../training-remaining-time'
import {
  getModelTrainingOutputFileDetail,
  getModelTrainingTaskDetail,
  getTrainingWorkerStatus,
  listModelTrainingOutputFiles,
  requestModelTrainingTaskAction,
  type ModelTrainingTaskDetail,
} from '../services/model.service'

enableAutoUnmount(afterEach)
afterEach(() => vi.useRealTimers())

const taskEventStreamMock = vi.hoisted(() => ({
  handler: null as ((event: Record<string, unknown>) => void) | null,
  start: vi.fn(),
}))

const trainingTelemetryStreamMock = vi.hoisted(() => ({
  handler: null as ((payload: Record<string, unknown>) => void) | null,
  start: vi.fn(),
}))

vi.mock('@/app/stores/session.store', () => ({ useSessionStore: () => ({ hasScopes: () => true }) }))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual<typeof import('vue-router')>('vue-router')
  return {
    ...actual,
    RouterLink: { template: '<a><slot /></a>' },
    useRoute: () => ({
      params: {
        taskType: 'classification',
        taskId: 'task-classification-1',
      },
    }),
    useRouter: () => ({ push: vi.fn() }),
  }
})

vi.mock('../services/model.service', () => ({
  deleteModelTrainingTask: vi.fn(),
  downloadModelTrainingOutputFile: vi.fn(),
  getModelTrainingOutputFileDetail: vi.fn(),
  getModelTrainingTaskDetail: vi.fn(),
  getTrainingWorkerStatus: vi.fn(),
  listModelTrainingOutputFiles: vi.fn(),
  registerModelTrainingLatestCheckpoint: vi.fn(),
  requestModelTrainingTaskAction: vi.fn(),
}))

vi.mock('@/modules/tasks/composables/useTaskEvents', async () => {
  const { ref } = await import('vue')
  return {
    useTaskEvents: (_getTaskId: () => string, handler: (event: Record<string, unknown>) => void) => {
      taskEventStreamMock.handler = handler
      return {
      streamState: ref(null),
      start: taskEventStreamMock.start,
      stop: vi.fn(),
      }
    },
  }
})

vi.mock('../composables/useTrainingTelemetry', async () => {
  const { ref } = await import('vue')
  return {
    useTrainingTelemetry: (
      _getTaskId: () => string,
      handler: (payload: Record<string, unknown>) => void,
    ) => {
      trainingTelemetryStreamMock.handler = handler
      return {
        streamState: ref(null),
        start: trainingTelemetryStreamMock.start,
        stop: vi.fn(),
      }
    },
  }
})

describe('TrainingTaskDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    taskEventStreamMock.handler = null
    trainingTelemetryStreamMock.handler = null
  })

  it('estimates the remaining time from completed rounds including validation, without mixing attempts', () => {
    const events = [10, 14, 18, 26, 30].map((second, index) => ({
      event_id: `event-${index}`, task_id: 'task-classification-1',
      event_type: 'progress', created_at: new Date(second * 1_000).toISOString(), message: '',
      payload: { attempt_no: 2, progress: { epoch: 78 + index, train_metrics: { loss: 0.002 } } },
    }))
    expect(estimateTrainingRemainingSeconds(events, 2, 82, 100)).toBe(90)
    expect(estimateTrainingRemainingSeconds(events, 2, 83, 100)).toBe(85)
    expect(estimateTrainingRemainingSeconds(events, 3, 82, 100)).toBeNull()
    expect(estimateTrainingRemainingSeconds(events.slice(-2), 2, 82, 100)).toBeNull()
  })

  it('accounts for the future validation rounds when enough wall-clock samples are available', () => {
    let second = 0
    const events = Array.from({ length: 10 }, (_, index) => {
      const epoch = index + 1
      const validated = epoch % 3 === 0
      second += validated ? 13 : 3
      return {
        event_id: `event-${epoch}`, task_id: 'task-classification-1', event_type: 'progress',
        created_at: new Date(second * 1_000).toISOString(), message: '',
        payload: { attempt_no: 1, progress: { epoch, train_metrics: { loss: 0.002 }, validation_ran: validated } },
      }
    })
    expect(estimateTrainingRemainingSeconds(events, 1, 10, 14, 3)).toBe(32)
  })

  it('explains an offline worker and follows the queued task without a WebSocket event', async () => {
    vi.useFakeTimers()
    const queued: ModelTrainingTaskDetail = {
      task_id: 'task-classification-1', task_type: 'classification', model_type: 'yolo11',
      display_name: 'Queued training', project_id: 'project-1', created_at: '2026-07-10T02:00:00Z',
      state: 'queued', current_attempt_no: 1, progress: {}, result: {}, metadata: {},
      training_summary: {}, available_actions: ['terminate'], control_status: { status: 'idle', resume_count: 0 },
      task_spec: { max_epochs: 100 }, events: [],
    }
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue(queued)
    vi.mocked(getTrainingWorkerStatus).mockResolvedValueOnce({ status: 'unavailable' }).mockResolvedValue({ status: 'ready' })
    vi.mocked(listModelTrainingOutputFiles).mockResolvedValue([{
      file_name: 'train-metrics', file_kind: 'json', file_status: 'pending', task_state: 'queued',
    }])
    const wrapper = mount(TrainingTaskDetailPage, { global: { plugins: [i18n] } })
    await flushPromises()

    expect(wrapper.get('.training-queue [role="status"]').text()).toContain('训练 Worker 未就绪')
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.find('.training-output-layout').exists()).toBe(false)
    expect(getModelTrainingOutputFileDetail).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(5000)
    expect(wrapper.get('.training-queue [role="status"]').text()).toContain('等待训练 Worker 领取')
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue({ ...queued, state: 'running' })
    await vi.advanceTimersByTimeAsync(5000)
    expect(wrapper.find('.training-queue').exists()).toBe(false)
    expect(wrapper.get('.training-overview-progress [role="progressbar"]').attributes('aria-valuetext')).toBe('准备中')
    expect(wrapper.get('.training-overview-progress').text()).toContain('0 / 100')
  })

  it('marks a deleted registered output while keeping the completed training detail', async () => {
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue({
      task_id: 'task-classification-1', task_type: 'classification', model_type: 'yolo11', display_name: 'Completed training',
      project_id: 'project-1', created_at: '2026-07-10T02:00:00Z', state: 'succeeded', current_attempt_no: 1,
      progress: {}, result: { model_version_id: 'deleted-version' }, metadata: { deleted_model_version_ids: ['deleted-version'] },
      model_version_id: 'deleted-version', training_summary: {}, available_actions: [],
      control_status: { status: 'idle', resume_count: 0 }, task_spec: {}, events: [],
    })
    vi.mocked(listModelTrainingOutputFiles).mockResolvedValue([])
    const wrapper = mount(TrainingTaskDetailPage, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('输出模型版本已删除')
    expect(wrapper.get('.page-actions').text()).not.toContain('查看模型版本')
    expect(wrapper.get('.training-detail-title').text()).toContain('已完成')
  })

  it('confirms cancellation, keeps a failed request retryable and waits for the worker state', async () => {
    vi.useFakeTimers()
    const active: ModelTrainingTaskDetail = {
      task_id: 'task-classification-1', task_type: 'classification', model_type: 'yolo11',
      display_name: 'tray training', project_id: 'project-1', created_at: '2026-07-10T02:00:00Z',
      state: 'running', current_attempt_no: 1,
      progress: { epoch: 3, completed_epoch: 2, max_epochs: 4 }, result: {}, metadata: {},
      best_metric_name: null, best_metric_value: null, training_summary: {},
      available_actions: ['terminate'], control_status: { status: 'idle', resume_count: 0 },
      task_spec: {}, events: [],
    }
    const waiting: ModelTrainingTaskDetail = {
      ...active, available_actions: [],
      control_status: { status: 'pending', pending_action: 'terminate', resume_count: 0 },
    }
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue(active)
    vi.mocked(listModelTrainingOutputFiles).mockResolvedValue([])
    vi.mocked(requestModelTrainingTaskAction).mockRejectedValueOnce(new Error('取消请求失败，请重试')).mockResolvedValueOnce(waiting)
    const wrapper = mount(TrainingTaskDetailPage, { global: { plugins: [i18n] } })
    await flushPromises()
    const action = () => wrapper.get('.training-terminate')
    const confirm = () => wrapper.get('.confirm-dialog__actions .ui-button--danger')
    await action().trigger('click')
    expect(wrapper.get('[role="dialog"]').text()).toContain('已完成 2 / 4 轮')
    await wrapper.get('[data-confirm-cancel]').trigger('click')
    expect(requestModelTrainingTaskAction).not.toHaveBeenCalled()
    await action().trigger('click')
    await confirm().trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="dialog"]').text()).toContain('取消请求失败，请重试')
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue(waiting)
    await confirm().trigger('click')
    await flushPromises()
    expect(requestModelTrainingTaskAction).toHaveBeenLastCalledWith('classification', 'task-classification-1', 'terminate')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.get('.training-detail-title').text()).toContain('正在取消')
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue({ ...waiting, state: 'cancelled' })
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(wrapper.get('.training-detail-title').text()).toContain('已取消')
    expect(wrapper.get('.training-cancelled-progress').text()).toContain('停止在第 3 轮')
    expect(wrapper.get('.page-actions').text()).toContain('按此配置新建训练')
    expect(requestModelTrainingTaskAction).toHaveBeenCalledTimes(2)
  }, 15_000)

  it('renders non-detection progress, metrics, and output files', async () => {
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue({
      task_id: 'task-classification-1',
      task_type: 'classification',
      model_type: 'yolo11',
      display_name: 'completed yolo11 classifier with runtime snapshot',
      project_id: 'project-1',
      created_at: '2026-07-10T02:00:00Z',
      state: 'succeeded',
      current_attempt_no: 1,
      progress: {
        stage: 'running',
        epoch: 2,
        max_epochs: 4,
        percent: 75,
        learning_rate: 0.00025,
        current_metric_name: 'val_top1_accuracy',
        current_metric_value: 0.66,
        best_metric_name: 'val_top1_accuracy',
        best_metric_value: 0.66,
        train_metrics: { epoch: 1, loss: 0.1234567, accuracy: 0.875 },
        runtime: { step_time_ms: 19.6789 },
        validation_metrics: {
          epoch: 1,
          epoch_index: 0,
          top1_accuracy: 0.66,
          top5_accuracy: 1,
          'metrics/accuracy_top1': 0.66,
        },
      },
      result: {},
      metadata: {},
      dataset_export_id: 'dataset-export-1',
      model_version_id: 'classifier-output-version',
      latest_checkpoint_model_version_id: null,
      output_object_prefix: 'task-runs/task-classification-1',
      checkpoint_object_key: null,
      latest_checkpoint_object_key: 'task-runs/task-classification-1/output-files/latest-checkpoint.pt',
      labels_object_key: 'task-runs/task-classification-1/output-files/labels.txt',
      metrics_object_key: 'task-runs/task-classification-1/output-files/train-metrics.json',
      validation_metrics_object_key: 'task-runs/task-classification-1/output-files/validation-metrics.json',
      summary_object_key: 'task-runs/task-classification-1/output-files/training-summary.json',
      best_metric_name: 'val_top1_accuracy',
      best_metric_value: 0.66,
      training_summary: {},
      available_actions: ['save', 'pause', 'terminate'],
      control_status: {
        status: 'idle',
        pending_action: null,
        resume_count: 0,
        resume_checkpoint_object_key: null,
      },
      task_spec: {},
      events: [
        {
          event_id: 'event-1',
          task_id: 'task-classification-1',
          event_type: 'progress',
          created_at: '2026-07-10T02:01:00Z',
          message: 'YOLO11 classification epoch 2/4',
          payload: {},
        },
      ],
    })
    vi.mocked(listModelTrainingOutputFiles).mockResolvedValue([
      {
        file_name: 'train-metrics',
        file_kind: 'json',
        file_status: 'ready',
        task_state: 'running',
        object_key: 'task-runs/task-classification-1/output-files/train-metrics.json',
        size_bytes: 128,
        updated_at: '2026-07-10T02:01:00Z',
        epoch: 2,
      },
      {
        file_name: 'best-checkpoint',
        file_kind: 'checkpoint',
        file_status: 'ready',
        task_state: 'succeeded',
        object_key: 'task-runs/task-classification-1/output-files/best-checkpoint.pt',
        size_bytes: 128,
        epoch: 1,
      },
      {
        file_name: 'test-metrics',
        file_kind: 'json',
        file_status: 'ready',
        task_state: 'succeeded',
        object_key: 'task-runs/task-classification-1/output-files/test-metrics.json',
        epoch: null,
        checkpoint_role: 'best',
      },
      {
        file_name: 'runtime-metrics',
        file_kind: 'json',
        file_status: 'ready',
        task_state: 'running',
        object_key: 'task-runs/task-classification-1/output-files/runtime-metrics.json',
        size_bytes: 256,
        updated_at: '2026-07-10T02:01:01Z',
      },
    ])
    vi.mocked(getModelTrainingOutputFileDetail).mockImplementation(
      async (_taskType, _taskId, fileName) => fileName === 'runtime-metrics'
        ? {
            file_name: 'runtime-metrics',
            file_kind: 'json',
            file_status: 'ready',
            task_state: 'running',
            object_key: 'task-runs/task-classification-1/output-files/runtime-metrics.json',
            size_bytes: 256,
            updated_at: '2026-07-10T02:01:01Z',
            payload: {
              protocol: 'training.runtime-metrics.v1',
              runtime_history: [{
                attempt_no: 1,
                global_step: 12,
                timestamp: '2026-07-10T02:01:01Z',
                runtime: { samples_per_second: 42.5 },
              }],
            },
            text_content: null,
            lines: [],
          }
        : fileName === 'validation-metrics'
        ? {
            file_name: 'validation-metrics', file_kind: 'json', file_status: 'ready', task_state: 'succeeded',
            object_key: 'task-runs/task-classification-1/output-files/validation-metrics.json',
            payload: { epoch_history: [
              { epoch: 1, top1_accuracy: 0.66 },
              { epoch: 2, top1_accuracy: 0.66, 'metrics/accuracy_top1': 0.66, epoch_index: 1 },
            ] },
            text_content: null, lines: [],
          }
        : {
            file_name: 'train-metrics',
            file_kind: 'json',
            file_status: 'ready',
            task_state: 'running',
            object_key: 'task-runs/task-classification-1/output-files/train-metrics.json',
            size_bytes: 128,
            updated_at: '2026-07-10T02:01:00Z',
            payload: { final_metrics: { loss: 0.1234567, accuracy: 0.875, small_loss: 0.000013 } },
            text_content: null,
            lines: [],
          },
    )

    const wrapper = mount(TrainingTaskDetailPage, {
      global: {
        plugins: [i18n],
      },
    })
    await flushPromises()

    expect(listModelTrainingOutputFiles).toHaveBeenCalledWith(
      'classification',
      'task-classification-1',
      expect.any(AbortSignal),
    )
    expect(getModelTrainingOutputFileDetail).toHaveBeenCalledWith(
      'classification',
      'task-classification-1',
      'train-metrics',
      expect.any(AbortSignal),
    )
    expect(getModelTrainingOutputFileDetail).toHaveBeenCalledWith(
      'classification',
      'task-classification-1',
      'runtime-metrics',
      expect.any(AbortSignal),
    )
    expect(wrapper.get('.training-overview-progress [role="progressbar"]').attributes('aria-valuenow')).toBe('50')
    expect(wrapper.text()).toContain('2 / 4')
    expect(wrapper.text()).toContain('loss')
    expect(wrapper.text()).toContain('loss0.123accuracy')
    const trainFile = wrapper.get('.training-output-layout tbody tr:first-child')
    expect(trainFile.findAll('td')[4].text()).toBe('2')
    const bestFile = wrapper.findAll('.training-output-layout tbody tr').find(row => row.text().includes('best-checkpoint.pt'))
    expect(bestFile?.findAll('td')[4].text()).toBe('1')
    expect(wrapper.getComponent(TrainingMetricsCharts).props('bestEpoch')).toBe(1)
    expect(wrapper.findAllComponents(ButtonLink).find(link => link.text() === '创建评估')?.props('to')).toEqual({
      path: '/models',
      query: { tab: 'evaluation', evaluation: 'classification', evaluationFrom: 'classifier-output-version', datasetFrom: 'dataset-export-1' },
    })
    await trainFile.get('button').trigger('click')
    await flushPromises()
    const preview = document.querySelector('[role="dialog"]')
    expect(preview?.textContent).toContain('train-metrics.json')
    expect(preview?.textContent).toContain('small_loss1.3e-5')
    expect(preview?.textContent).toContain('原始 JSON')
    expect(wrapper.text()).toContain('Learning rate0.0003')
    expect(wrapper.text()).toContain('20 ms')
    const metrics = wrapper.get('[aria-labelledby="training-metrics-title"]')
    expect(metrics.text()).toContain('Top-1 Accuracy0.66')
    expect(metrics.text()).not.toContain('metrics/accuracy_top1')
    expect(metrics.text()).not.toContain('epoch_index')
    expect(wrapper.get('.training-more').text()).not.toContain('dataset-export-1')
    expect(wrapper.text()).toContain('train-metrics')
    expect(wrapper.text()).toContain('runtime-metrics')
    expect(trainingTelemetryStreamMock.start).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('此旧任务未保存运行时遥测')

    const testFile = wrapper.findAll('.training-output-layout tbody tr')
      .find(row => row.text().includes('test-metrics.json'))!
    expect(testFile.findAll('td')[4].text()).toBe('—')
    vi.mocked(getModelTrainingOutputFileDetail).mockResolvedValueOnce({
      file_name: 'test-metrics',
      file_kind: 'json',
      file_status: 'ready',
      task_state: 'succeeded',
      object_key: 'task-runs/task-classification-1/output-files/test-metrics.json',
      epoch: null,
      checkpoint_role: 'best',
      payload: { available: false, metrics: {} },
      text_content: null,
      lines: [],
    })
    await testFile.get('button').trigger('click')
    await flushPromises()
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('没有可用的独立测试结果。')
  })

  it('separates completed epoch metrics from volatile batch metrics', async () => {
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue({
      task_id: 'task-classification-1',
      task_type: 'classification',
      model_type: 'yolo11',
      display_name: 'completed yolo11 classifier',
      project_id: 'project-1',
      created_at: '2026-07-10T02:00:00Z',
      state: 'succeeded',
      current_attempt_no: 1,
      progress: {
        stage: 'running',
        granularity: 'batch',
        epoch: 3,
        max_epochs: 4,
        percent: 75,
        train_metrics: { loss: 9.9 },
        batch_metrics: { loss: 2.75, box_loss: 0 },
      },
      result: {},
      metadata: {},
      dataset_export_id: 'dataset-export-1',
      model_version_id: null,
      latest_checkpoint_model_version_id: null,
      output_object_prefix: 'task-runs/task-classification-1',
      checkpoint_object_key: null,
      latest_checkpoint_object_key: null,
      labels_object_key: null,
      metrics_object_key: 'task-runs/task-classification-1/output-files/train-metrics.json',
      validation_metrics_object_key: null,
      summary_object_key: null,
      best_metric_name: null,
      best_metric_value: null,
      training_summary: {},
      available_actions: [],
      control_status: {
        status: 'idle',
        pending_action: null,
        resume_count: 0,
        resume_checkpoint_object_key: null,
      },
      task_spec: {},
      events: [],
    })
    vi.mocked(listModelTrainingOutputFiles).mockResolvedValue([{
      file_name: 'train-metrics',
      file_kind: 'json',
      file_status: 'ready',
        task_state: 'succeeded',
      object_key: 'task-runs/task-classification-1/output-files/train-metrics.json',
      size_bytes: 128,
      updated_at: '2026-07-10T02:01:00Z',
    }])
    vi.mocked(getModelTrainingOutputFileDetail).mockResolvedValue({
      file_name: 'train-metrics',
      file_kind: 'json',
      file_status: 'ready',
        task_state: 'succeeded',
      object_key: 'task-runs/task-classification-1/output-files/train-metrics.json',
      size_bytes: 128,
      updated_at: '2026-07-10T02:01:00Z',
      payload: { final_metrics: { epoch: 2, loss: 1.25 } },
      text_content: null,
      lines: [],
    })

    const wrapper = mount(TrainingTaskDetailPage, { global: { plugins: [i18n] } })
    await flushPromises()

    expect(wrapper.text()).toContain('已完成轮次训练指标')
    expect(wrapper.text()).toContain('完整轮次的样本加权平均')
    expect(wrapper.text()).not.toContain('总 loss 是带权训练目标')
    expect(wrapper.text()).toContain('当前批次指标')
    expect(wrapper.text()).toContain('1.25')
    expect(wrapper.text()).toContain('2.75')
    expect(wrapper.text()).not.toContain('9.9')
    expect(wrapper.text()).toContain('此旧任务未保存运行时遥测')
  })

  it('applies batch telemetry and refreshes output files at the next epoch boundary', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue({
      task_id: 'task-classification-1',
      task_type: 'classification',
      model_type: 'yolo11',
      display_name: 'live classifier',
      project_id: 'project-1',
      created_at: '2026-07-10T02:00:00Z',
      state: 'running',
      current_attempt_no: 1,
      progress: { stage: 'running', epoch: 1, max_epochs: 4, percent: 25 },
      result: {},
      metadata: {},
      best_metric_name: null,
      best_metric_value: null,
      training_summary: {},
      available_actions: [],
      control_status: { status: 'idle', resume_count: 0 },
      task_spec: {},
      events: [],
    })
    const pendingMetricsFile = {
      file_name: 'train-metrics',
      file_kind: 'json' as const,
      file_status: 'pending',
      task_state: 'running',
      object_key: 'task-runs/task-classification-1/output-files/train-metrics.json',
      size_bytes: null,
      updated_at: null,
    }
    vi.mocked(listModelTrainingOutputFiles)
      .mockResolvedValueOnce([pendingMetricsFile])
      .mockResolvedValue([{
        ...pendingMetricsFile,
        file_status: 'ready',
        size_bytes: 256,
        updated_at: '2026-07-10T02:02:00Z',
      }])
    vi.mocked(getModelTrainingOutputFileDetail).mockResolvedValue({
      ...pendingMetricsFile,
      file_status: 'ready',
      size_bytes: 256,
      updated_at: '2026-07-10T02:02:00Z',
      payload: { final_metrics: { loss: 0.875 } },
      text_content: null,
      lines: [],
    })

    const wrapper = mount(TrainingTaskDetailPage, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(taskEventStreamMock.start).toHaveBeenCalled()
    expect(trainingTelemetryStreamMock.start).toHaveBeenCalled()

    const batch = {
      protocol: 'training.telemetry.v1',
      task_id: 'task-classification-1',
      attempt_no: 1,
      sequence: 3,
      timestamp: '2026-07-10T02:01:00Z',
      task_type: 'classification',
      model_type: 'yolo11',
      stage: 'training',
      granularity: 'batch',
      epoch: 3,
      epoch_index: 2,
      max_epochs: 4,
      step: 8,
      steps_per_epoch: 12,
      global_step: 32,
      total_steps: 48,
      progress_percent: 68,
      learning_rate: 0.0005,
      metrics: { loss: 0.875 },
      runtime: {
        batch_size: 8,
        samples_per_second: 42.5,
        step_time_ms: 188.2,
        gpu_utilization_percent: 73,
        gpu_memory_allocated_bytes: 2147483648,
      },
    }
    trainingTelemetryStreamMock.handler?.(batch)
    await flushPromises()

    expect(wrapper.text()).toContain('3 / 4')
    const progressBar = () => wrapper.get('.training-overview-progress [role="progressbar"]').attributes('aria-valuenow')
    expect(progressBar()).toBe('50')
    expect(wrapper.text()).toContain('0.875')
    expect(wrapper.text()).toContain('训练运行时')
    expect(wrapper.text()).toContain('42.5')
    expect(wrapper.text()).toContain('73%')
    expect(wrapper.text()).toContain('2.000 GiB')
    expect(getModelTrainingTaskDetail).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()
    expect(listModelTrainingOutputFiles).toHaveBeenCalledTimes(2)
    const download = wrapper.findAll('.training-output-layout tbody button').find(button => button.text() === '下载')
    expect(download?.exists()).toBe(true)
    expect(download?.attributes('disabled')).toBeUndefined()

    // 完整轮次晚于下一轮首批到达时，进度和轨道保持同一口径。
    taskEventStreamMock.handler?.({
      event_id: 'event-epoch-2', task_id: batch.task_id, event_type: 'progress', created_at: batch.timestamp,
      payload: { attempt_no: 1, progress: { epoch: 2, percent: 45, train_metrics: { loss: 0.8 } } },
    })
    await flushPromises()
    expect(progressBar()).toBe('50')
    await wrapper.findAll('button').find(button => button.text() === '刷新')!.trigger('click')
    await flushPromises()
    expect(progressBar()).toBe('50')

    taskEventStreamMock.handler?.({
      event_id: 'event-epoch-4', task_id: batch.task_id, event_type: 'progress', created_at: batch.timestamp,
      payload: { attempt_no: 1, progress: { epoch: 4, percent: 90, train_metrics: { loss: 0.3 } } },
    })
    await flushPromises()
    expect(progressBar()).toBe('100')
    expect(wrapper.get('.training-progress-eta').text()).toContain('正在整理产物')

    trainingTelemetryStreamMock.handler?.({ ...batch, attempt_no: 2, epoch: 1, epoch_index: 0, global_step: 1 })
    await flushPromises()
    expect(progressBar()).toBe('0')

    trainingTelemetryStreamMock.handler?.(batch)
    await flushPromises()
    expect(progressBar()).toBe('0')
  }, 10_000)

  it('applies completed epoch metrics from task events over an older output snapshot', async () => {
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue({
      task_id: 'task-classification-1',
      task_type: 'classification',
      model_type: 'yolo11',
      display_name: 'live classifier',
      project_id: 'project-1',
      created_at: '2026-07-10T02:00:00Z',
      state: 'running',
      current_attempt_no: 1,
      progress: { stage: 'running', epoch: 1, max_epochs: 4, percent: 25 },
      result: {},
      metadata: {},
      best_metric_name: null,
      best_metric_value: null,
      training_summary: {},
      available_actions: [],
      control_status: { status: 'idle', resume_count: 0 },
      task_spec: {},
      events: [],
    })
    vi.mocked(listModelTrainingOutputFiles).mockResolvedValue([{
      file_name: 'train-metrics',
      file_kind: 'json',
      file_status: 'ready',
      task_state: 'running',
      object_key: 'task-runs/task-classification-1/output-files/train-metrics.json',
      size_bytes: 128,
      updated_at: '2026-07-10T02:01:00Z',
    }])
    vi.mocked(getModelTrainingOutputFileDetail).mockResolvedValue({
      file_name: 'train-metrics',
      file_kind: 'json',
      file_status: 'ready',
      task_state: 'running',
      object_key: 'task-runs/task-classification-1/output-files/train-metrics.json',
      size_bytes: 128,
      updated_at: '2026-07-10T02:01:00Z',
      payload: { epoch: 1, final_metrics: { loss: 1.25 } },
      text_content: null,
      lines: [],
    })

    const wrapper = mount(TrainingTaskDetailPage, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('1.25')

    trainingTelemetryStreamMock.handler?.({
      protocol: 'training.telemetry.v1',
      task_id: 'task-classification-1',
      attempt_no: 1,
      sequence: 3,
      timestamp: '2026-07-10T02:01:59Z',
      task_type: 'classification',
      model_type: 'yolo11',
      stage: 'training',
      granularity: 'batch',
      epoch: 3,
      epoch_index: 2,
      max_epochs: 4,
      step: 1,
      steps_per_epoch: 12,
      global_step: 25,
      total_steps: 48,
      progress_percent: 52,
      learning_rate: 0.0005,
      metrics: { loss: 0.625 },
      runtime: {},
    })
    taskEventStreamMock.handler?.({
      event_id: 'event-epoch-2',
      task_id: 'task-classification-1',
      event_type: 'progress',
      created_at: '2026-07-10T02:02:00Z',
      message: 'epoch 2/4',
      payload: {
        attempt_no: 1,
        state: 'running',
        progress: {
          epoch: 2,
          epoch_index: 1,
          max_epochs: 4,
          train_metrics: { loss: 0.5, accuracy: 0.75 },
        },
      },
    })
    await flushPromises()

    const completedMetricsPanel = wrapper.findAll('.training-metric-panel').find(
      (panel) => panel.text().includes('已完成轮次训练指标'),
    )
    expect(completedMetricsPanel).toBeDefined()
    expect(wrapper.text()).toContain('0.5')
    expect(wrapper.text()).toContain('0.75')
    expect(wrapper.text()).toContain('3 / 4')
    expect(completedMetricsPanel?.text()).not.toContain('1.25')
    expect(getModelTrainingTaskDetail).toHaveBeenCalledTimes(1)
  })
})
