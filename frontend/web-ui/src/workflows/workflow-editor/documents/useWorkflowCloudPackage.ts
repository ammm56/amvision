import { onScopeDispose, ref, watch } from 'vue'
import { apiRequest } from '@/shared/api/http-client'
import { readCloudCapabilities, type MeasurementResourceReference } from '../services/measurement-resource.service'
import type { WorkflowAppDocumentV1 } from './workflow-app-document'

export interface CloudPackageResult {
  application_id: string
  template_id: string
  resource_mapping: { source: MeasurementResourceReference; target: MeasurementResourceReference }[]
}

/** 只负责当前编辑上下文的传输，不替换草稿、不改变发布或运行状态。 */
export function useWorkflowCloudPackage(options: {
  context: () => string
  project: () => string | null
  onImported: (result: CloudPackageResult) => void
  onExported: (blob: Blob) => void
  onError: (error: unknown) => void
  capacityError: () => string
}) {
  const busy = ref(false)
  let active: AbortController | null = null
  let disposed = false
  function cancel() {
    active?.abort()
    active = null
    busy.value = false
  }
  watch(options.context, cancel, { flush: 'sync' })
  onScopeDispose(() => { disposed = true; cancel() })

  async function transfer(operation: (root: string, project: string, signal: AbortSignal) => Promise<() => void>) {
    const project = options.project()
    if (busy.value || disposed || !project) return
    const controller = new AbortController()
    const context = options.context()
    active = controller
    busy.value = true
    const current = () => !disposed && active === controller && !controller.signal.aborted && context === options.context()
    try {
      const complete = await operation(`/workflows/projects/${encodeURIComponent(project)}/application-packages`, project, controller.signal)
      if (current()) complete()
    } catch (error) {
      if (current()) options.onError(error)
    } finally {
      if (active === controller) { active = null; busy.value = false }
    }
  }

  function importPackage(file: File) {
    return transfer(async (root, project, signal) => {
      const { max_archive_bytes: limit } = await readCloudCapabilities(project, signal)
      signal.throwIfAborted()
      if (!limit || !file.size || file.size > limit) throw new Error(options.capacityError())
      const result = await apiRequest<CloudPackageResult>(`${root}/import`, {
        method: 'POST', body: file, signal, retryOnUnauthorized: false,
        headers: { 'Content-Type': 'application/zip', 'Idempotency-Key': crypto.randomUUID() },
      })
      return () => options.onImported(result)
    })
  }

  function exportPackage(document: WorkflowAppDocumentV1) {
    return transfer(async (root, _project, signal) => {
      const blob = await apiRequest<Blob>(`${root}/export`, {
        method: 'POST', body: document, signal, responseType: 'blob', retryOnUnauthorized: false,
      })
      return () => options.onExported(blob)
    })
  }
  return { busy, cancel, importPackage, exportPackage }
}

export function downloadCloudPackage(blob: Blob) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'workflow-cloud-package.zip'
  try { document.body.append(link); link.click() }
  finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
}
