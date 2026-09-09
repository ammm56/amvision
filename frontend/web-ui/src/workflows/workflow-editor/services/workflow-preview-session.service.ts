import { apiRequest } from '@/shared/api/http-client'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'

export const PREVIEW_FORMAT = 'amvision.workflow-preview-session.v1'
const CHUNK_SIZE = 256 * 1024
const MAX_FILE_BYTES = 64 * 1024 * 1024

export interface PreviewSessionIdentity {
  session_id: string
  epoch: string
  format_id: string
  memory_limit_bytes: number
}

export interface PreviewValuePage {
  value: unknown
  total: number
  offset: number
  limit: number
  has_more: boolean
  value_type: string
  path: Array<string | number>
  children: Array<{ key: string | number; path: Array<string | number>; value_type: string; total: number }>
}

export interface PreviewEvent {
  format_id: string
  session_id: string
  epoch: string
  run_id: string | null
  document_revision: string | null
  seq: number
  type: string
  payload: Record<string, any>
}

type Pending = { resolve: (value: any) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }
type Download = { chunks: ArrayBuffer[]; bytes: number; size: number; next: number; mediaType: string }

export function createPreviewSession(projectId: string, applicationId: string, editorSessionId: string) {
  return apiRequest<PreviewSessionIdentity>('/workflows/preview-sessions', {
    method: 'POST', body: { project_id: projectId, application_id: applicationId, editor_session_id: editorSessionId },
  })
}

export function submitPreviewSession(sessionId: string, body: object) {
  return apiRequest<{ session_id: string; run_id: string; state: string; epoch: string }>(
    `/workflows/preview-sessions/${sessionId}/runs`, { method: 'POST', body })
}

export function cancelPreviewSession(sessionId: string, runId: string) {
  return apiRequest(`/workflows/preview-sessions/${sessionId}/runs/${runId}/cancel`, { method: 'POST' })
}

export function releasePreviewSession(sessionId: string) {
  return apiRequest<void>(`/workflows/preview-sessions/${sessionId}`, { method: 'DELETE', responseType: 'void' })
}

/** 一个连接负责控制与二进制流。断线只恢复快照，绝不重发运行请求。 */
export class PreviewSessionConnection {
  private socket: WebSocket | null = null
  private pending = new Map<string, Pending>()
  private downloads = new Map<string, Download>()
  private reads = new Map<string, Promise<Blob>>()
  private readQueue: Array<() => void> = []
  private activeReads = 0
  private stopped = false
  private reconnect: ReturnType<typeof setTimeout> | null = null
  private attempts = 0
  private connected = false

  constructor(readonly identity: PreviewSessionIdentity, private options: {
    getAccessToken: () => string | null
    queryTokenEnabled: () => boolean
    onEvent: (event: PreviewEvent) => void
    onConnection: (connected: boolean, error?: string, expired?: boolean) => void
  }) {}

  async connect(): Promise<void> {
    const ready = this.wait('snapshot', 15_000)
    this.open()
    await ready
  }

  private open(): void {
    if (this.stopped) return
    const url = new URL(`${getRuntimeConfig().wsBaseUrl.replace(/\/$/, '')}/workflows/preview-sessions/${this.identity.session_id}`)
    if (this.options.queryTokenEnabled()) {
      const token = this.options.getAccessToken()
      if (token) url.searchParams.set('access_token', token)
    }
    const socket = new WebSocket(url)
    socket.binaryType = 'arraybuffer'
    this.socket = socket
    socket.onmessage = ({ data }) => {
      if (socket !== this.socket || this.stopped) return
      try { this.receive(data) } catch (error) {
        this.failPending(error instanceof Error ? error : new Error(String(error)))
        socket.close(1002, 'preview_protocol_invalid')
      }
    }
    socket.onclose = ({ code, reason }) => {
      if (socket !== this.socket) return
      this.connected = false
      this.failPending(new Error(reason || 'preview_connection_lost'))
      const expired = [4401, 4403, 4404].includes(code)
      this.options.onConnection(false, reason || 'preview_connection_lost', expired)
      if (!this.stopped && !expired) {
        this.reconnect = setTimeout(() => this.open(), Math.min(1000 * ++this.attempts, 5000))
      }
    }
  }

  private receive(data: string | ArrayBuffer): void {
    if (data instanceof ArrayBuffer) {
      if (data.byteLength < 32 || data.byteLength > CHUNK_SIZE + 32) throw new Error('preview_frame_size')
      const header = new DataView(data)
      if (header.getUint32(0) !== 0x414d5650 || header.getUint8(4) !== 1 || header.getUint8(5) !== 2 || header.getUint16(6) !== 0) throw new Error('preview_frame_version')
      const blobId = Array.from(new Uint8Array(data, 8, 16), byte => byte.toString(16).padStart(2, '0')).join('')
      const index = header.getUint32(24), length = header.getUint32(28)
      const transfer = this.downloads.get(blobId)
      if (!transfer || index !== transfer.next || length !== data.byteLength - 32 || length < 1 || transfer.bytes + length > transfer.size) throw new Error('preview_frame_order')
      transfer.chunks.push(data.slice(32))
      transfer.bytes += length
      transfer.next++
      this.send({ type: 'display.ack', blob_id: blobId, chunk_index: index })
      return
    }
    const message = JSON.parse(data)
    if (!message || typeof message !== 'object' || typeof message.type !== 'string') throw new Error('preview_message_invalid')
    if (message.type === 'session.ping') { this.send({ type: 'session.pong' }); return }
    if (message.type === 'protocol.error') {
      // 服务器拒绝命令后终止这次传输；不能让 Promise 一直等待不存在的 ACK。
      const inputReply: Record<string, string> = { 'input.begin': 'input.ready', 'input.commit': 'input.committed', 'input.chunk': 'input.ack' }
      const key = message.request_type === 'value.get' ? `value:${message.request_id}` : message.blob_id ? `display:${message.blob_id.replaceAll('-', '')}`
        : message.transfer_id ? `${inputReply[message.request_type]}:${message.transfer_id}${message.request_type === 'input.chunk' ? `:${message.chunk_index}` : ''}` : null
      if (key) this.reject(key, new Error(message.error))
      else this.failPending(new Error(message.error))
      return
    }
    if (message.type === 'value.page') { this.resolve(`value:${message.request_id}`, message); return }
    if (message.type.startsWith('input.')) {
      const key = message.type === 'input.ack' ? `input.ack:${message.transfer_id}:${message.chunk_index}` : `${message.type}:${message.transfer_id}`
      this.resolve(key, message)
      return
    }
    if (message.type === 'display.begin') {
      const transfer = this.downloads.get(message.blob_id)
      if (!transfer || !Number.isSafeInteger(message.byte_length) || message.byte_length < 1 || message.byte_length > MAX_FILE_BYTES * 8) throw new Error('preview_display_size')
      const reserved = [...this.downloads.values()].reduce((total, item) => total + item.size, 0)
      if (reserved + message.byte_length > this.identity.memory_limit_bytes) throw new Error('preview_browser_memory_capacity')
      transfer.size = message.byte_length
      return
    }
    if (message.type === 'display.end') {
      const transfer = this.downloads.get(message.blob_id)
      if (!transfer || transfer.bytes !== transfer.size) throw new Error('preview_display_incomplete')
      this.downloads.delete(message.blob_id)
      this.resolve(`display:${message.blob_id}`, new Blob(transfer.chunks, { type: transfer.mediaType }))
      return
    }
    if (message.format_id !== PREVIEW_FORMAT || message.session_id !== this.identity.session_id || message.epoch !== this.identity.epoch) throw new Error('preview_session_identity')
    if (message.type === 'session.snapshot') {
      this.connected = true
      this.attempts = 0
      this.options.onConnection(true)
      this.resolve('snapshot', undefined)
    }
    this.options.onEvent(message as PreviewEvent)
  }

  private send(message: object | ArrayBuffer): void {
    if (this.socket?.readyState !== WebSocket.OPEN) throw new Error('preview_connection_lost')
    this.socket.send(message instanceof ArrayBuffer ? message : JSON.stringify(message))
  }

  async readValue(blobId: string, offset = 0, path: Array<string | number> = []): Promise<PreviewValuePage> {
    if (!this.connected) throw new Error('preview_connection_lost')
    const requestId = crypto.randomUUID()
    const pending = this.wait(`value:${requestId}`)
    try { this.send({ type: 'value.get', request_id: requestId, blob_id: blobId, offset, limit: 50, path }) }
    catch (error) { this.reject(`value:${requestId}`, error instanceof Error ? error : new Error(String(error))) }
    return pending
  }

  private wait(key: string, timeout = 30_000): Promise<any> {
    if (this.pending.size >= 256) throw new Error('preview_request_capacity')
    if (this.pending.has(key)) throw new Error('preview_request_duplicate')
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => this.reject(key, new Error('preview_transfer_timeout')), timeout)
      this.pending.set(key, { resolve, reject, timer })
    })
  }
  private resolve(key: string, value: any): void {
    const pending = this.pending.get(key)
    if (!pending) return
    clearTimeout(pending.timer)
    this.pending.delete(key)
    pending.resolve(value)
  }
  private reject(key: string, error: Error): void {
    const pending = this.pending.get(key)
    if (!pending) return
    clearTimeout(pending.timer)
    this.pending.delete(key)
    pending.reject(error)
  }
  private failPending(error: Error): void {
    for (const key of this.pending.keys()) this.reject(key, error)
    this.downloads.clear()
  }

  async upload(file: File): Promise<string> {
    if (!this.connected || this.stopped) throw new Error('preview_connection_lost')
    if (!file.size || file.size > MAX_FILE_BYTES) throw new Error('preview_input_capacity')
    const transferId = crypto.randomUUID()
    const content = await file.arrayBuffer()
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', content)), byte => byte.toString(16).padStart(2, '0')).join('')
    const ready = this.wait(`input.ready:${transferId}`)
    this.send({ type: 'input.begin', transfer_id: transferId, byte_length: file.size, media_type: file.type || 'application/octet-stream', file_name: file.name, sha256: digest })
    await ready
    const identity = transferId.replaceAll('-', '').match(/../g)!.map(byte => parseInt(byte, 16))
    for (let offset = 0, index = 0; offset < content.byteLength; offset += CHUNK_SIZE, index++) {
      const length = Math.min(CHUNK_SIZE, content.byteLength - offset)
      const frame = new ArrayBuffer(32 + length)
      const header = new DataView(frame)
      header.setUint32(0, 0x414d5650); header.setUint8(4, 1); header.setUint8(5, 1)
      new Uint8Array(frame, 8, 16).set(identity)
      header.setUint32(24, index); header.setUint32(28, length)
      new Uint8Array(frame, 32).set(new Uint8Array(content, offset, length))
      const ack = this.wait(`input.ack:${transferId}:${index}`)
      this.send(frame)
      await ack
    }
    const committed = this.wait(`input.committed:${transferId}`)
    this.send({ type: 'input.commit', transfer_id: transferId })
    return (await committed).input_id
  }

  readBlob(blobId: string, mediaType = 'image/png'): Promise<Blob> {
    blobId = blobId.replaceAll('-', '')
    const existing = this.reads.get(blobId)
    if (existing) return existing
    if (this.readQueue.length >= 256) return Promise.reject(new Error('preview_browser_capacity'))
    const operation = this.download(blobId, mediaType).finally(() => this.reads.delete(blobId))
    this.reads.set(blobId, operation)
    return operation
  }

  private async download(blobId: string, mediaType: string): Promise<Blob> {
    if (this.activeReads >= 4) await new Promise<void>(resolve => this.readQueue.push(resolve))
    else this.activeReads++
    try {
      if (!this.connected || this.stopped) throw new Error('preview_connection_lost')
      this.downloads.set(blobId, { chunks: [], bytes: 0, size: 0, next: 0, mediaType })
      const received = this.wait(`display:${blobId}`, 60_000)
      this.send({ type: 'display.get', blob_id: blobId })
      return await received
    } finally {
      this.downloads.delete(blobId)
      const next = this.readQueue.shift()
      if (next) next()
      else this.activeReads--
    }
  }

  close(): void {
    this.stopped = true
    this.connected = false
    if (this.reconnect !== null) clearTimeout(this.reconnect)
    this.socket?.close()
    this.failPending(new Error('preview_session_closed'))
  }
}
