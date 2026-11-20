import { computed, ref, watch, type Ref } from 'vue'
import { ApiError } from '@/shared/api/error'
import { resolveModelSubmission, type ModelTaskType } from '../services/model.service'

export function isUncertainModelSubmission(error: unknown, id: string): boolean {
  return !(error instanceof ApiError) || error.status === 0 || error.status === 408 || error.status === 429
    || error.status >= 500 || (error.status === 409 && (error.details as { submission_id?: string } | null)?.submission_id === id)
}

export function useModelSubmissionReceipt(kind: 'training' | 'conversion', projectId: Ref<string>, taskType: Ref<ModelTaskType>, principalId?: Ref<string>) {
  const id = ref<string | null>(null)
  const checking = ref(false)
  const checkedAt = ref<Date | null>(null)
  const status = ref<'unknown' | 'failed' | 'not_created' | 'accepted'>('unknown')
  const acceptedTaskId = ref<string | null>(null)
  const memory = new Map<string, string>()
  const current = () => `amvision.${kind}-submission-unknown:${projectId.value}:${taskType.value}:${principalId?.value ?? ''}`
  const available = computed(() => id.value !== null && id.value !== '1')
  const pending = computed(() => id.value !== null)
  const visible = computed(() => pending.value || status.value === 'not_created')

  function read(key: string): string | null {
    try { return sessionStorage.getItem(key) ?? memory.get(key) ?? null }
    catch { return memory.get(key) ?? null }
  }

  function write(key: string, value: string | null): void {
    if (value === null) memory.delete(key)
    else memory.set(key, value)
    try {
      if (value === null) sessionStorage.removeItem(key)
      else sessionStorage.setItem(key, value)
    } catch { /* 保留本页内的回执。 */ }
    if (key === current()) id.value = value
  }

  watch(current, key => {
    id.value = read(key)
    checkedAt.value = null
    checking.value = false
    status.value = 'unknown'
    acceptedTaskId.value = null
  }, { immediate: true, flush: 'sync' })

  function start(): { id: string; clear: () => void } {
    const key = current()
    // HTTP 本地部署不一定有 randomUUID，getRandomValues 可在普通上下文使用。
    const bytes = crypto.getRandomValues(new Uint8Array(16))
    bytes[6] = (bytes[6] & 15) | 64
    bytes[8] = (bytes[8] & 63) | 128
    const hex = Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('')
    const submissionId = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
    status.value = 'unknown'
    checkedAt.value = null
    acceptedTaskId.value = null
    write(key, submissionId)
    return { id: submissionId, clear: () => {
      if (read(key) === submissionId) write(key, null)
    } }
  }

  async function check(): Promise<string | null> {
    const submissionId = id.value
    if (!submissionId || !available.value || checking.value) return null
    const key = current()
    checking.value = true
    try {
      const result = await resolveModelSubmission(projectId.value, submissionId)
      if (current() !== key || id.value !== submissionId) return null
      checkedAt.value = new Date()
      if (result.status === 'accepted' && result.task_id) {
        status.value = 'accepted'
        acceptedTaskId.value = result.task_id
        return result.task_id
      }
      if (result.status === 'not_created' && result.task_id === null) {
        write(key, null)
        status.value = 'not_created'
      } else status.value = 'failed'
    } catch {
      if (current() === key && id.value === submissionId) {
        checkedAt.value = new Date()
        status.value = 'failed'
      }
    } finally {
      if (current() === key && (id.value === submissionId || id.value === null)) checking.value = false
    }
    return null
  }

  function viewed(taskId: string): void {
    if (acceptedTaskId.value !== taskId) return
    write(current(), null)
    status.value = 'unknown'
    acceptedTaskId.value = null
  }

  return { status, available, pending, visible, checking, checkedAt, acceptedTaskId, start, check, viewed }
}
