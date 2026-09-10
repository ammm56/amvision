import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { PREVIEW_FORMAT, PreviewSessionConnection } from './workflow-preview-session.service'

vi.mock('@/platform/runtime/runtime-config', () => ({ getRuntimeConfig: () => ({ wsBaseUrl: 'ws://127.0.0.1/ws/v1' }) }))
const sockets: Socket[] = []
class Socket {
  static OPEN = 1
  readyState = 1
  binaryType = ''
  sent: Array<string | ArrayBuffer> = []
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null
  onclose: ((event: { code: number; reason: string }) => void) | null = null
  constructor(public url: string) { sockets.push(this) }
  send(value: string | ArrayBuffer) { this.sent.push(value) }
  close = vi.fn()
  receive(value: object | ArrayBuffer) { this.onmessage?.({ data: value instanceof ArrayBuffer ? value : JSON.stringify(value) }) }
}
let connection: PreviewSessionConnection
beforeEach(async () => {
  sockets.length = 0
  vi.stubGlobal('WebSocket', Socket)
  connection = new PreviewSessionConnection({ session_id: 's', epoch: 'e', format_id: PREVIEW_FORMAT, memory_limit_bytes: 512 * 1024 ** 2 }, {
    getAccessToken: () => 'test', queryTokenEnabled: () => true, onEvent: vi.fn(), onConnection: vi.fn(),
  })
  const ready = connection.connect()
  sockets[0]!.receive({ format_id: PREVIEW_FORMAT, session_id: 's', epoch: 'e', seq: 0, type: 'session.snapshot', payload: { watermark: 0 } })
  await ready
})
afterEach(() => { connection.close(); vi.unstubAllGlobals() })

function frame(blobId: string, index: number, content: number[]): ArrayBuffer {
  const frame = new ArrayBuffer(32 + content.length), view = new DataView(frame)
  view.setUint32(0, 0x414d5650); view.setUint8(4, 1); view.setUint8(5, 2)
  new Uint8Array(frame, 8, 16).set(blobId.match(/../g)!.map(byte => parseInt(byte, 16)))
  view.setUint32(24, index); view.setUint32(28, content.length)
  new Uint8Array(frame, 32).set(content)
  return frame
}

it('keeps at most eight upload chunks in flight and refills after one ACK', async () => {
  const transferId = '12345678-1234-1234-1234-123456789abc'
  vi.stubGlobal('crypto', { randomUUID: () => transferId, subtle: { digest: async () => new ArrayBuffer(32) } })
  const socket = sockets[0]!, content = new ArrayBuffer(10 * 256 * 1024)
  const uploaded = connection.upload({ size: content.byteLength, name: 'test.bmp', type: 'image/bmp', arrayBuffer: async () => content } as File)
  await flushPromises()
  socket.receive({ type: 'input.ready', transfer_id: transferId })
  await flushPromises()
  const frames = () => socket.sent.filter(item => item instanceof ArrayBuffer)
  expect(frames()).toHaveLength(8)
  socket.receive({ type: 'input.ack', transfer_id: transferId, chunk_index: 0 })
  await flushPromises()
  expect(frames()).toHaveLength(9)
  for (let index = 1; index < 10; index++) {
    socket.receive({ type: 'input.ack', transfer_id: transferId, chunk_index: index })
    await flushPromises()
  }
  expect(frames()).toHaveLength(10)
  expect(JSON.parse(socket.sent.at(-1) as string).type).toBe('input.commit')
  socket.receive({ type: 'input.committed', transfer_id: transferId, input_id: 'complete' })
  expect(await uploaded).toBe('complete')
})

it('collects binary chunks in order and acknowledges only received data', async () => {
  const id = '01'.repeat(16), socket = sockets[0]!
  const received = connection.readBlob(id, 'image/png')
  socket.receive({ type: 'display.begin', blob_id: id, byte_length: 5 })
  socket.receive(frame(id, 0, [1, 2, 3]))
  socket.receive(frame(id, 1, [4, 5]))
  expect(socket.sent.every(item => !String(item).includes('resource.received'))).toBe(true)
  socket.receive({ type: 'display.end', blob_id: id, receipt: 'complete-proof' })
  const blob = await received
  const bytes = await new Promise<ArrayBuffer>(resolve => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as ArrayBuffer)
    reader.readAsArrayBuffer(blob)
  })
  expect(Array.from(new Uint8Array(bytes))).toEqual([1, 2, 3, 4, 5])
  expect(socket.sent.map(item => JSON.parse(item as string))).toEqual([
    { type: 'display.get', blob_id: id }, { type: 'display.ack', blob_id: id, chunk_index: 0 }, { type: 'display.ack', blob_id: id, chunk_index: 1 },
    { type: 'resource.received', blob_id: id, receipt: 'complete-proof' },
  ])
  expect(await connection.readBlob(id)).toBe(blob)
  expect(socket.sent).toHaveLength(4)
})

it('oversized display fails only its own transfer without a reconnect loop', async () => {
  const id = '05'.repeat(16), socket = sockets[0]!
  connection.identity.memory_limit_bytes = 2
  const received = connection.readBlob(id)
  const rejection = expect(received).rejects.toThrow('preview_browser_memory_capacity')
  socket.receive({ type: 'display.begin', blob_id: id, byte_length: 3 })
  socket.receive(frame(id, 0, [1, 2, 3]))
  socket.receive({ type: 'display.end', blob_id: id, receipt: 'not-owned' })
  await rejection
  expect(socket.close).not.toHaveBeenCalled()
  const count = socket.sent.length
  await expect(connection.readBlob(id)).rejects.toThrow('preview_browser_memory_capacity')
  expect(socket.sent).toHaveLength(count)
})

it('pages complete nested JSON from browser ownership without another server request', async () => {
  // jsdom 的 Blob 缺少现代浏览器 text()，只补测试环境 API。
  vi.stubGlobal('Blob', class extends Blob {
    text(): Promise<string> {
      return new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result))
        reader.onerror = () => reject(reader.error)
        reader.readAsText(this)
      })
    }
  })
  const id = '06'.repeat(16), socket = sockets[0]!
  const source = { items: Array.from({ length: 80 }, (_, index) => ({ index, value: false, score: 0 })) }
  const bytes = [...new TextEncoder().encode(JSON.stringify(source))]
  const page = connection.readValue(id, 50, ['items'])
  socket.receive({ type: 'display.begin', blob_id: id, byte_length: bytes.length })
  socket.receive(frame(id, 0, bytes))
  socket.receive({ type: 'display.end', blob_id: id, receipt: 'json-proof' })
  const result = await page
  expect(result).toMatchObject({ total: 80, offset: 50, has_more: false })
  expect(result.children).toHaveLength(30)
  expect(result.children[0]).toMatchObject({ key: 50, path: ['items', 50], value_type: 'dict', total: 3 })
  const count = socket.sent.length
  expect((await connection.readValue(id, 0, ['items', 79])).value).toEqual({ index: 79, value: false, score: 0 })
  expect(socket.sent).toHaveLength(count)
})

it('rejects bad frame ordering instead of publishing a partial image', async () => {
  const id = '02'.repeat(16), socket = sockets[0]!
  const received = connection.readBlob(id)
  const rejection = expect(received).rejects.toThrow('preview_frame_order')
  socket.receive({ type: 'display.begin', blob_id: id, byte_length: 3 })
  socket.receive(frame(id, 1, [1, 2, 3]))
  await rejection
  expect(socket.close).toHaveBeenCalledWith(1002, 'preview_protocol_invalid')
  expect(socket.sent).toHaveLength(1)
})

it('an expired image does not reject another node image transfer', async () => {
  const a = '03'.repeat(16), b = '04'.repeat(16), socket = sockets[0]!
  const first = connection.readBlob(a), second = connection.readBlob(b)
  const rejection = expect(first).rejects.toThrow('preview_memory_unavailable')
  socket.receive({ type: 'protocol.error', request_type: 'display.get', blob_id: a, error: 'preview_memory_unavailable' })
  socket.receive({ type: 'display.begin', blob_id: b, byte_length: 1 })
  socket.receive(frame(b, 0, [9])); socket.receive({ type: 'display.end', blob_id: b })
  await rejection
  expect((await second).size).toBe(1)
})
