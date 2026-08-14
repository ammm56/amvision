import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import TrainingTaskDetailPage from './TrainingTaskDetailPage.vue'
import {
  getModelTrainingOutputFileDetail,
  getModelTrainingTaskDetail,
  listModelTrainingOutputFiles,
} from '../services/model.service'

const taskEventStreamMock = vi.hoisted(() => ({
  handler: null as ((event: Record<string, unknown>) => void) | null,
  start: vi.fn(),
}))

const trainingTelemetryStreamMock = vi.hoisted(() => ({
  handler: null as ((payload: Record<string, unknown>) => void) | null,
  start: vi.fn(),
}))

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
  getModelTrainingOutputFileDetail: vi.fn(),
  getModelTrainingTaskDetail: vi.fn(),
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
        validation_metrics: {
          epoch: 1,
          top1_accuracy: 0.66,
          top5_accuracy: 1,
        },
      },
      result: {},
      metadata: {},
      dataset_export_id: 'dataset-export-1',
      model_version_id: null,
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
        : {
            file_name: 'train-metrics',
            file_kind: 'json',
            file_status: 'ready',
            task_state: 'running',
            object_key: 'task-runs/task-classification-1/output-files/train-metrics.json',
            size_bytes: 128,
            updated_at: '2026-07-10T02:01:00Z',
            payload: { final_metrics: { loss: 0.1234567, accuracy: 0.875 } },
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
    )
    expect(getModelTrainingOutputFileDetail).toHaveBeenCalledWith(
      'classification',
      'task-classification-1',
      'train-metrics',
    )
    expect(getModelTrainingOutputFileDetail).toHaveBeenCalledWith(
      'classification',
      'task-classification-1',
      'runtime-metrics',
    )
    expect(wrapper.text()).toContain('训练进度')
    expect(wrapper.text()).toContain('75.0%')
    expect(wrapper.text()).toContain('2 / 4')
    expect(wrapper.text()).toContain('loss')
    expect(wrapper.text()).toContain('0.123457')
    expect(wrapper.text()).toContain('top1_accuracy')
    expect(wrapper.text()).toContain('train-metrics')
    expect(wrapper.text()).toContain('runtime-metrics')
    expect(trainingTelemetryStreamMock.start).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('此旧任务未保存运行时遥测')
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

    trainingTelemetryStreamMock.handler?.({
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
    })
    await flushPromises()

    expect(wrapper.text()).toContain('3 / 4')
    expect(wrapper.text()).toContain('68.0%')
    expect(wrapper.text()).toContain('0.875')
    expect(wrapper.text()).toContain('训练运行时')
    expect(wrapper.text()).toContain('42.5')
    expect(wrapper.text()).toContain('73%')
    expect(wrapper.text()).toContain('2.000 GiB')
    expect(getModelTrainingTaskDetail).toHaveBeenCalledTimes(1)
    await new Promise((resolve) => window.setTimeout(resolve, 350))
    await flushPromises()
    expect(listModelTrainingOutputFiles).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('ready')
  })

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
