import { apiRequest } from '@/shared/api/http-client'

export interface YoloXInferenceDetection {
  bbox_xyxy: [number, number, number, number]
  score: number
  class_id: number
  class_name?: string | null
}

export interface YoloXInferencePayload {
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
  detections: YoloXInferenceDetection[]
  runtime_session_info: Record<string, unknown>
  preview_image_uri?: string | null
  preview_image_base64?: string | null
  result_object_key?: string | null
}

export interface YoloXInferenceTaskSubmission {
  task_id: string
  status: string
  queue_name: string
  queue_task_id: string
  deployment_instance_id: string
  input_uri: string
  input_source_kind: string
}

export interface YoloXInferenceTaskSummary {
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

export interface YoloXInferenceTaskResult {
  file_status: 'pending' | 'ready'
  task_state: string
  object_key?: string | null
  payload: Record<string, unknown>
}

export interface YoloXInferenceDebugInput {
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

export interface YoloXInferenceTaskListInput {
  projectId: string
  deploymentInstanceId?: string
  limit?: number
}

function buildInferenceFormData(input: YoloXInferenceDebugInput, includeTaskFields: boolean): FormData {
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

export async function inferYoloXDeployment(input: YoloXInferenceDebugInput): Promise<YoloXInferencePayload> {
  return apiRequest<YoloXInferencePayload>(
    `/models/detection/deployment-instances/${encodeURIComponent(input.deploymentInstanceId)}/infer`,
    { method: 'POST', body: buildInferenceFormData(input, false) },
  )
}

export async function createYoloXInferenceTask(input: YoloXInferenceDebugInput): Promise<YoloXInferenceTaskSubmission> {
  return apiRequest<YoloXInferenceTaskSubmission>('/models/detection/inference-tasks', {
    method: 'POST',
    body: buildInferenceFormData(input, true),
  })
}

export async function listYoloXInferenceTasks(input: YoloXInferenceTaskListInput): Promise<YoloXInferenceTaskSummary[]> {
  return apiRequest<YoloXInferenceTaskSummary[]>('/models/detection/inference-tasks', {
    query: {
      project_id: input.projectId,
      deployment_instance_id: input.deploymentInstanceId,
      limit: input.limit ?? 20,
    },
  })
}

export async function getYoloXInferenceTaskResult(taskId: string): Promise<YoloXInferenceTaskResult> {
  return apiRequest<YoloXInferenceTaskResult>(`/models/detection/inference-tasks/${encodeURIComponent(taskId)}/result`)
}
