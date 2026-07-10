import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import TrainingTaskDetailPage from './TrainingTaskDetailPage.vue'
import {
  getModelTrainingOutputFileDetail,
  getModelTrainingTaskDetail,
  listModelTrainingOutputFiles,
} from '../services/model.service'

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

describe('TrainingTaskDetailPage', () => {
  it('renders non-detection progress, metrics, and output files', async () => {
    vi.mocked(getModelTrainingTaskDetail).mockResolvedValue({
      task_id: 'task-classification-1',
      task_type: 'classification',
      model_type: 'yolo11',
      display_name: 'yolo11 classifier',
      project_id: 'project-1',
      created_at: '2026-07-10T02:00:00Z',
      state: 'running',
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
    ])
    vi.mocked(getModelTrainingOutputFileDetail).mockResolvedValue({
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
    })

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
    expect(wrapper.text()).toContain('训练进度')
    expect(wrapper.text()).toContain('75.0%')
    expect(wrapper.text()).toContain('2 / 4')
    expect(wrapper.text()).toContain('loss')
    expect(wrapper.text()).toContain('0.123457')
    expect(wrapper.text()).toContain('top1_accuracy')
    expect(wrapper.text()).toContain('train-metrics')
  })
})
