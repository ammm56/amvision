import { apiRequest } from '@/shared/api/http-client'

export interface YoloXDeploymentInstance {
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

export interface YoloXDeploymentCreateInput {
  projectId: string
  modelVersionId?: string
  modelBuildId?: string
  runtimeProfileId?: string
  runtimeBackend?: string
  runtimePrecision?: string
  deviceName?: string
  instanceCount: number
  displayName?: string
}

export interface YoloXDeploymentProcessStatus {
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

export interface YoloXDeploymentRuntimeHealth extends YoloXDeploymentProcessStatus {
  healthy_instance_count: number
  warmed_instance_count: number
  pinned_output_total_bytes: number
  instances: Array<{ instance_id: string; healthy: boolean; warmed: boolean; busy: boolean; last_error?: string | null }>
  keep_warm: Record<string, unknown>
  local_buffer_broker: Record<string, unknown>
}

export interface YoloXDeploymentProcessEvent {
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

export async function listYoloXDeployments(projectId: string): Promise<YoloXDeploymentInstance[]> {
  return apiRequest<YoloXDeploymentInstance[]>('/models/detection/deployment-instances', {
    query: { project_id: projectId, limit: 100 },
  })
}

export async function createYoloXDeployment(input: YoloXDeploymentCreateInput): Promise<YoloXDeploymentInstance> {
  return apiRequest<YoloXDeploymentInstance>('/models/detection/deployment-instances', {
    method: 'POST',
    body: {
      project_id: input.projectId,
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

export async function runYoloXDeploymentStatusAction(
  deploymentInstanceId: string,
  mode: DeploymentRuntimeMode,
  action: DeploymentStatusAction,
): Promise<YoloXDeploymentProcessStatus> {
  return apiRequest<YoloXDeploymentProcessStatus>(
    `/models/detection/deployment-instances/${encodeURIComponent(deploymentInstanceId)}/${mode}/${action}`,
    { method: action === 'status' ? 'GET' : 'POST' },
  )
}

export async function runYoloXDeploymentHealthAction(
  deploymentInstanceId: string,
  mode: DeploymentRuntimeMode,
  action: DeploymentHealthAction,
): Promise<YoloXDeploymentRuntimeHealth> {
  return apiRequest<YoloXDeploymentRuntimeHealth>(
    `/models/detection/deployment-instances/${encodeURIComponent(deploymentInstanceId)}/${mode}/${action}`,
    { method: action === 'health' ? 'GET' : 'POST' },
  )
}

export async function listYoloXDeploymentEvents(
  deploymentInstanceId: string,
  mode: DeploymentRuntimeMode,
): Promise<YoloXDeploymentProcessEvent[]> {
  return apiRequest<YoloXDeploymentProcessEvent[]>(
    `/models/detection/deployment-instances/${encodeURIComponent(deploymentInstanceId)}/events`,
    { query: { runtime_mode: mode, limit: 100 } },
  )
}
