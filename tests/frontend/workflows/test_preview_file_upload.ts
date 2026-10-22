import { afterEach, expect, it, vi } from 'vitest'
import { PreviewSessionConnection, PREVIEW_FORMAT } from '@/workflows/workflow-editor/services/workflow-preview-session.service'
import { apiRequest } from '@/shared/api/http-client'

vi.mock('@/shared/api/http-client', () => ({ apiRequest: vi.fn() }))
vi.mock('@/platform/runtime/runtime-config', () => ({ getRuntimeConfig: () => ({ wsBaseUrl: 'ws://127.0.0.1/ws/v1' }) }))

let connection: PreviewSessionConnection
afterEach(() => { connection?.close(); vi.unstubAllGlobals(); vi.clearAllMocks() })

async function connect() {
  let socket: any
  vi.stubGlobal('WebSocket', class {
    static OPEN = 1
    readyState = 1
    onmessage: any
    send() {}
    close() {}
    constructor() { socket = this }
  })
  connection = new PreviewSessionConnection({ session_id: 's', epoch: 'e', format_id: PREVIEW_FORMAT,
    memory_limit_bytes: 512, file_upload_limit_bytes: 1_000_000_000 }, {
    getAccessToken: () => null, queryTokenEnabled: () => false, onEvent: vi.fn(), onConnection: vi.fn(),
  })
  const ready = connection.connect()
  socket.onmessage({ data: JSON.stringify({ format_id: PREVIEW_FORMAT, session_id: 's', epoch: 'e',
    seq: 0, type: 'session.snapshot', payload: { watermark: 0 } }) })
  await ready
}

it('passes the File directly, without whole-file arrayBuffer or hashing', async () => {
  await connect()
  const file = new File(['cloud'], 'cloud.ply')
  Object.defineProperty(file, 'arrayBuffer', { value: vi.fn(() => { throw new Error('must not copy') }) })
  vi.mocked(apiRequest).mockResolvedValue({ input_id: 'complete' })
  expect(await connection.uploadFile(file)).toBe('complete')
  expect(apiRequest).toHaveBeenCalledWith('/workflows/preview-sessions/s/inputs/file', expect.objectContaining({
    body: file, retryOnUnauthorized: false, query: { byte_length: 5, file_name: 'cloud.ply' },
  }))
  expect(file.arrayBuffer).not.toHaveBeenCalled()
})

it('aborts on unmount and rejects a late successful reply', async () => {
  await connect()
  let resolve!: (value: unknown) => void
  vi.mocked(apiRequest).mockImplementation(() => new Promise(done => { resolve = done }))
  const result = connection.uploadFile(new File(['data'], 'cloud.ply'))
  const rejected = expect(result).rejects.toThrow('preview_connection_lost')
  const signal = vi.mocked(apiRequest).mock.calls[0]![1]!.signal!
  connection.close()
  expect(signal.aborted).toBe(true)
  resolve({ input_id: 'late' })
  await rejected
})

it('does not invent a file capacity when the capability is unconfigured', async () => {
  await connect()
  connection.identity.file_upload_limit_bytes = null
  await expect(connection.uploadFile(new File(['data'], 'cloud.ply'))).rejects.toThrow('preview_file_policy_unconfigured')
  expect(apiRequest).not.toHaveBeenCalled()
})
