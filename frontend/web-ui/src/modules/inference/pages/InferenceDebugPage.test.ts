import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, type Pinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { i18n } from '@/platform/i18n'
import {
  listTaskDeployments,
  type DeploymentRuntimeConfiguration,
  type TaskDeploymentInstance,
} from '@/modules/deployments/services/deployment.service'
import {
  inferTaskDeployment,
  listTaskInferenceTasks,
  type TaskInferencePayload,
} from '../services/inference.service'
import InferenceDebugPage from './InferenceDebugPage.vue'

vi.mock('@/modules/deployments/services/deployment.service', () => ({
  listTaskDeployments: vi.fn(),
}))

vi.mock('../services/inference.service', () => ({
  createTaskInferenceTask: vi.fn(),
  getTaskInferenceTaskResult: vi.fn(),
  inferTaskDeployment: vi.fn(),
  listTaskInferenceTasks: vi.fn(),
}))

function runtimeConfiguration(): DeploymentRuntimeConfiguration {
  return {
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
  }
}

const deployment: TaskDeploymentInstance = {
  deployment_instance_id: 'deployment-1',
  project_id: 'project-1',
  display_name: 'Default deployment',
  status: 'active',
  model_id: 'model-1',
  model_version_id: 'model-version-1',
  model_build_id: 'model-build-1',
  model_name: 'yolo11-m',
  model_scale: 'm',
  task_type: 'detection',
  source_kind: 'model-build',
  runtime_backend: 'openvino',
  device_name: 'cpu',
  runtime_precision: 'fp32',
  runtime_execution_mode: 'sync',
  runtime_configuration: runtimeConfiguration(),
  input_size: [640, 640],
  labels: [],
  created_at: '2026-07-17T01:00:00Z',
  updated_at: '2026-07-17T01:00:00Z',
  metadata: {},
}

function inferencePayload(requestId: string, latencyMs: number): TaskInferencePayload {
  return {
    request_id: requestId,
    deployment_instance_id: deployment.deployment_instance_id,
    model_version_id: deployment.model_version_id,
    model_build_id: deployment.model_build_id,
    input_uri: 'memory://input.jpg',
    input_source_kind: 'memory',
    score_threshold: 0.3,
    save_result_image: false,
    return_preview_image_base64: true,
    image_width: 640,
    image_height: 640,
    detection_count: 1,
    latency_ms: latencyMs,
    labels: ['part'],
    detections: [],
    runtime_session_info: {},
    preview_image_base64: null,
    result_object_key: null,
  }
}

describe('InferenceDebugPage', () => {
  let pinia: Pinia

  beforeEach(() => {
    pinia = createPinia()
    const projectStore = useProjectStore(pinia)
    const sessionStore = useSessionStore(pinia)

    projectStore.projects = [{ project_id: 'project-1', display_name: 'Project 1', description: '' }]
    projectStore.selectedProjectId = 'project-1'
    sessionStore.currentUser = {
      principal_id: 'user-1',
      principal_type: 'user',
      project_ids: ['project-1'],
      scopes: ['tasks:read', 'tasks:write'],
      username: 'tester',
      display_name: 'Tester',
      auth_provider_kind: 'local',
      auth_credential_kind: 'session',
    }
    sessionStore.accessToken = 'test-token'

    vi.mocked(listTaskDeployments).mockResolvedValue([deployment])
    vi.mocked(listTaskInferenceTasks).mockResolvedValue([])
    vi.mocked(inferTaskDeployment).mockResolvedValue({} as never)
  })

  it('submits memory transport without saving and returns a preview by default', async () => {
    const wrapper = mount(InferenceDebugPage, {
      global: {
        plugins: [pinia, i18n],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()

    expect(wrapper.findAll('input[type="checkbox"]').map((checkbox) => (checkbox.element as HTMLInputElement).checked)).toEqual([false, true])
    expect(wrapper.findAll('.ui-select__value').some((value) => value.text() === 'memory')).toBe(true)

    await wrapper.find('input[placeholder="project/files/image.jpg"]').setValue('project/files/input.jpg')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(inferTaskDeployment).toHaveBeenCalledWith(expect.objectContaining({
      inputTransportMode: 'memory',
      saveResultImage: false,
      returnPreviewImageBase64: true,
    }))
  })

  it('omits redundant section kicker labels', async () => {
    const wrapper = mount(InferenceDebugPage, {
      global: {
        plugins: [pinia, i18n],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()

    expect(wrapper.find('.page-kicker').exists()).toBe(false)
  })

  it('keeps the previous result mounted until the next inference completes', async () => {
    const firstResult = inferencePayload('request-1', 31.435)
    let resolveSecondResult!: (value: TaskInferencePayload) => void
    const secondResultPromise = new Promise<TaskInferencePayload>((resolve) => {
      resolveSecondResult = resolve
    })
    vi.mocked(inferTaskDeployment)
      .mockResolvedValueOnce(firstResult)
      .mockReturnValueOnce(secondResultPromise)

    const wrapper = mount(InferenceDebugPage, {
      global: {
        plugins: [pinia, i18n],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()

    await wrapper.find('input[placeholder="project/files/image.jpg"]').setValue('project/files/input.jpg')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const findResultSection = () => wrapper.findAll('section.resource-section')
      .find((section) => section.find('h2').text() === '同步推理结果')
    const firstResultSection = findResultSection()

    expect(firstResultSection?.text()).toContain('31.435')
    const resultElement = firstResultSection?.element

    await wrapper.find('form').trigger('submit')

    expect(findResultSection()?.element).toBe(resultElement)
    expect(findResultSection()?.text()).toContain('31.435')

    resolveSecondResult(inferencePayload('request-2', 28.125))
    await flushPromises()

    expect(findResultSection()?.element).toBe(resultElement)
    expect(findResultSection()?.text()).toContain('28.125')
  })
})
