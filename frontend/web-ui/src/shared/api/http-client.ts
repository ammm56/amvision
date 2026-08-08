import { buildBearerAuthHeader } from './auth-header'
import { ApiError } from './error'
import { translate } from '@/platform/i18n'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'

type ResponseType = 'json' | 'text' | 'blob' | 'void'

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  body?: BodyInit | object | null
  query?: Record<string, string | number | boolean | null | undefined>
  skipAuth?: boolean
  retryOnUnauthorized?: boolean
  /** 是否对幂等只读请求执行短暂故障重试。 */
  retryTransientRead?: boolean
  /** 只读请求的最大重试次数。 */
  transientRetryCount?: number
  /** 只读请求重试的基础退避时间，单位为毫秒。 */
  transientRetryBaseDelayMs?: number
  responseType?: ResponseType
}

const TRANSIENT_READ_STATUSES = new Set([429, 502, 503, 504])
const DEFAULT_TRANSIENT_RETRY_COUNT = 2
const DEFAULT_TRANSIENT_RETRY_BASE_DELAY_MS = 150
const MAX_TRANSIENT_RETRY_DELAY_MS = 2_000

interface HttpClientHooks {
  getAccessToken: () => string | null
  refreshAccessToken: () => Promise<boolean>
  onUnauthorized: () => void
}

let hooks: HttpClientHooks = {
  getAccessToken: () => null,
  refreshAccessToken: async () => false,
  onUnauthorized: () => undefined,
}

export function configureHttpClient(nextHooks: HttpClientHooks): void {
  hooks = nextHooks
}

function buildUrl(path: string, query?: ApiRequestOptions['query']): string {
  const runtimeConfig = getRuntimeConfig()
  const baseUrl = runtimeConfig.apiBaseUrl.replace(/\/$/, '')
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const url = new URL(`${baseUrl}${normalizedPath}`)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined) {
        url.searchParams.set(key, String(value))
      }
    }
  }
  return url.toString()
}

function isPlainJsonBody(body: unknown): body is object {
  return (
    typeof body === 'object' &&
    body !== null &&
    !(body instanceof FormData) &&
    !(body instanceof Blob) &&
    !(body instanceof URLSearchParams) &&
    !(body instanceof ArrayBuffer)
  )
}

async function parseErrorPayload(response: Response): Promise<{ message: string; code?: string; details?: unknown }> {
  try {
    const payload = (await response.json()) as Record<string, unknown>
    const errorPayload = payload.error
    if (errorPayload && typeof errorPayload === 'object') {
      const errorRecord = errorPayload as Record<string, unknown>
      return {
        message: String(errorRecord.message ?? payload.message ?? response.statusText),
        code: typeof errorRecord.code === 'string' ? errorRecord.code : undefined,
        details: errorRecord.details,
      }
    }
    const detail = payload.detail
    if (typeof detail === 'string') {
      return { message: detail }
    }
    if (detail && typeof detail === 'object') {
      const detailRecord = detail as Record<string, unknown>
      return {
        message: String(detailRecord.message ?? payload.message ?? response.statusText),
        code: typeof detailRecord.code === 'string' ? detailRecord.code : undefined,
        details: detailRecord.details,
      }
    }
    return { message: String(payload.message ?? response.statusText) }
  } catch {
    return { message: response.statusText || translate('errors.requestFailed') }
  }
}

async function handleResponse<T>(response: Response, responseType: ResponseType): Promise<T> {
  if (!response.ok) {
    const payload = await parseErrorPayload(response)
    throw new ApiError(response.status, {
      ...payload,
      requestId: response.headers.get('x-request-id'),
    })
  }

  if (responseType === 'void' || response.status === 204) {
    return undefined as T
  }
  if (responseType === 'blob') {
    return (await response.blob()) as T
  }
  if (responseType === 'text') {
    return (await response.text()) as T
  }
  return (await response.json()) as T
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const {
    body,
    query,
    skipAuth,
    retryOnUnauthorized = true,
    retryTransientRead,
    transientRetryCount,
    transientRetryBaseDelayMs,
    responseType = 'json',
    ...requestInit
  } = options
  const headers = new Headers(requestInit.headers)
  if (!skipAuth) {
    for (const [key, value] of Object.entries(buildBearerAuthHeader(hooks.getAccessToken()))) {
      headers.set(key, value)
    }
  }

  let requestBody: BodyInit | undefined
  if (body !== null && body !== undefined) {
    if (isPlainJsonBody(body)) {
      headers.set('Content-Type', 'application/json')
      requestBody = JSON.stringify(body)
    } else {
      requestBody = body as BodyInit
    }
  }

  const response = await fetchWithTransientReadRetry(
    buildUrl(path, query),
    {
      ...requestInit,
      headers,
      body: requestBody,
    },
    { retryTransientRead, transientRetryCount, transientRetryBaseDelayMs },
  )

  if (response.status === 401 && !skipAuth && retryOnUnauthorized) {
    const refreshed = await hooks.refreshAccessToken()
    if (refreshed) {
      return apiRequest<T>(path, { ...options, retryOnUnauthorized: false })
    }
    hooks.onUnauthorized()
  }

  return handleResponse<T>(response, responseType)
}

export async function apiRequestWithHeaders<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<{ payload: T; headers: Headers }> {
  const {
    body,
    query,
    skipAuth,
    retryTransientRead,
    transientRetryCount,
    transientRetryBaseDelayMs,
    responseType = 'json',
    ...requestInit
  } = options
  const headers = new Headers(requestInit.headers)
  if (!skipAuth) {
    for (const [key, value] of Object.entries(buildBearerAuthHeader(hooks.getAccessToken()))) {
      headers.set(key, value)
    }
  }

  let requestBody: BodyInit | undefined
  if (body !== null && body !== undefined) {
    if (isPlainJsonBody(body)) {
      headers.set('Content-Type', 'application/json')
      requestBody = JSON.stringify(body)
    } else {
      requestBody = body as BodyInit
    }
  }

  const response = await fetchWithTransientReadRetry(
    buildUrl(path, query),
    {
      ...requestInit,
      method: requestInit.method ?? 'GET',
      headers,
      body: requestBody,
    },
    { retryTransientRead, transientRetryCount, transientRetryBaseDelayMs },
  )
  const payload = await handleResponse<T>(response, responseType)
  return { payload, headers: response.headers }
}

function isReadMethod(method: string | undefined): boolean {
  const normalizedMethod = (method ?? 'GET').toUpperCase()
  return normalizedMethod === 'GET' || normalizedMethod === 'HEAD'
}

function isAbortError(error: unknown, signal: AbortSignal | null | undefined): boolean {
  return (
    signal?.aborted === true
    || (typeof error === 'object'
      && error !== null
      && 'name' in error
      && error.name === 'AbortError')
  )
}

function parseRetryAfterMs(response: Response): number | null {
  const value = response.headers.get('retry-after')
  if (!value) {
    return null
  }
  const seconds = Number(value)
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.min(seconds * 1_000, MAX_TRANSIENT_RETRY_DELAY_MS)
  }
  const retryAt = Date.parse(value)
  if (Number.isNaN(retryAt)) {
    return null
  }
  return Math.min(Math.max(retryAt - Date.now(), 0), MAX_TRANSIENT_RETRY_DELAY_MS)
}

function waitForRetry(delayMs: number, signal: AbortSignal | null | undefined): Promise<void> {
  if (signal?.aborted) {
    return Promise.reject(signal.reason ?? new DOMException('Request aborted', 'AbortError'))
  }
  return new Promise((resolve, reject) => {
    const timeoutId = globalThis.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, delayMs)
    const onAbort = (): void => {
      globalThis.clearTimeout(timeoutId)
      reject(signal?.reason ?? new DOMException('Request aborted', 'AbortError'))
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

async function discardResponseBody(response: Response): Promise<void> {
  try {
    await response.body?.cancel()
  } catch {
    // 重试前释放连接即可；部分测试或旧浏览器不支持取消空响应体。
  }
}

async function fetchWithTransientReadRetry(
  url: string,
  requestInit: RequestInit,
  options: Pick<
    ApiRequestOptions,
    'retryTransientRead' | 'transientRetryCount' | 'transientRetryBaseDelayMs'
  >,
): Promise<Response> {
  const retryEnabled = options.retryTransientRead !== false && isReadMethod(requestInit.method)
  const retryCount = retryEnabled
    ? Math.min(Math.max(Math.trunc(options.transientRetryCount ?? DEFAULT_TRANSIENT_RETRY_COUNT), 0), 5)
    : 0
  const baseDelayMs = Math.min(
    Math.max(Math.trunc(options.transientRetryBaseDelayMs ?? DEFAULT_TRANSIENT_RETRY_BASE_DELAY_MS), 0),
    MAX_TRANSIENT_RETRY_DELAY_MS,
  )

  for (let attempt = 0; ; attempt += 1) {
    try {
      const response = await fetch(url, requestInit)
      if (attempt >= retryCount || !TRANSIENT_READ_STATUSES.has(response.status)) {
        return response
      }
      const delayMs = parseRetryAfterMs(response) ?? Math.min(baseDelayMs * 2 ** attempt, MAX_TRANSIENT_RETRY_DELAY_MS)
      await discardResponseBody(response)
      await waitForRetry(delayMs, requestInit.signal)
    } catch (error) {
      if (attempt >= retryCount || isAbortError(error, requestInit.signal)) {
        throw error
      }
      const delayMs = Math.min(baseDelayMs * 2 ** attempt, MAX_TRANSIENT_RETRY_DELAY_MS)
      await waitForRetry(delayMs, requestInit.signal)
    }
  }
}

export function buildApiContentUrl(pathOrUrl: string): string {
  if (/^https?:\/\//.test(pathOrUrl)) {
    return pathOrUrl
  }
  return buildUrl(pathOrUrl)
}
