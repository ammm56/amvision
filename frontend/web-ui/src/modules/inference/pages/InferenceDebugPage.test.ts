import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, type Pinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { i18n } from '@/platform/i18n'
import { listTaskDeployments, type TaskDeploymentInstance } from '@/modules/deployments/services/deployment.service'
import {
  inferTaskDeployment,
  listTaskInferenceTasks,
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
  instance_count: 1,
  input_size: [640, 640],
  labels: [],
  created_at: '2026-07-17T01:00:00Z',
  updated_at: '2026-07-17T01:00:00Z',
  metadata: {},
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
})
