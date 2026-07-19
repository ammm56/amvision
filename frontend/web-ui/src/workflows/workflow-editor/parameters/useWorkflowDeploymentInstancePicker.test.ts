import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { TaskDeploymentInstance } from '@/modules/deployments/services/deployment.service'
import type { WorkflowDeploymentPickerNodeView } from './useWorkflowDeploymentInstancePicker'

const { listTaskDeployments } = vi.hoisted(() => ({
  listTaskDeployments: vi.fn(),
}))

vi.mock('@/modules/deployments/services/deployment.service', () => ({
  listTaskDeployments,
}))

import {
  readModelInferenceTaskType,
  useWorkflowDeploymentInstancePicker,
} from './useWorkflowDeploymentInstancePicker'

function createNode(capabilityTags: string[], deploymentInstanceId = ''): WorkflowDeploymentPickerNodeView {
  return {
    node: {
      node_id: 'node-1',
      node_type_id: 'core.model.test',
      parameters: { deployment_instance_id: deploymentInstanceId },
      enabled: true,
      ui_state: {},
      metadata: {},
    },
    definition: {
      category: 'model.inference',
      capability_tags: capabilityTags,
    } as WorkflowDeploymentPickerNodeView['definition'],
  }
}

function createDeployment(
  deploymentInstanceId: string,
  status: string,
  updatedAt: string,
): TaskDeploymentInstance {
  return {
    deployment_instance_id: deploymentInstanceId,
    project_id: 'project-1',
    display_name: `实例 ${deploymentInstanceId}`,
    status,
    model_id: 'model-1',
    model_version_id: 'model-version-1',
    model_build_id: 'model-build-1',
    model_name: 'yolo11',
    model_scale: 'm',
    task_type: 'classification',
    source_kind: 'model-build',
    runtime_profile_id: null,
    runtime_backend: 'openvino',
    device_name: 'cpu',
    runtime_precision: 'fp32',
    runtime_execution_mode: 'sync',
    instance_count: 1,
    input_size: [640, 640],
    labels: ['ok', 'ng'],
    created_at: '2026-07-18T00:00:00Z',
    updated_at: updatedAt,
    metadata: {},
  }
}

describe('readModelInferenceTaskType', () => {
  it.each([
    [['detection'], 'detection'],
    [['classification'], 'classification'],
    [['segmentation'], 'segmentation'],
    [['pose'], 'pose'],
    [['obb'], 'obb'],
    [['detection.sahi'], 'detection'],
  ] as const)('resolves %j as %s', (tags, expected) => {
    expect(readModelInferenceTaskType(createNode([...tags]))).toBe(expected)
  })

  it('does not turn unrelated nodes into deployment pickers', () => {
    const node = createNode(['classification'])
    node.definition = { ...node.definition!, category: 'logic.transform' }

    expect(readModelInferenceTaskType(node)).toBeNull()
  })
})

describe('useWorkflowDeploymentInstancePicker', () => {
  beforeEach(() => {
    listTaskDeployments.mockReset()
  })

  it('loads only the node task type, preserves a valid configured id, and writes the explicit selection', async () => {
    const stopped = createDeployment('deployment-stopped', 'stopped', '2026-07-18T12:00:00Z')
    const running = createDeployment('deployment-running', 'running', '2026-07-19T12:00:00Z')
    listTaskDeployments.mockResolvedValue([stopped, running])
    const node = createNode(['classification'], stopped.deployment_instance_id)
    const statusMessages: Array<string | null> = []
    const picker = useWorkflowDeploymentInstancePicker({
      selectedProjectId: ref('project-1'),
      readNodeTitle: () => 'Classification',
      setStatusMessage: (message) => statusMessages.push(message),
      setErrorMessage: () => undefined,
    })

    await picker.openForNode(node)

    expect(listTaskDeployments).toHaveBeenCalledOnce()
    expect(listTaskDeployments).toHaveBeenCalledWith('classification', 'project-1')
    expect(picker.deployments.value.map((item) => item.deployment_instance_id)).toEqual([
      running.deployment_instance_id,
      stopped.deployment_instance_id,
    ])
    expect(picker.selectedDeploymentId.value).toBe(stopped.deployment_instance_id)
    expect(picker.configuredDeploymentMissing.value).toBe(false)

    picker.selectDeployment(running.deployment_instance_id)
    picker.applySelectedDeployment()

    expect(node.node.parameters.deployment_instance_id).toBe(running.deployment_instance_id)
    expect(statusMessages.at(-1)).toContain(running.display_name)
    expect(picker.open.value).toBe(false)
  })

  it('marks a stale configured id and selects an available replacement without applying it implicitly', async () => {
    const running = createDeployment('deployment-running', 'active', '2026-07-19T12:00:00Z')
    listTaskDeployments.mockResolvedValue([running])
    const node = createNode(['classification'], 'deployment-deleted')
    const picker = useWorkflowDeploymentInstancePicker({
      selectedProjectId: ref('project-1'),
      readNodeTitle: () => 'Classification',
      setStatusMessage: () => undefined,
      setErrorMessage: () => undefined,
    })

    await picker.openForNode(node)

    expect(picker.configuredDeploymentMissing.value).toBe(true)
    expect(picker.selectedDeploymentId.value).toBe(running.deployment_instance_id)
    expect(node.node.parameters.deployment_instance_id).toBe('deployment-deleted')
  })
})
