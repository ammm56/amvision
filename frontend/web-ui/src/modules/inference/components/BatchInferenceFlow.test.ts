import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import {
  getDatasetImage,
  listDatasetCatalog,
  listDatasetSamples,
  listDatasetVersionPage,
} from '@/modules/datasets/services/dataset-workspace.service'
import {
  runTaskDeploymentStatusAction,
  type TaskDeploymentInstance,
} from '@/modules/deployments/services/deployment.service'
import {
  createBatchInferenceTask,
  fetchBatchInferenceTaskItemImageBlob,
  getBatchInferenceTask,
  getBatchInferenceTaskItemResult,
  listBatchInferenceTaskItems,
} from '../services/inference.service'
import BatchInferenceCreateView from './BatchInferenceCreateView.vue'
import BatchInferenceDetailView from './BatchInferenceDetailView.vue'

vi.mock('@/modules/deployments/services/deployment.service', () => ({
  runTaskDeploymentStatusAction: vi.fn(),
}))

vi.mock('@/modules/datasets/services/dataset-workspace.service', () => ({
  listDatasetCatalog: vi.fn(),
  listDatasetVersionPage: vi.fn(),
  listDatasetSamples: vi.fn(),
  getDatasetImage: vi.fn(),
}))

vi.mock('../services/inference.service', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/inference.service')>()
  return {
    ...actual,
    createBatchInferenceTask: vi.fn(),
    getBatchInferenceTask: vi.fn(),
    listBatchInferenceTaskItems: vi.fn(),
    getBatchInferenceTaskItemResult: vi.fn(),
    fetchBatchInferenceTaskItemImageBlob: vi.fn(),
  }
})

const deployments: TaskDeploymentInstance[] = [
  {
    deployment_instance_id: 'deploy-async-1',
    project_id: 'project-1',
    display_name: '异步主线部署',
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

describe('BatchInferenceCreateView & BatchInferenceDetailView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getDatasetImage).mockResolvedValue(new Blob(['img'], { type: 'image/png' }))
    const version = {
      dataset_version_id: 'ver-1',
      dataset_id: 'ds-1',
      project_id: 'project-1',
      version_number: 1,
      display_name: 'v1',
      task_type: 'detection',
      sample_count: 2,
      category_count: 1,
      object_count: 2,
      split_counts: { val: 2 },
      created_at: '2026-11-27T00:00:00Z',
      metadata: {},
    }
    vi.mocked(listDatasetCatalog).mockResolvedValue({
      items: [
        {
          dataset_id: 'ds-1',
          project_id: 'project-1',
          display_name: '产线样本',
          description: '',
          task_type: 'detection',
          created_at: '2026-11-27T00:00:00Z',
          updated_at: '2026-11-27T00:00:00Z',
          revision: 'r1',
          latest_version: version,
        },
      ],
      total: 1,
      offset: 0,
      limit: 100,
    })
    vi.mocked(listDatasetVersionPage).mockResolvedValue({
      items: [version],
      total: 1,
      offset: 0,
      limit: 50,
    })
    vi.mocked(listDatasetSamples).mockResolvedValue({
      items: [
        {
          sample_id: 's1',
          dataset_version_id: 'ver-1',
          image_id: 1,
          file_name: 'part_1.jpg',
          split: 'val',
          width: 640,
          height: 480,
          annotations: [],
          metadata: {},
        },
      ],
      total: 2,
      offset: 0,
      limit: 20,
    })
  })

  it('blocks batch submission when async channel is stopped and submits when running', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/deployments', component: { template: '<div />' } },
      ],
    })
    await router.push('/')
    await router.isReady()
    vi.mocked(runTaskDeploymentStatusAction).mockResolvedValue({
      deployment_instance_id: 'deploy-async-1',
      display_name: '异步主线部署',
      runtime_mode: 'async',
      desired_state: 'stopped',
      observed_state: 'stopped',
      generation: 1,
      process_state: 'stopped',
      auto_restart: false,
      restart_count: 0,
      restart_count_rollover_count: 0,
      instance_count: 1,
    })
    vi.mocked(createBatchInferenceTask).mockResolvedValue({
      batch_task_id: 'batch-new',
      project_id: 'project-1',
      task_type: 'detection',
      display_name: 'test-batch',
      deployment_instance_id: 'deploy-async-1',
      deployment_display_name: '异步主线部署',
      source_kind: 'dataset_version',
      source_summary: {},
      parameters: {},
      state: 'queued',
      total_items: 2,
      completed_items: 0,
      succeeded_items: 0,
      failed_items: 0,
      skipped_items: 0,
      output_object_prefix: 'prefix',
      created_at: '2026-11-27T01:00:00Z',
      updated_at: '2026-11-27T01:00:00Z',
    })

    const wrapper = mount(BatchInferenceCreateView, {
      props: { projectId: 'project-1', deployments },
      global: { plugins: [i18n, router] },
    })
    await flushPromises()

    await wrapper.find('[data-batch-next]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-batch-submit]').attributes('disabled')).toBeDefined()

    vi.mocked(runTaskDeploymentStatusAction).mockImplementation(async (_task, _id, mode) => ({
      deployment_instance_id: 'deploy-async-1',
      display_name: '异步主线部署',
      runtime_mode: mode,
      desired_state: mode === 'async' ? 'running' : 'stopped',
      observed_state: mode === 'async' ? 'running' : 'stopped',
      generation: 1,
      process_state: mode === 'async' ? 'running' : 'stopped',
      auto_restart: mode === 'async',
      restart_count: 0,
      restart_count_rollover_count: 0,
      instance_count: 1,
    }))
    const recheckBtn = wrapper.findAll('button').find((b) => b.text().includes('重新检查'))
    await recheckBtn?.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-batch-submit]').attributes('disabled')).toBeUndefined()

    await wrapper.find('[data-batch-submit]').trigger('click')
    await flushPromises()
    expect(createBatchInferenceTask).toHaveBeenCalledTimes(1)
    expect(createBatchInferenceTask).toHaveBeenCalledWith(
      expect.objectContaining({ runtimeMode: 'async' }),
    )
    expect(wrapper.emitted('created')).toBeTruthy()
  })

  it('auto-selects sync channel and allows submission when only sync channel is running', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/deployments', component: { template: '<div />' } },
      ],
    })
    await router.push('/')
    await router.isReady()

    vi.mocked(runTaskDeploymentStatusAction).mockImplementation(async (_task, _id, mode) => ({
      deployment_instance_id: 'deploy-async-1',
      display_name: '异步主线部署',
      runtime_mode: mode,
      desired_state: mode === 'sync' ? 'running' : 'stopped',
      observed_state: mode === 'sync' ? 'running' : 'stopped',
      generation: 1,
      process_state: mode === 'sync' ? 'running' : 'stopped',
      auto_restart: false,
      restart_count: 0,
      restart_count_rollover_count: 0,
      instance_count: 1,
    }))
    vi.mocked(createBatchInferenceTask).mockResolvedValue({
      batch_task_id: 'batch-sync-1',
      project_id: 'project-1',
      task_type: 'detection',
      display_name: 'sync-batch',
      deployment_instance_id: 'deploy-async-1',
      deployment_display_name: '异步主线部署',
      source_kind: 'dataset_version',
      source_summary: {},
      parameters: { execution_runtime_mode: 'sync' },
      state: 'queued',
      total_items: 2,
      completed_items: 0,
      succeeded_items: 0,
      failed_items: 0,
      skipped_items: 0,
      output_object_prefix: 'prefix',
      created_at: '2026-11-27T01:00:00Z',
      updated_at: '2026-11-27T01:00:00Z',
    })

    const wrapper = mount(BatchInferenceCreateView, {
      props: { projectId: 'project-1', deployments },
      global: { plugins: [i18n, router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('同步通道就绪')
    expect((wrapper.find('.inf-bc-checkbox input[type="checkbox"]').element as HTMLInputElement).checked).toBe(false)
    expect(listDatasetSamples).toHaveBeenCalledWith(
      'ds-1',
      'ver-1',
      expect.objectContaining({ offset: 0, limit: 5 }),
    )

    await wrapper.find('[data-batch-next]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('同步部署通道')
    expect(wrapper.find('[data-batch-submit]').attributes('disabled')).toBeUndefined()

    await wrapper.find('[data-batch-submit]').trigger('click')
    await flushPromises()
    expect(createBatchInferenceTask).toHaveBeenCalledWith(
      expect.objectContaining({ runtimeMode: 'sync', saveResultImage: false }),
    )
    expect(wrapper.emitted('created')).toBeTruthy()
  })

  it('opens non-modal failed-sample drawer and fullscreen prev/next navigation in BatchInferenceDetailView', async () => {
    vi.mocked(getBatchInferenceTask).mockResolvedValue({
      batch_task_id: 'batch-1',
      project_id: 'project-1',
      task_type: 'detection',
      display_name: '部分失败批量任务',
      deployment_instance_id: 'deploy-async-1',
      deployment_display_name: '异步主线部署',
      source_kind: 'project_files',
      source_summary: {},
      parameters: {},
      state: 'partial_failed',
      total_items: 2,
      completed_items: 2,
      succeeded_items: 1,
      failed_items: 1,
      skipped_items: 0,
      output_object_prefix: 'prefix',
      created_at: '2026-11-27T01:00:00Z',
      started_at: '2026-11-27T01:00:01Z',
      finished_at: '2026-11-27T01:01:00Z',
      updated_at: '2026-11-27T01:01:00Z',
    })
    vi.mocked(listBatchInferenceTaskItems).mockResolvedValue([
      {
        item_id: 'it-1',
        batch_task_id: 'batch-1',
        sequence_no: 1,
        input_label: 'ok.jpg',
        input_source_kind: 'input_file_id',
        input_file_id: 'f-1',
        has_input_image: true,
        has_preview_image: false,
        state: 'succeeded',
        item_count: 1,
        latency_ms: 12.3,
        image_width: 640,
        image_height: 480,
        finished_at: '2026-11-27T01:00:10Z',
        result_summary: {},
      },
      {
        item_id: 'it-2',
        batch_task_id: 'batch-1',
        sequence_no: 2,
        input_label: 'bad.jpg',
        input_source_kind: 'input_file_id',
        input_file_id: 'f-2',
        has_input_image: false,
        has_preview_image: false,
        state: 'failed',
        error_code: 'DECODE_ERROR',
        error_message: '图像解码失败',
        finished_at: '2026-11-27T01:00:11Z',
        result_summary: {},
      },
    ])
    vi.mocked(fetchBatchInferenceTaskItemImageBlob).mockResolvedValue(new Blob(['img'], { type: 'image/jpeg' }))
    vi.mocked(getBatchInferenceTaskItemResult).mockResolvedValue({
      file_status: 'ready',
      item_state: 'succeeded',
      payload: {
        request_id: 'r1',
        deployment_instance_id: 'deploy-async-1',
        model_version_id: 'mv1',
        image_width: 640,
        image_height: 480,
        detections: [{ bbox_xyxy: [10, 10, 50, 50], score: 0.9, class_id: 0, class_name: 'bolt' }],
        labels: ['bolt'],
      },
    })

    const wrapper = mount(BatchInferenceDetailView, {
      props: { batchTaskId: 'batch-1', deployments },
      global: { plugins: [i18n], stubs: { Teleport: true } },
    })
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === '任务信息')?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('项目文件')
    expect(wrapper.text()).not.toContain('project_files')

    await wrapper.get('[data-tab-id="logs"]').trigger('click')
    const logs = wrapper.get('[aria-label="任务日志"]')
    expect(logs.findAll('tbody tr')).toHaveLength(5)
    expect(logs.text()).toContain('批量推理完成，部分图片失败')
    await logs.get('input[type="search"]').setValue('bad.jpg')
    expect(logs.findAll('tbody tr')).toHaveLength(1)
    expect(logs.text()).toContain('bad.jpg：图像解码失败')
    expect(logs.text()).not.toContain('ok.jpg')

    await wrapper.findAll('button').find((b) => b.text() === '样本结果')?.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.text() === '查看原因')?.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-failure-drawer]').exists()).toBe(true)
    expect(wrapper.find('[data-failure-drawer]').text()).toContain('图像解码失败')

    await wrapper.findAll('button').find((b) => b.text() === '查看结果')?.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-batch-fs-next]').exists()).toBe(true)
    expect(wrapper.text()).toContain('ok.jpg')

    await wrapper.find('[data-batch-fs-next]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('bad.jpg')
    expect(wrapper.text()).toContain('推理失败')
  })
})
