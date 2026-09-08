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
    const details = payload.details as { blockers?: Array<{ resource_id?: string; references?: string[] }> } | undefined
    const dependencies = Array.isArray(details?.blockers)
      ? [...new Set(details.blockers.flatMap(item => [item.resource_id, ...(item.references ?? [])]).filter((id): id is string => typeof id === 'string'))]
      : []
    super(dependencies.length ? `${payload.message}\n${dependencies.join('、')}` : payload.message)
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
