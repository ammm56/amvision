import { translate } from '@/platform/i18n'

export interface ApiErrorPayload {
  message: string
  code?: string
  details?: unknown
  requestId?: string | null
}

export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly details?: unknown
  readonly requestId?: string | null

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message)
    this.name = 'ApiError'
    this.status = status
    this.code = payload.code
    this.details = payload.details
    this.requestId = payload.requestId
  }
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message
  }
  return translate('errors.requestFailed')
}