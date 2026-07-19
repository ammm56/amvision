import { computed, ref, shallowRef, watch, type Ref } from 'vue'

import {
  listTaskDeployments,
  type ModelTaskType,
  type TaskDeploymentInstance,
} from '@/modules/deployments/services/deployment.service'
import type { NodeDefinition, NodeParameterUiField, WorkflowGraphNode } from '../types'

export interface WorkflowDeploymentPickerNodeView {
  node: WorkflowGraphNode
  definition: NodeDefinition | null
}

export interface WorkflowDeploymentInstancePickerOptions<NodeView extends WorkflowDeploymentPickerNodeView> {
  selectedProjectId: Ref<string>
  readNodeTitle: (node: NodeView) => string
  setStatusMessage: (message: string | null) => void
  setErrorMessage: (message: string | null) => void
}

const modelTaskTypes: ModelTaskType[] = ['detection', 'classification', 'segmentation', 'pose', 'obb']

export function readModelInferenceTaskType(
  node: WorkflowDeploymentPickerNodeView,
): ModelTaskType | null {
  if (node.definition?.category !== 'model.inference') return null
  const tags = node.definition.capability_tags.map((tag) => tag.trim().toLowerCase())
  for (const taskType of modelTaskTypes) {
    if (tags.includes(taskType) || tags.some((tag) => tag.startsWith(`${taskType}.`))) {
      return taskType
    }
  }
  return null
}

export function isModelInferenceDeploymentField(
  node: WorkflowDeploymentPickerNodeView,
  field: NodeParameterUiField,
): boolean {
  return field.parameter_name === 'deployment_instance_id' && readModelInferenceTaskType(node) !== null
}

export function useWorkflowDeploymentInstancePicker<NodeView extends WorkflowDeploymentPickerNodeView>(
  options: WorkflowDeploymentInstancePickerOptions<NodeView>,
) {
  const open = ref(false)
  const loading = ref(false)
  const errorMessage = ref<string | null>(null)
  const activeNode = shallowRef<NodeView | null>(null)
  const taskType = ref<ModelTaskType | null>(null)
  const deployments = ref<TaskDeploymentInstance[]>([])
  const selectedDeploymentId = ref('')
  let requestSequence = 0

  const selectedDeployment = computed(() => deployments.value.find(
    (deployment) => deployment.deployment_instance_id === selectedDeploymentId.value,
  ) ?? null)
  const configuredDeploymentId = computed(() => readConfiguredDeploymentId(activeNode.value))
  const configuredDeploymentMissing = computed(() => Boolean(
    configuredDeploymentId.value
      && !deployments.value.some((deployment) => deployment.deployment_instance_id === configuredDeploymentId.value),
  ))

  async function openForNode(node: NodeView): Promise<void> {
    const resolvedTaskType = readModelInferenceTaskType(node)
    if (!resolvedTaskType) {
      options.setErrorMessage(`${options.readNodeTitle(node)} 无法确定模型推理任务类型`)
      return
    }
    activeNode.value = node
    taskType.value = resolvedTaskType
    selectedDeploymentId.value = readConfiguredDeploymentId(node)
    deployments.value = []
    errorMessage.value = null
    open.value = true
    await refresh()
  }

  function close(): void {
    requestSequence += 1
    open.value = false
    loading.value = false
    errorMessage.value = null
    activeNode.value = null
    taskType.value = null
    deployments.value = []
    selectedDeploymentId.value = ''
  }

  async function refresh(): Promise<void> {
    const currentTaskType = taskType.value
    const projectId = options.selectedProjectId.value.trim()
    if (!open.value || !currentTaskType) return
    if (!projectId) {
      deployments.value = []
      errorMessage.value = '当前项目 id 为空，无法读取部署实例'
      return
    }
    const currentSequence = ++requestSequence
    loading.value = true
    errorMessage.value = null
    try {
      const items = await listTaskDeployments(currentTaskType, projectId)
      if (currentSequence !== requestSequence || !open.value) return
      deployments.value = sortDeployments(items)
      const currentSelection = selectedDeploymentId.value
      if (!deployments.value.some((deployment) => deployment.deployment_instance_id === currentSelection)) {
        selectedDeploymentId.value = deployments.value[0]?.deployment_instance_id ?? ''
      }
    } catch (error) {
      if (currentSequence !== requestSequence || !open.value) return
      deployments.value = []
      errorMessage.value = error instanceof Error ? error.message : '读取部署实例失败'
    } finally {
      if (currentSequence === requestSequence) loading.value = false
    }
  }

  function selectDeployment(deploymentInstanceId: string): void {
    if (!deployments.value.some((deployment) => deployment.deployment_instance_id === deploymentInstanceId)) return
    selectedDeploymentId.value = deploymentInstanceId
  }

  function applySelectedDeployment(): void {
    const node = activeNode.value
    const deployment = selectedDeployment.value
    if (!node || !deployment) return
    node.node.parameters = {
      ...node.node.parameters,
      deployment_instance_id: deployment.deployment_instance_id,
    }
    options.setErrorMessage(null)
    options.setStatusMessage(
      `已为 ${options.readNodeTitle(node)} 选择部署实例：${deployment.display_name || deployment.deployment_instance_id}`,
    )
    close()
  }

  watch(options.selectedProjectId, () => {
    if (open.value) void refresh()
  })

  return {
    open,
    loading,
    errorMessage,
    taskType,
    deployments,
    selectedDeploymentId,
    selectedDeployment,
    configuredDeploymentId,
    configuredDeploymentMissing,
    openForNode,
    close,
    refresh,
    selectDeployment,
    applySelectedDeployment,
  }
}

function readConfiguredDeploymentId(node: WorkflowDeploymentPickerNodeView | null): string {
  const value = node?.node.parameters.deployment_instance_id
  return typeof value === 'string' ? value.trim() : ''
}

function sortDeployments(deployments: TaskDeploymentInstance[]): TaskDeploymentInstance[] {
  return [...deployments].sort((left, right) => {
    const statusOrder = deploymentStatusOrder(left.status) - deploymentStatusOrder(right.status)
    if (statusOrder !== 0) return statusOrder
    return Date.parse(right.updated_at || right.created_at) - Date.parse(left.updated_at || left.created_at)
  })
}

function deploymentStatusOrder(status: string): number {
  const normalized = status.trim().toLowerCase()
  if (normalized.includes('running') || normalized.includes('active') || normalized.includes('ready')) return 0
  if (normalized.includes('stop')) return 1
  if (normalized.includes('fail') || normalized.includes('error') || normalized.includes('crash')) return 3
  return 2
}
