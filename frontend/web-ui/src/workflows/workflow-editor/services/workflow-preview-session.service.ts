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
type Download = { chunks: ArrayBuffer[]; bytes: number; size: number; next: number; mediaType: string; discardError?: string }

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
  private blobs = new Map<string, Blob>()
  private resources = new Map<string, Map<string, string>>()
  private receipts = new Map<string, string>()
  private descriptors = new Map<string, { size: number; available: boolean }>()
  private failures = new Map<string, Error>()
  private released = new Set<string>()
  private runId: string | null = null
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
    onResources?: () => void
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
      const failureReason = reason || (code === 4404 ? 'preview_session_expired' : 'preview_connection_lost')
      this.failPending(new Error(failureReason))
      const expired = [4401, 4403, 4404].includes(code)
      this.options.onConnection(false, failureReason, expired)
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
      if (!transfer.discardError) transfer.chunks.push(data.slice(32))
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
      const key = message.blob_id ? `display:${message.blob_id.replaceAll('-', '')}`
        : message.transfer_id ? `${inputReply[message.request_type]}:${message.transfer_id}${message.request_type === 'input.chunk' ? `:${message.chunk_index}` : ''}` : null
      if (key) this.reject(key, new Error(message.error))
      else this.failPending(new Error(message.error))
      return
    }
    if (message.type.startsWith('input.')) {
      const key = message.type === 'input.ack' ? `input.ack:${message.transfer_id}:${message.chunk_index}` : `${message.type}:${message.transfer_id}`
      this.resolve(key, message)
      return
    }
    if (message.type === 'display.begin') {
      const transfer = this.downloads.get(message.blob_id)
      if (!transfer || !Number.isSafeInteger(message.byte_length) || message.byte_length < 1 || message.byte_length > MAX_FILE_BYTES * 8) throw new Error('preview_display_size')
      const reserved = [...this.downloads.values()].reduce((total, item) => total + item.size, 0)
        + [...this.blobs.values()].reduce((total, item) => total + item.size, 0)
      // 合法的大结果超出浏览器预算只拒绝该资源，不能制造 WS 重连循环。
      if (reserved + message.byte_length > this.identity.memory_limit_bytes) transfer.discardError = 'preview_browser_memory_capacity'
      transfer.size = message.byte_length
      return
    }
    if (message.type === 'display.end') {
      const transfer = this.downloads.get(message.blob_id)
      if (!transfer || transfer.bytes !== transfer.size) throw new Error('preview_display_incomplete')
      this.downloads.delete(message.blob_id)
      if (transfer.discardError) { this.reject(`display:${message.blob_id}`, new Error(transfer.discardError)); return }
      const blob = new Blob(transfer.chunks, { type: transfer.mediaType })
      this.blobs.set(message.blob_id, blob)
      this.resolve(`display:${message.blob_id}`, blob)
      if (typeof message.receipt === 'string') {
        this.receipts.set(message.blob_id, message.receipt)
        this.send({ type: 'resource.received', blob_id: message.blob_id, receipt: message.receipt })
      }
      return
    }
    if (message.format_id !== PREVIEW_FORMAT || message.session_id !== this.identity.session_id || message.epoch !== this.identity.epoch) throw new Error('preview_session_identity')
    if (!this.projectResources(message as PreviewEvent)) return
    if (message.type === 'session.snapshot') {
      this.connected = true
      this.attempts = 0
      this.options.onConnection(true)
      this.resolve('snapshot', undefined)
    }
    this.trackResources(message as PreviewEvent)
    this.options.onEvent(message as PreviewEvent)
  }

  /** 页面重载没有 Blob 缓存；已释放的历史资源不能按可重试传输错误恢复。 */
  private projectResources(event: PreviewEvent): boolean {
    if (event.type === 'run.accepted') this.released.clear()
    if (event.type !== 'session.snapshot' && this.released.size === 0) return true
    if (!['session.snapshot', 'run.outputs', 'run.finished', 'display.updated', 'value.updated'].includes(event.type)) return true
    const expired = new Set<string>()
    const missing = (value: any): boolean => {
      if (!value || typeof value !== 'object') return false
      let unavailable = false
      if (value.transport_kind === 'preview-memory' && typeof value.blob_id === 'string') {
        const id = value.blob_id.replaceAll('-', '')
        if ((value.server_available === false || this.released.has(id)) && !this.blobs.has(id)) {
          expired.add(id)
          this.released.add(id)
          unavailable = true
        }
      }
      for (const child of Object.values(value)) if (missing(child)) unavailable = true
      return unavailable
    }
    const payload = event.payload
    // 保留可恢复的值与显示；同页断线仍可使用已接管的完整 Blob。
    if (event.type === 'session.snapshot') {
      for (const kind of ['displays', 'values']) payload[kind] = (payload[kind] ?? []).filter((item: any) => !missing(item))
    } else if (event.type === 'display.updated' || event.type === 'value.updated') {
      return !missing(payload)
    }
    const pruneOutputs = (value: any): any => {
      if (!value || typeof value !== 'object') return value
      if (value.transport_kind === 'preview-memory' && missing(value)) return { unavailable: true, reason: 'preview_result_expired' }
      if (Array.isArray(value)) return value.map(pruneOutputs)
      return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, pruneOutputs(child)]))
    }
    if (payload.run) payload.run.outputs = pruneOutputs(payload.run.outputs)
    if ('outputs' in payload) payload.outputs = pruneOutputs(payload.outputs)
    payload.expired_resources = expired.size
    return true
  }

  /** 当前结果在浏览器持有完整副本；旧版本替换后同时撤销缓存引用。 */
  private trackResources(event: PreviewEvent): void {
    const register = (key: string, value: unknown) => {
      const found = new Map<string, string>()
      const visit = (item: any): void => {
        if (!item || typeof item !== 'object') return
        if (item.transport_kind === 'preview-memory' && typeof item.blob_id === 'string') {
          const id = item.blob_id.replaceAll('-', '')
          found.set(id, item.media_type || 'image/jpeg')
          this.descriptors.set(id, { size: Number.isSafeInteger(item.byte_length) ? item.byte_length : 0, available: item.server_available !== false })
        }
        for (const child of Object.values(item)) visit(child)
      }
      visit(value)
      this.resources.set(key, found)
    }
    const payload = event.payload
    if (event.type === 'session.snapshot') {
      this.runId = payload.run?.run_id ?? null
      this.failures.clear()
      this.resources.clear()
      for (const kind of ['displays', 'values']) for (const item of payload[kind] ?? []) register(JSON.stringify([kind, item.node_id, item.output_port]), item)
      register('outputs', payload.run?.outputs)
    } else if (event.type === 'run.accepted') {
      this.runId = event.run_id
      const nodes = Array.isArray(payload.node_ids) ? new Set(payload.node_ids) : null
      for (const key of this.resources.keys()) {
        if (key === 'outputs') this.resources.delete(key)
        else {
          const [kind, node] = JSON.parse(key)
          if (kind === 'values' || nodes && !nodes.has(node)) this.resources.delete(key)
        }
      }
    } else if (event.run_id !== this.runId) return
    else if (event.type === 'display.updated' || event.type === 'value.updated') {
      register(JSON.stringify([event.type === 'display.updated' ? 'displays' : 'values', payload.node_id, payload.output_port]), payload)
    } else if (event.type === 'run.finished' || event.type === 'run.outputs') {
      if ('outputs' in payload) register('outputs', payload.outputs)
    } else return
    const current = new Map([...this.resources.values()].flatMap(value => [...value]))
    for (const id of this.descriptors.keys()) if (!current.has(id) && !this.reads.has(id)) {
      this.blobs.delete(id); this.receipts.delete(id); this.descriptors.delete(id); this.failures.delete(id)
    }
    if (event.type === 'session.snapshot') for (const [id, receipt] of this.receipts) {
      if (current.has(id)) this.send({ type: 'resource.received', blob_id: id, receipt })
    }
    // 完整源图和大值也转移到浏览器，不能只接收缩略图后长期占用后端。
    for (const [id, mediaType] of current) void this.readBlob(id, mediaType).catch(() => { /* 显式读取仍返回具体容量/传输错误。 */ })
    this.options.onResources?.()
  }

  /** 只检查当前显示的完整 Blob，浏览器解码由反馈回调单独确认。 */
  resourceStatus(): { pending: number; errors: string[] } {
    const current = new Set([...this.resources.values()].flatMap(value => [...value.keys()]))
    let pending = 0
    const errors: string[] = []
    for (const id of current) {
      if (this.blobs.has(id)) continue
      const error = this.failures.get(id)?.message ?? (this.descriptors.get(id)?.available === false ? 'preview_memory_unavailable' : null)
      if (error) errors.push(error)
      else pending++
    }
    return { pending, errors: [...new Set(errors)] }
  }

  private send(message: object | ArrayBuffer): void {
    if (this.socket?.readyState !== WebSocket.OPEN) throw new Error('preview_connection_lost')
    this.socket.send(message instanceof ArrayBuffer ? message : JSON.stringify(message))
  }

  async readValue(blobId: string, offset = 0, path: Array<string | number> = []): Promise<PreviewValuePage> {
    if (!Number.isSafeInteger(offset) || offset < 0) throw new Error('preview_value_page_invalid')
    if (!Array.isArray(path) || path.length > 32 || path.some(key => typeof key !== 'string' && !Number.isSafeInteger(key))) throw new Error('preview_value_path_invalid')
    const blob = await this.readBlob(blobId, 'application/json')
    let value: any = JSON.parse(await blob.text())
    for (const key of path) {
      if (value == null || !Object.prototype.hasOwnProperty.call(value, key)) throw new Error('preview_value_path_invalid')
      value = value[key]
    }
    const children: PreviewValuePage['children'] = []
    const describe = (key: string | number, item: any): any => {
      if (item !== null && typeof item === 'object' || typeof item === 'string' && item.length > 1024) {
        const type = Array.isArray(item) ? 'list' : typeof item === 'string' ? 'str' : 'dict'
        const total = type === 'dict' ? Object.keys(item).length : item.length
        children.push({ key, path: [...path, key], value_type: type, total })
        return { value_type: type, total, summary: true }
      }
      return item
    }
    const type = Array.isArray(value) ? 'list' : value !== null && typeof value === 'object' ? 'dict' : typeof value === 'string' ? 'str' : value === null ? 'NoneType' : typeof value === 'boolean' ? 'bool' : Number.isInteger(value) ? 'int' : 'float'
    const total = type === 'dict' ? Object.keys(value).length : ['list', 'str'].includes(type) ? value.length : 1
    const page = type === 'dict' ? Object.fromEntries(Object.entries(value).slice(offset, offset + 50).map(([key, item]) => [key, describe(key, item)]))
      : type === 'list' ? value.slice(offset, offset + 50).map((item: any, index: number) => describe(offset + index, item))
        : type === 'str' ? value.slice(offset, offset + 50) : value
    return { value: page, total, offset, limit: 50, has_more: offset + 50 < total, value_type: type, path, children }
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

  async upload(file: File, onTimings?: (timings: Record<string, number>) => void): Promise<string> {
    if (!this.connected || this.stopped) throw new Error('preview_connection_lost')
    if (!file.size || file.size > MAX_FILE_BYTES) throw new Error('preview_input_capacity')
    const transferId = crypto.randomUUID()
    const started = performance.now()
    const content = await file.arrayBuffer()
    const readDone = performance.now()
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', content)), byte => byte.toString(16).padStart(2, '0')).join('')
    const hashDone = performance.now()
    const ready = this.wait(`input.ready:${transferId}`)
    this.send({ type: 'input.begin', transfer_id: transferId, byte_length: file.size, media_type: file.type || 'application/octet-stream', file_name: file.name, sha256: digest })
    await ready
    const identity = transferId.replaceAll('-', '').match(/../g)!.map(byte => parseInt(byte, 16))
    const acknowledgements: Promise<any>[] = []
    for (let offset = 0, index = 0; offset < content.byteLength; offset += CHUNK_SIZE, index++) {
      const length = Math.min(CHUNK_SIZE, content.byteLength - offset)
      const frame = new ArrayBuffer(32 + length)
      const header = new DataView(frame)
      header.setUint32(0, 0x414d5650); header.setUint8(4, 1); header.setUint8(5, 1)
      new Uint8Array(frame, 8, 16).set(identity)
      header.setUint32(24, index); header.setUint32(28, length)
      new Uint8Array(frame, 32).set(new Uint8Array(content, offset, length))
      const ack = this.wait(`input.ack:${transferId}:${index}`)
      // 后续帧可能在较早帧失败后被连接一并拒绝；主等待仍传播错误。
      void ack.catch(() => {})
      this.send(frame)
      acknowledgements.push(ack)
      // 每收到最早一帧 ACK 就补充一帧，保持有界连续窗口，避免逐批停顿。
      if (acknowledgements.length === 8) await acknowledgements.shift()
    }
    await Promise.all(acknowledgements)
    const committed = this.wait(`input.committed:${transferId}`)
    this.send({ type: 'input.commit', transfer_id: transferId })
    const result = await committed
    onTimings?.({ client_file_read_ms: readDone - started, client_file_hash_ms: hashDone - readDone, client_file_transfer_ms: performance.now() - hashDone })
    return result.input_id
  }

  readBlob(blobId: string, mediaType = 'image/jpeg'): Promise<Blob> {
    blobId = blobId.replaceAll('-', '')
    const cached = this.blobs.get(blobId)
    if (cached) return Promise.resolve(cached)
    const existing = this.reads.get(blobId)
    if (existing) return existing
    const failed = this.failures.get(blobId)
    if (failed) return Promise.reject(failed)
    const descriptor = this.descriptors.get(blobId)
    if (descriptor?.available === false) return Promise.reject(new Error('preview_memory_unavailable'))
    const reserved = [...this.blobs.values()].reduce((sum, item) => sum + item.size, 0)
      + [...this.reads.keys()].reduce((sum, id) => sum + (this.descriptors.get(id)?.size ?? 0), 0)
    if (reserved + (descriptor?.size ?? 0) > this.identity.memory_limit_bytes) {
      const error = new Error('preview_browser_memory_capacity')
      this.failures.set(blobId, error)
      return Promise.reject(error)
    }
    if (this.readQueue.length >= 256) return Promise.reject(new Error('preview_browser_capacity'))
    const operation = this.download(blobId, mediaType).catch(error => { this.failures.set(blobId, error); throw error }).finally(() => {
      this.reads.delete(blobId)
      this.options.onResources?.()
    })
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
    this.blobs.clear()
    this.resources.clear()
    this.receipts.clear()
    this.descriptors.clear()
    this.failures.clear()
    this.released.clear()
  }
}
