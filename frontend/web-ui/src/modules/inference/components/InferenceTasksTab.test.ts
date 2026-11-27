import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import type { TaskDeploymentInstance } from '@/modules/deployments/services/deployment.service'
import {
  cancelBatchInferenceTask,
  deleteDirectInferenceRecord,
  listBatchInferenceTasks,
  listDirectInferenceRecords,
  listTaskInferenceTasks,
} from '../services/inference.service'
import InferenceTasksTab from './InferenceTasksTab.vue'

vi.mock('../services/inference.service', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/inference.service')>()
  return {
    ...actual,
    listBatchInferenceTasks: vi.fn(),
    listDirectInferenceRecords: vi.fn(),
    listTaskInferenceTasks: vi.fn(),
    cancelBatchInferenceTask: vi.fn(),
    deleteBatchInferenceTask: vi.fn(),
    deleteDirectInferenceRecord: vi.fn(),
  }
})

const deployments: TaskDeploymentInstance[] = [
  {
    deployment_instance_id: 'deploy-1',
    project_id: 'project-1',
    display_name: '零件检测主线',
    status: 'active',
    model_id: 'm1',
    model_version_id: 'mv1',
    model_name: 'yolo11-s',
    model_scale: 's',
    task_type: 'detection',
    source_kind: 'model-build',
    runtime_backend: 'openvino',
    device_name: 'cpu',
    runtime_precision: 'fp32',
    runtime_execution_mode: 'async',
    runtime_configuration: {
      execution: {
        instance_count: 1,
        isolation_level: 'session',
        overflow_policy: 'reject',
        performance_goal: 'latency',
      },
      lifecycle: {
        warmup_dummy_inference_count: null,
        warmup_dummy_image_size: null,
        keep_warm_enabled: null,
        keep_warm_interval_seconds: null,
      },
      backend_options: { kind: 'default' },
    },
    input_size: { width: 640, height: 640 },
    labels: ['bolt'],
    created_at: '2026-11-27T01:00:00Z',
    updated_at: '2026-11-27T01:00:00Z',
    metadata: {},
  },
]

describe('InferenceTasksTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listBatchInferenceTasks).mockResolvedValue([
      {
        batch_task_id: 'batch-1',
        project_id: 'project-1',
        task_type: 'detection',
        display_name: '零件抽检-1023',
        deployment_instance_id: 'deploy-1',
        deployment_display_name: '零件检测主线',
        source_kind: 'dataset_version',
        source_summary: {},
        parameters: {},
        state: 'running',
        total_items: 10,
        completed_items: 4,
        succeeded_items: 4,
        failed_items: 0,
        skipped_items: 0,
        output_object_prefix: 'projects/project-1/results/batches/batch-1',
        created_at: '2026-11-27T10:00:00Z',
        updated_at: '2026-11-27T10:01:00Z',
      },
    ])
    vi.mocked(listDirectInferenceRecords).mockResolvedValue([
      {
        record_id: 'rec-1',
        project_id: 'project-1',
        request_id: 'req-1',
        task_type: 'detection',
        deployment_instance_id: 'deploy-1',
        deployment_display_name: '零件检测主线',
        input_source_kind: 'upload',
        input_label: 'sample.jpg',
        has_input_image: true,
        has_preview_image: false,
        result_object_key: 'k',
        item_count: 2,
        latency_ms: 15,
        parameters: {},
        result_summary: {},
        created_at: '2026-11-27T09:00:00Z',
      },
    ])
    vi.mocked(listTaskInferenceTasks).mockResolvedValue([])
  })

  it('merges batch and direct records and supports cancel & delete confirmations', async () => {
    vi.mocked(cancelBatchInferenceTask).mockResolvedValue({} as never)
    vi.mocked(deleteDirectInferenceRecord).mockResolvedValue()

    const wrapper = mount(InferenceTasksTab, {
      props: { projectId: 'project-1', deployments },
      global: { plugins: [i18n], stubs: { Teleport: true } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('零件抽检-1023')
    expect(wrapper.text()).toContain('sample.jpg')

    await wrapper.find('input[placeholder="搜索任务名称"]').setValue('抽检')
    expect(wrapper.text()).toContain('零件抽检-1023')
    expect(wrapper.text()).not.toContain('sample.jpg')

    await wrapper.find('button[aria-label="清空搜索"]').trigger('click')
    await wrapper.find('.inf-link-action.is-warn').trigger('click')
    expect(wrapper.text()).toContain('取消推理任务?')
    await wrapper.findAll('button').find((b) => b.text() === '确认取消')?.trigger('click')
    await flushPromises()
    expect(cancelBatchInferenceTask).toHaveBeenCalledWith('batch-1')

    await wrapper.find('.inf-link-action.is-danger').trigger('click')
    expect(wrapper.text()).toContain('删除推理记录?')
    await wrapper.findAll('button').find((b) => b.text() === '确认删除')?.trigger('click')
    await flushPromises()
    expect(deleteDirectInferenceRecord).toHaveBeenCalledWith('rec-1')
  })
})
