import { translate } from '@/platform/i18n'
import { apiRequest } from '@/shared/api/http-client'

export interface TransferOptions {
  display_name?: string
  device_name?: string
  instance_count?: number
  runtime_configuration?: Record<string, unknown>
  create_copy?: boolean
  analysis_revision?: string
  idempotency_key?: string
}
export interface DeploymentTransfer {
  operation_id: string
  direction: 'import' | 'export'
  state: string
  display_name?: string
  error?: string
  analysis_revision?: string
  deployment_id?: string
  mapping?: Record<string, string>
  progress_bytes?: number
  total_bytes?: number
  summary?: {
    model: { model_name: string; task_type: string; model_type: string }
    deployment: { display_name: string; runtime_backend: string; device_name: string }
    inference: { runtime_precision: string; input_size: { width: number; height: number } }
    category_count: number
  }
  plan?: {
    mapping: Record<string, string>
    original: Record<string, string>
    reused: string[]
    issues: { code: string; reason: string; blocking: boolean }[]
    can_import: boolean
    display_name: string
    device_name: string
    runtime_configuration: Record<string, unknown>
  }
}
const base = (project: string) => `/projects/${encodeURIComponent(project)}/model-deployment-transfers`
export interface DeploymentDeletionPreview {
  revision: string
  deleted_models: { kind: string; resource_id: string }[]
  retained_models: { kind: string; resource_id: string; reason: string }[]
}
export const previewDeploymentDeletion = (project: string, id: string) => apiRequest<DeploymentDeletionPreview>(`${base(project)}/deployment/${encodeURIComponent(id)}/deletion-preview`)
export const listTransfers = (project: string) => apiRequest<DeploymentTransfer[]>(base(project))
export const exportDeployment = (project: string, id: string) => apiRequest<DeploymentTransfer>(`${base(project)}/exports`, { method: 'POST', body: { deployment_instance_id: id } })
export function uploadDeployment(project: string, file: File, signal?: AbortSignal) {
  const body = new FormData()
  body.append('file', file)
  return apiRequest<DeploymentTransfer>(`${base(project)}/imports`, { method: 'POST', body, signal })
}
export const changeTransfer = (project: string, id: string, action: 'analyze' | 'commit', options: TransferOptions) => apiRequest<DeploymentTransfer>(`${base(project)}/imports/${encodeURIComponent(id)}/${action}`, { method: 'POST', body: options })
export const cancelTransfer = (project: string, id: string) => apiRequest<DeploymentTransfer>(`${base(project)}/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
export const dismissTransfer = (project: string, id: string) => apiRequest<void>(`${base(project)}/${encodeURIComponent(id)}/dismiss`, { method: 'POST' })
export async function downloadTransfer(project: string, item: DeploymentTransfer) {
  const blob = await apiRequest<Blob>(`${base(project)}/exports/${encodeURIComponent(item.operation_id)}/download`, { responseType: 'blob' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${item.display_name || 'model'}.amvision-deployment.zip`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
export const transferIsActive = (state: string) => ['uploading', 'pending_export', 'exporting', 'pending_analysis', 'analyzing', 'pending_import', 'importing'].includes(state)
export const transferStateLabel = (state: string) => translate(`deploymentTransfer.${state}`)
