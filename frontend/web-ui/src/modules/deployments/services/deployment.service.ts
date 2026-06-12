import { apiRequest } from '@/shared/api/http-client'

export type ModelTaskType = 'detection' | 'classification' | 'segmentation' | 'pose' | 'obb'

export interface TaskDeploymentInstance {
  deployment_instance_id: string
  project_id: string
  display_name: string
  status: string
  model_id: string
  model_version_id: string
  model_build_id?: string | null
  model_name: string
  model_scale: string
  task_type: string
  source_kind: string
  runtime_profile_id?: string | null
  runtime_backend: string
  device_name: string
  runtime_precision: string
  runtime_execution_mode: string
  instance_count: number
  input_size: [number, number]
  labels: string[]
  created_at: string
  updated_at: string
  created_by?: string | null
  metadata: Record<string, unknown>
}

export interface TaskDeploymentCreateInput {
  taskType: ModelTaskType
  projectId: string
  modelType: string
  modelVersionId?: string
  modelBuildId?: string
  runtimeProfileId?: string
  runtimeBackend?: string
  runtimePrecision?: string
  deviceName?: string
  instanceCount: number
  displayName?: string
}

export interface TaskDeploymentProcessStatus {
  deployment_instance_id: string
  display_name: string
  runtime_mode: string
  desired_state: string
  process_state: string
  process_id?: number | null
  auto_restart: boolean
  restart_count: number
  restart_count_rollover_count: number
  last_exit_code?: number | null
  last_error?: string | null
  instance_count: number
}

export interface TaskDeploymentRuntimeHealth extends TaskDeploymentProcessStatus {
  healthy_instance_count: number
  warmed_instance_count: number
  pinned_output_total_bytes: number
  instances: Array<{ instance_id: string; healthy: boolean; warmed: boolean; busy: boolean; last_error?: string | null }>
  keep_warm: Record<string, unknown>
  local_buffer_broker: Record<string, unknown>
}

export interface TaskDeploymentProcessEvent {
  deployment_instance_id: string
  runtime_mode: string
  sequence: number
  event_type: string
  created_at: string
  message: string
  payload: Record<string, unknown>
}

export type DeploymentRuntimeMode = 'sync' | 'async'
export type DeploymentStatusAction = 'start' | 'status' | 'stop'
export type DeploymentHealthAction = 'warmup' | 'health' | 'reset'

function buildDeploymentPath(taskType: ModelTaskType, suffix = ''): string {
  return `/models/${taskType}/deployment-instances${suffix}`
}

export async function listTaskDeployments(taskType: ModelTaskType, projectId: string): Promise<TaskDeploymentInstance[]> {
  return apiRequest<TaskDeploymentInstance[]>(buildDeploymentPath(taskType), {
    query: { project_id: projectId, limit: 100 },
  })
}

export async function createTaskDeployment(input: TaskDeploymentCreateInput): Promise<TaskDeploymentInstance> {
  return apiRequest<TaskDeploymentInstance>(buildDeploymentPath(input.taskType), {
    method: 'POST',
    body: {
      project_id: input.projectId,
      model_type: input.modelType,
      model_version_id: input.modelVersionId || null,
      model_build_id: input.modelBuildId || null,
      runtime_profile_id: input.runtimeProfileId || null,
      runtime_backend: input.runtimeBackend || null,
      runtime_precision: input.runtimePrecision || null,
      device_name: input.deviceName || null,
      instance_count: input.instanceCount,
      display_name: input.displayName ?? '',
      metadata: {},
    },
  })
}

export async function runTaskDeploymentStatusAction(
  taskType: ModelTaskType,
  deploymentInstanceId: string,
  mode: DeploymentRuntimeMode,
  action: DeploymentStatusAction,
): Promise<TaskDeploymentProcessStatus> {
  return apiRequest<TaskDeploymentProcessStatus>(
    buildDeploymentPath(taskType, `/${encodeURIComponent(deploymentInstanceId)}/${mode}/${action}`),
    { method: action === 'status' ? 'GET' : 'POST' },
  )
}

export async function runTaskDeploymentHealthAction(
  taskType: ModelTaskType,
  deploymentInstanceId: string,
  mode: DeploymentRuntimeMode,
  action: DeploymentHealthAction,
): Promise<TaskDeploymentRuntimeHealth> {
  return apiRequest<TaskDeploymentRuntimeHealth>(
    buildDeploymentPath(taskType, `/${encodeURIComponent(deploymentInstanceId)}/${mode}/${action}`),
    { method: action === 'health' ? 'GET' : 'POST' },
  )
}

export async function listTaskDeploymentEvents(
  taskType: ModelTaskType,
  deploymentInstanceId: string,
  mode: DeploymentRuntimeMode,
): Promise<TaskDeploymentProcessEvent[]> {
  return apiRequest<TaskDeploymentProcessEvent[]>(
    buildDeploymentPath(taskType, `/${encodeURIComponent(deploymentInstanceId)}/events`),
    { query: { runtime_mode: mode, limit: 100 } },
  )
}

