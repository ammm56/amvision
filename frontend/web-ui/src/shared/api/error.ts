import { translate } from '@/platform/i18n'

export interface ApiErrorPayload {
  message: string
  code?: string
  details?: unknown
  requestId?: string | null
}

/** 只按已知规则显示固定译文，不拼接服务器的原始异常或用户输入。 */
function validationMessage(details: unknown): string | undefined {
  if (!details || typeof details !== 'object') return undefined
  const errors = (details as { errors?: unknown }).errors
  if (!Array.isArray(errors)) return undefined
  const keys: Record<string, string> = {
    yolox_warmup_epochs_invalid: 'modelOps.trainingParameters.yoloxWarmupInvalid',
    yolox_epoch_schedule_invalid: 'modelOps.trainingParameters.yoloxScheduleInvalid',
    training_range_order_invalid: 'modelOps.trainingParameters.rangeOrderInvalidGeneric',
  }
  for (const item of errors.slice(0, 32)) {
    if (!item || typeof item !== 'object' || typeof item.rule !== 'string') continue
    const key = Object.hasOwn(keys, item.rule) ? keys[item.rule] : undefined
    if (key) return translate(key)
  }
  return undefined
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
    const message = payload.code === 'request_validation_failed'
      ? validationMessage(payload.details) ?? payload.message
      : payload.message
    super(dependencies.length ? `${message}\n${dependencies.join('、')}` : message)
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
