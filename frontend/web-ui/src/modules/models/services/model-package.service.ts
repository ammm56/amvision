import { apiRequest } from '@/shared/api/http-client'

export interface ModelPackageExportOptions {
  model_version_id: string
  include_checkpoint: boolean
  build_ids: string[]
  file_name: string
}

export interface ModelPackageRecord {
  operation_id: string
  direction: 'export' | 'import'
  state: string
  created_at: string
  updated_at: string
  file_name?: string
  total_bytes?: number
  upload_bytes?: number
  archive_sha256?: string
  completed_at?: string
  registered_at?: string
  uploaded_at?: string
  input_size?: { width: number; height: number }
  import_check?: { phase: 'archive' | 'model'; code: string; message: string; member?: string | null }
  file_state?: 'available' | 'cleaned' | 'missing' | 'unavailable'
  analysis_revision?: string
  error?: string
  failure_stage?: 'package_check' | 'file_write' | 'registration' | 'unknown'
  failure_code?: 'storage_full' | 'import_failed'
  can_recheck?: boolean
  import_description?: string
  source_version_id?: string
  source?: { source_version_label?: string | null }
  export_options?: ModelPackageExportOptions
  model?: { model_name: string; model_type: string; task_type: string; model_scale: string }
  categories?: string[]
  builds?: Array<{ build_format: string; runtime_precision: string }>
  files?: Array<{ path: string; owner: string; byte_size: number; sha256: string }>
  plan?: {
    name: string
    can_import: boolean
    target_model_id: string | null
    issues: Array<{ code: string; reason: string; expected?: string[]; incoming?: string[] }>
  }
  result?: { model_id: string; model_version_id: string; model_build_ids: string[] }
}

export interface ModelPackageDestination {
  target_model_id?: string
  model_name?: string
  description: string
}

function resource(project: string, suffix = ''): string {
  return `/projects/${encodeURIComponent(project)}/model-packages${suffix}`
}

export function listModelPackages(project: string): Promise<ModelPackageRecord[]> {
  return apiRequest(resource(project))
}

export function getModelPackage(project: string, id: string): Promise<ModelPackageRecord> {
  return apiRequest(resource(project, `/${encodeURIComponent(id)}`))
}

export function exportModelPackage(project: string, body: ModelPackageExportOptions): Promise<ModelPackageRecord> {
  return apiRequest(resource(project, '/exports'), { method: 'POST', body })
}

export function uploadModelPackage(project: string, file: File): Promise<ModelPackageRecord> {
  const body = new FormData()
  body.append('file', file)
  return apiRequest(resource(project, '/imports'), { method: 'POST', body })
}

export function analyzeModelPackage(project: string, id: string, body: ModelPackageDestination): Promise<ModelPackageRecord> {
  return apiRequest(resource(project, `/imports/${encodeURIComponent(id)}/analyze`), { method: 'POST', body })
}

export function importModelPackage(project: string, id: string, revision: string): Promise<ModelPackageRecord> {
  return apiRequest(resource(project, `/imports/${encodeURIComponent(id)}/commit`), {
    method: 'POST', body: { analysis_revision: revision, idempotency_key: revision },
  })
}

export function deleteModelPackageImport(project: string, id: string): Promise<void> {
  return apiRequest(resource(project, `/imports/${encodeURIComponent(id)}`), { method: 'DELETE' })
}

export async function downloadModelPackage(project: string, item: ModelPackageRecord): Promise<void> {
  const blob = await apiRequest<Blob>(resource(project, `/exports/${encodeURIComponent(item.operation_id)}/download`), {
    responseType: 'blob', retryTransientRead: false,
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = item.file_name || 'model.zip'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function packagePending(state: string): boolean {
  return ['uploading', 'pending_analysis', 'analyzing', 'pending_import', 'importing', 'pending_export', 'exporting'].includes(state)
}

export function packageStatus(state: string, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    uploading: ['上传中', 'Uploading'],
    pending_analysis: ['等待检查', 'Awaiting checks'],
    analyzing: ['检查中', 'Checking'],
    ready: ['检查通过', 'Checks passed'],
    needs_attention: ['需要处理', 'Requires attention'],
    pending_import: ['等待登记', 'Awaiting registration'],
    importing: ['登记中', 'Registering'],
    pending_export: ['等待生成', 'Awaiting generation'],
    exporting: ['生成中', 'Generating'],
    completed: ['已完成', 'Completed'],
    failed: ['失败', 'Failed'],
    cancelled: ['已取消', 'Cancelled'],
    expired: ['文件已清理', 'Files cleaned'],
  }
  return labels[state]?.[zh ? 0 : 1] ?? state
}

export function packageExportState(row: ModelPackageRecord): string {
  return row.state === 'expired' && row.archive_sha256 && row.files?.length ? 'completed' : row.state
}

export function canDownloadModelPackage(row: ModelPackageRecord): boolean {
  return row.direction === 'export' && row.state === 'completed' && (!row.file_state || row.file_state === 'available')
}

export function canRegenerateModelPackage(row: ModelPackageRecord): boolean {
  return row.direction === 'export' && !!row.export_options && (
    ['failed', 'expired'].includes(row.state) || (row.state === 'completed' && !canDownloadModelPackage(row))
  )
}

export function packageExportFileLabel(row: ModelPackageRecord, zh: boolean): string {
  if (row.file_state === 'cleaned' || row.state === 'expired') return zh ? '文件已清理' : 'File cleaned'
  if (row.file_state === 'missing') return zh ? '文件不存在' : 'File missing'
  if (row.file_state === 'unavailable') return zh ? '文件不可用' : 'File unavailable'
  return ''
}
