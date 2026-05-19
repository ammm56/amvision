import { buildBearerAuthHeader } from './auth-header'
import { ApiError } from './error'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'

type ResponseType = 'json' | 'text' | 'blob' | 'void'

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  body?: BodyInit | object | null
  query?: Record<string, string | number | boolean | null | undefined>
  skipAuth?: boolean
  retryOnUnauthorized?: boolean
  responseType?: ResponseType
}

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
    return { message: response.statusText || '请求失败' }
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
  const { body, query, skipAuth, retryOnUnauthorized = true, responseType = 'json', ...requestInit } = options
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

  const response = await fetch(buildUrl(path, query), {
    ...requestInit,
    headers,
    body: requestBody,
  })

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
  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers: {
      ...buildBearerAuthHeader(options.skipAuth ? null : hooks.getAccessToken()),
      ...(options.headers as Record<string, string> | undefined),
    },
  })
  const payload = await handleResponse<T>(response, options.responseType ?? 'json')
  return { payload, headers: response.headers }
}

export function buildApiContentUrl(pathOrUrl: string): string {
  if (/^https?:\/\//.test(pathOrUrl)) {
    return pathOrUrl
  }
  return buildUrl(pathOrUrl)
}