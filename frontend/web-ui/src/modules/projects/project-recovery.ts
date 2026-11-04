import type { ProjectCatalogItem } from '@/shared/contracts'

export interface PendingDeletion {
  project: Pick<ProjectCatalogItem, 'project_id' | 'display_name'>
  operation_id: string
}
export const projectRecoveryEvent = 'amvision:project-recovery'
const deletionKey = (principal: string) => `amvision.project-deletion.${principal}`

export function readPendingDeletions(principal: string): PendingDeletion[] {
  try {
    const saved = JSON.parse(localStorage.getItem(deletionKey(principal)) || '[]')
    // 保留本轮首批实现已经保存的待确认操作，不能在升级时丢弃。
    return (Array.isArray(saved) ? saved : [saved]).filter(item =>
      typeof item?.project?.project_id === 'string' && typeof item?.operation_id === 'string')
  } catch { return [] }
}
export function savePendingDeletion(principal: string, value: PendingDeletion) {
  const entries = readPendingDeletions(principal).filter(item => item.project.project_id !== value.project.project_id)
  writePending(principal, [...entries, value])
}
export function clearPendingDeletion(principal: string, projectId: string) {
  writePending(principal, readPendingDeletions(principal).filter(item => item.project.project_id !== projectId))
}
function writePending(principal: string, entries: PendingDeletion[]) {
  try {
    if (entries.length) localStorage.setItem(deletionKey(principal), JSON.stringify(entries))
    else localStorage.removeItem(deletionKey(principal))
  } catch { /* 存储受限不改变服务端操作结果。 */ }
  window.dispatchEvent(new Event(projectRecoveryEvent))
}

export interface PendingCreation { request_id: string; display_name: string; description: string | null }
const creationKey = (principal: string) => `amvision.project-creation.${principal}`
export function readPendingCreation(principal: string): PendingCreation | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(creationKey(principal)) || 'null')
    return typeof value?.display_name === 'string' && /^[0-9a-f-]{36}$/i.test(value?.request_id || '') ? value : null
  } catch { return null }
}
export function savePendingCreation(principal: string, value: PendingCreation | null) {
  try {
    if (value) sessionStorage.setItem(creationKey(principal), JSON.stringify(value))
    else sessionStorage.removeItem(creationKey(principal))
  } catch { /* 浏览器禁用存储时仍保留当前组件内请求身份。 */ }
}
