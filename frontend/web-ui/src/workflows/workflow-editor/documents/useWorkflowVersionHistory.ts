import { onBeforeUnmount, ref } from 'vue'
import { listWorkflowAppVersions, getWorkflowAppVersion, renameWorkflowAppVersion, deleteWorkflowAppVersion } from '../services/workflow-application.service'
import { createWorkflowAppDocument, downloadWorkflowAppDocument, parseWorkflowAppDocumentV1, WORKFLOW_APP_DOCUMENT_FORMAT, type WorkflowAppDocumentV1 } from './workflow-app-document'
import type { WorkflowAppVersion } from '../types'

export interface WorkflowVersionHistoryOptions {
  isDocumentBusy?: () => boolean
  readTarget: () => { projectId: string; applicationId: string }
  loadDocument: (document: WorkflowAppDocumentV1, version: WorkflowAppVersion) => Promise<void>
  onVersionsChanged?: (versions: WorkflowAppVersion[]) => void
  readError: (error: unknown) => string
}

/** 版本面板统一管理请求；关闭或切换 App 后丢弃迟到响应。 */
export function useWorkflowVersionHistory(options: WorkflowVersionHistoryOptions) {
  const open = ref(false)
  const versions = ref<WorkflowAppVersion[]>([])
  const loading = ref(false)
  const selectedId = ref<string | null>(null)
  const error = ref<string | null>(null)
  const nextOffset = ref<number | null>(null)
  let generation = 0
  let loadedTargetKey: string | null = null
  const targetKey = () => JSON.stringify(options.readTarget())
  function close(): void { generation += 1; open.value = false; loading.value = false; selectedId.value = null }
  onBeforeUnmount(close)

  async function refresh(append = false): Promise<void> {
    if (loading.value) return
    const offset = append ? nextOffset.value : 0
    if (offset === null) return
    const token = ++generation
    const key = targetKey()
    const target = options.readTarget()
    loading.value = true
    error.value = null
    try {
      const response = await listWorkflowAppVersions(target.projectId, target.applicationId, { offset, limit: 25 })
      if (token !== generation || key !== targetKey()) return
      const items = [...(append ? versions.value : []), ...response.items].filter(v => ['published', 'archived'].includes(v.state))
      versions.value = [...new Map(items.map(v => [v.workflow_app_version_id, v])).values()].sort((a, b) => b.version_number - a.version_number)
      nextOffset.value = response.pagination.hasMore ? response.pagination.nextOffset : null
      loadedTargetKey = key
    } catch (cause) { if (token === generation && key === targetKey()) error.value = options.readError(cause) }
    finally { if (token === generation) loading.value = false }
  }
  async function show(): Promise<void> {
    close()
    open.value = true
    // 同一 App 切回版本栏时保留已读列表，后台刷新不会先闪成空面板。
    if (loadedTargetKey !== targetKey()) {
      versions.value = []
      nextOffset.value = null
    }
    await refresh()
  }
  async function select(version: WorkflowAppVersion): Promise<void> {
    if (loading.value || options.isDocumentBusy?.() || !open.value || !['published', 'archived'].includes(version.state)) return
    const token = ++generation
    const key = targetKey()
    const target = options.readTarget()
    loading.value = true
    selectedId.value = version.workflow_app_version_id
    error.value = null
    try {
      const detail = await getWorkflowAppVersion(target.projectId, target.applicationId, version.workflow_app_version_id)
      if (token !== generation || key !== targetKey()) return
      const document = parseWorkflowAppDocumentV1({ format_id: WORKFLOW_APP_DOCUMENT_FORMAT, application: detail.application, template: detail.template })
      await options.loadDocument(document, version)
      // 载入后保持面板可用，浏览器编辑内容已替换但尚未保存。
    } catch (cause) { if (token === generation && key === targetKey()) error.value = options.readError(cause) }
    finally { if (token === generation) { loading.value = false; selectedId.value = null } }
  }
  async function act(version: WorkflowAppVersion, action: 'rename' | 'export' | 'delete', name = '', releaseNotes?: string): Promise<boolean> {
    if (loading.value || options.isDocumentBusy?.() || !open.value) return false
    const token = ++generation
    const key = targetKey()
    const target = options.readTarget()
    const current = () => token === generation && key === targetKey()
    loading.value = true
    error.value = null
    try {
      if (action === 'export') {
        const detail = await getWorkflowAppVersion(target.projectId, target.applicationId, version.workflow_app_version_id)
        if (!current()) return false
        const source = parseWorkflowAppDocumentV1({ format_id: WORKFLOW_APP_DOCUMENT_FORMAT, application: detail.application, template: detail.template })
        downloadWorkflowAppDocument(createWorkflowAppDocument(source.application, source.template))
      } else if (action === 'rename') {
        const updated = await renameWorkflowAppVersion(target.projectId, target.applicationId, version.workflow_app_version_id, name.trim(), releaseNotes)
        if (!current()) return false
        versions.value = versions.value.map(item => item.workflow_app_version_id === updated.workflow_app_version_id ? updated : item)
        options.onVersionsChanged?.(versions.value)
      } else {
        await deleteWorkflowAppVersion(target.projectId, target.applicationId, version.workflow_app_version_id)
        if (!current()) return false
        versions.value = versions.value.filter(item => item.workflow_app_version_id !== version.workflow_app_version_id)
        options.onVersionsChanged?.(versions.value)
        // 删除后从第一页重新读取，避免 offset 因记录移除而跳过下一页。
        loading.value = false
        await refresh()
        if (key !== targetKey() || !open.value) return false
        options.onVersionsChanged?.(versions.value)
      }
      return true
    } catch (cause) { if (current()) error.value = options.readError(cause); return false }
    finally { if (current()) loading.value = false }
  }
  return { act, open, versions, loading, selectedId, error, nextOffset, show, close, refresh, select }
}
