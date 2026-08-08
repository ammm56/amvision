import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiRequest, apiRequestWithHeaders } from './http-client'

function jsonResponse(payload: unknown, status = 200, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'content-type': 'application/json',
      ...headers,
    },
  })
}

describe('http client transient read retries', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('retries a transient GET response and returns the recovered payload', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ message: 'busy' }, 503))
      .mockResolvedValueOnce(jsonResponse({ state: 'ready' }))
    vi.stubGlobal('fetch', fetchMock)

    const payload = await apiRequest<{ state: string }>('/health', {
      transientRetryBaseDelayMs: 0,
    })

    expect(payload).toEqual({ state: 'ready' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('retries a transient network error for a header-returning GET', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError('connection reset'))
      .mockResolvedValueOnce(jsonResponse({ items: [] }, 200, { 'x-request-id': 'request-1' }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiRequestWithHeaders<{ items: unknown[] }>('/projects', {
      transientRetryBaseDelayMs: 0,
    })

    expect(result.payload).toEqual({ items: [] })
    expect(result.headers.get('x-request-id')).toBe('request-1')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('never replays a mutating request', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ message: 'busy' }, 503))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      apiRequest('/tasks', {
        method: 'POST',
        body: { type: 'train' },
        transientRetryBaseDelayMs: 0,
      }),
    ).rejects.toMatchObject({ status: 503 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not retry an aborted read', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new DOMException('Request aborted', 'AbortError'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      apiRequest('/projects', {
        transientRetryBaseDelayMs: 0,
      }),
    ).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
