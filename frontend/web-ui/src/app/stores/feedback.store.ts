import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastVariant = 'success' | 'error' | 'warning' | 'info'

export interface ToastNotice {
  id: string
  variant: ToastVariant
  title: string
  message?: string
  durationMs: number
}

export interface ToastNoticeInput {
  variant: ToastVariant
  title: string
  message?: string
  durationMs?: number
}

const DEFAULT_DURATION_MS = 4_500
const MAX_VISIBLE_NOTICES = 3

function createNoticeId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export const useFeedbackStore = defineStore('feedback', () => {
  const notices = ref<ToastNotice[]>([])

  function show(input: ToastNoticeInput): string {
    const title = input.title.trim()
    const message = input.message?.trim() || undefined
    const duplicateIndex = notices.value.findIndex(
      (notice) => notice.variant === input.variant && notice.title === title && notice.message === message,
    )
    if (duplicateIndex >= 0) {
      notices.value.splice(duplicateIndex, 1)
    }

    const notice: ToastNotice = {
      id: createNoticeId(),
      variant: input.variant,
      title,
      message,
      durationMs: input.durationMs ?? (input.variant === 'error' ? 0 : DEFAULT_DURATION_MS),
    }
    notices.value = [...notices.value, notice].slice(-MAX_VISIBLE_NOTICES)
    return notice.id
  }

  function success(title: string, options: Omit<ToastNoticeInput, 'variant' | 'title'> = {}): string {
    return show({ ...options, variant: 'success', title })
  }

  function error(title: string, options: Omit<ToastNoticeInput, 'variant' | 'title'> = {}): string {
    return show({ ...options, variant: 'error', title })
  }

  function warning(title: string, options: Omit<ToastNoticeInput, 'variant' | 'title'> = {}): string {
    return show({ ...options, variant: 'warning', title })
  }

  function info(title: string, options: Omit<ToastNoticeInput, 'variant' | 'title'> = {}): string {
    return show({ ...options, variant: 'info', title })
  }

  function dismiss(id: string): void {
    notices.value = notices.value.filter((notice) => notice.id !== id)
  }

  function clear(): void {
    notices.value = []
  }

  return { notices, show, success, error, warning, info, dismiss, clear }
})
