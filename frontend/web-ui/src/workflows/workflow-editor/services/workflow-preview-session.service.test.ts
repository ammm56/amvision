import { afterEach, beforeEach, expect, it, vi } from 'vitest'
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

it('collects binary chunks in order and acknowledges only received data', async () => {
  const id = '01'.repeat(16), socket = sockets[0]!
  const received = connection.readBlob(id, 'image/png')
  socket.receive({ type: 'display.begin', blob_id: id, byte_length: 5 })
  socket.receive(frame(id, 0, [1, 2, 3]))
  socket.receive(frame(id, 1, [4, 5]))
  socket.receive({ type: 'display.end', blob_id: id })
  const blob = await received
  const bytes = await new Promise<ArrayBuffer>(resolve => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as ArrayBuffer)
    reader.readAsArrayBuffer(blob)
  })
  expect(Array.from(new Uint8Array(bytes))).toEqual([1, 2, 3, 4, 5])
  expect(socket.sent.map(item => JSON.parse(item as string))).toEqual([
    { type: 'display.get', blob_id: id }, { type: 'display.ack', blob_id: id, chunk_index: 0 }, { type: 'display.ack', blob_id: id, chunk_index: 1 },
  ])
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
