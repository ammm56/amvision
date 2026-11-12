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
export function readPendingCreations(principal: string): PendingCreation[] {
  try {
    const value = JSON.parse(sessionStorage.getItem(creationKey(principal)) || 'null')
    // 已保存的单个待确认请求也必须保留，升级不能丢失核对身份。
    return (Array.isArray(value) ? value : [value]).filter(item => typeof item?.display_name === 'string' && /^[0-9a-f-]{36}$/i.test(item?.request_id || ''))
  } catch { return [] }
}
export function savePendingCreation(principal: string, value: PendingCreation) {
  writeCreations(principal, [...readPendingCreations(principal).filter(item => item.request_id !== value.request_id), value])
}
export function clearPendingCreation(principal: string, requestId: string) {
  writeCreations(principal, readPendingCreations(principal).filter(item => item.request_id !== requestId))
}
function writeCreations(principal: string, entries: PendingCreation[]) {
  try {
    if (entries.length) sessionStorage.setItem(creationKey(principal), JSON.stringify(entries))
    else sessionStorage.removeItem(creationKey(principal))
  } catch { /* 浏览器禁用存储时仍保留当前组件内请求身份。 */ }
  window.dispatchEvent(new Event(projectRecoveryEvent))
}

export interface PendingEdit { display_name: string; description: string | null; expected_revision: string }
const editKey = (principal: string, projectId: string) => `amvision.project-edit.${principal}.${projectId}`
export function readPendingEdit(principal: string, projectId: string): PendingEdit | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(editKey(principal, projectId)) || 'null')
    return typeof value?.display_name === 'string' && typeof value?.expected_revision === 'string' && (value.description === null || typeof value.description === 'string') ? value : null
  } catch { return null }
}
export function savePendingEdit(principal: string, projectId: string, value: PendingEdit | null) {
  try {
    if (value) sessionStorage.setItem(editKey(principal, projectId), JSON.stringify(value))
    else sessionStorage.removeItem(editKey(principal, projectId))
  } catch { /* 浏览器禁用存储时仍可在当前抽屉核对。 */ }
}
