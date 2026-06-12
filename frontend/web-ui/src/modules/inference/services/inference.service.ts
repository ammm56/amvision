import { apiRequest } from '@/shared/api/http-client'
import type { ModelTaskType } from '@/modules/deployments/services/deployment.service'

export interface DetectionInferenceDetection {
  bbox_xyxy: [number, number, number, number]
  score: number
  class_id: number
  class_name?: string | null
}

export interface DetectionInferencePayload {
  request_id: string
  inference_task_id?: string | null
  deployment_instance_id: string
  instance_id?: string | null
  model_version_id: string
  model_build_id?: string | null
  input_uri: string
  input_source_kind: string
  input_file_id?: string | null
  score_threshold: number
  save_result_image: boolean
  return_preview_image_base64: boolean
  image_width: number
  image_height: number
  detection_count: number
  latency_ms?: number | null
  decode_ms?: number | null
  preprocess_ms?: number | null
  infer_ms?: number | null
  postprocess_ms?: number | null
  serialize_ms?: number | null
  labels: string[]
  detections: DetectionInferenceDetection[]
  runtime_session_info: Record<string, unknown>
  preview_image_uri?: string | null
  preview_image_base64?: string | null
  result_object_key?: string | null
}

export interface DetectionInferenceTaskSubmission {
  task_id: string
  status: string
  queue_name: string
  queue_task_id: string
  deployment_instance_id: string
  input_uri: string
  input_source_kind: string
}

export interface DetectionInferenceTaskSummary {
  task_id: string
  display_name: string
  project_id: string
  created_by?: string | null
  created_at: string
  worker_pool?: string | null
  state: string
  current_attempt_no: number
  started_at?: string | null
  finished_at?: string | null
  progress: Record<string, unknown>
  result: Record<string, unknown>
  error_message?: string | null
  metadata: Record<string, unknown>
  deployment_instance_id: string
  instance_id?: string | null
  model_version_id?: string | null
  model_build_id?: string | null
  input_uri?: string | null
  input_source_kind?: string | null
  input_file_id?: string | null
  score_threshold?: number | null
  save_result_image: boolean
  output_object_prefix?: string | null
  result_object_key?: string | null
  preview_image_object_key?: string | null
  detection_count?: number | null
  latency_ms?: number | null
  result_summary: Record<string, unknown>
}

export interface DetectionInferenceTaskResult {
  file_status: 'pending' | 'ready'
  task_state: string
  object_key?: string | null
  payload: Record<string, unknown>
}

export interface DetectionInferenceDebugInput {
  taskType: ModelTaskType
  projectId: string
  deploymentInstanceId: string
  inputFileId?: string
  inputUri?: string
  imageBase64?: string
  inputImage?: File | null
  inputTransportMode: 'storage' | 'memory'
  scoreThreshold?: number
  saveResultImage: boolean
  returnPreviewImageBase64: boolean
  displayName?: string
}

export interface DetectionInferenceTaskListInput {
  taskType: ModelTaskType
  projectId: string
  deploymentInstanceId?: string
  limit?: number
}

function buildInferenceTaskPath(taskType: ModelTaskType, suffix = ''): string {
  return `/models/${taskType}/inference-tasks${suffix}`
}

function buildDeploymentInferencePath(taskType: ModelTaskType, deploymentInstanceId: string): string {
  return `/models/${taskType}/deployment-instances/${encodeURIComponent(deploymentInstanceId)}/infer`
}

function buildInferenceFormData(input: DetectionInferenceDebugInput, includeTaskFields: boolean): FormData {
  const formData = new FormData()
  if (includeTaskFields) {
    formData.set('project_id', input.projectId)
    formData.set('deployment_instance_id', input.deploymentInstanceId)
    formData.set('display_name', input.displayName ?? '')
  }
  if (input.inputFileId) formData.set('input_file_id', input.inputFileId)
  if (input.inputUri) formData.set('input_uri', input.inputUri)
  if (input.imageBase64) formData.set('image_base64', input.imageBase64)
  if (input.inputImage) formData.set('input_image', input.inputImage)
  formData.set('input_transport_mode', input.inputTransportMode)
  if (typeof input.scoreThreshold === 'number') formData.set('score_threshold', String(input.scoreThreshold))
  formData.set('save_result_image', String(input.saveResultImage))
  formData.set('return_preview_image_base64', String(input.returnPreviewImageBase64))
  formData.set('extra_options', '{}')
  return formData
}

export async function inferDetectionDeployment(input: DetectionInferenceDebugInput): Promise<DetectionInferencePayload> {
  return apiRequest<DetectionInferencePayload>(
    buildDeploymentInferencePath(input.taskType, input.deploymentInstanceId),
    { method: 'POST', body: buildInferenceFormData(input, false) },
  )
}

export async function createDetectionInferenceTask(input: DetectionInferenceDebugInput): Promise<DetectionInferenceTaskSubmission> {
  return apiRequest<DetectionInferenceTaskSubmission>(buildInferenceTaskPath(input.taskType), {
    method: 'POST',
    body: buildInferenceFormData(input, true),
  })
}

export async function listDetectionInferenceTasks(input: DetectionInferenceTaskListInput): Promise<DetectionInferenceTaskSummary[]> {
  return apiRequest<DetectionInferenceTaskSummary[]>(buildInferenceTaskPath(input.taskType), {
    query: {
      project_id: input.projectId,
      deployment_instance_id: input.deploymentInstanceId,
      limit: input.limit ?? 20,
    },
  })
}

export async function getDetectionInferenceTaskResult(taskType: ModelTaskType, taskId: string): Promise<DetectionInferenceTaskResult> {
  return apiRequest<DetectionInferenceTaskResult>(buildInferenceTaskPath(taskType, `/${encodeURIComponent(taskId)}/result`))
}

