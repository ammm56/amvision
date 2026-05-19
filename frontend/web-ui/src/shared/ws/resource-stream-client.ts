import type { ResourceStreamState, WebSocketEnvelope } from '@/shared/contracts'
import { isControlEvent } from '@/shared/contracts'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'

export interface ResourceStreamClientOptions {
  stream: string
  path: string
  resourceId: string
  query?: Record<string, string | number | boolean | null | undefined>
  getAccessToken: () => string | null
  queryTokenEnabled: () => boolean
  onMessage: (message: WebSocketEnvelope) => void
  onStateChange?: (state: ResourceStreamState) => void
}

export class ResourceStreamClient {
  private socket: WebSocket | null = null
  private reconnectTimer: number | null = null
  private closedByClient = false
  private readonly state: ResourceStreamState

  constructor(private readonly options: ResourceStreamClientOptions) {
    this.state = {
      resourceId: options.resourceId,
      stream: options.stream,
      connected: false,
      stale: false,
      lastBusinessCursor: null,
      lastBusinessOccurredAt: null,
      lastDisconnectReason: null,
      reconnectAttempt: 0,
      lastError: null,
    }
  }

  connect(): void {
    this.closedByClient = false
    this.openSocket()
  }

  close(): void {
    this.closedByClient = true
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.socket?.close()
    this.socket = null
  }

  getState(): ResourceStreamState {
    return { ...this.state }
  }

  private openSocket(): void {
    const url = this.buildUrl()
    this.socket = new WebSocket(url)
    this.socket.onopen = () => {
      this.state.connected = true
      this.state.stale = false
      this.state.lastError = null
      this.emitState()
    }
    this.socket.onmessage = (event) => this.handleMessage(event)
    this.socket.onerror = () => {
      this.state.lastError = 'WebSocket 连接异常'
      this.emitState()
    }
    this.socket.onclose = (event) => {
      this.state.connected = false
      this.state.stale = true
      this.state.lastDisconnectReason = event.reason || `closed:${event.code}`
      this.emitState()
      if (!this.closedByClient) {
        this.scheduleReconnect()
      }
    }
  }

  private handleMessage(event: MessageEvent<string>): void {
    const message = JSON.parse(event.data) as WebSocketEnvelope
    if (!isControlEvent(message.event_type)) {
      this.state.lastBusinessCursor = message.cursor
      this.state.lastBusinessOccurredAt = message.occurred_at
    }
    if (message.event_type.endsWith('.lagging')) {
      this.state.stale = true
    }
    this.options.onMessage(message)
    this.emitState()
  }

  private scheduleReconnect(): void {
    this.state.reconnectAttempt += 1
    const delayMs = Math.min(1000 * this.state.reconnectAttempt, 10000)
    this.reconnectTimer = window.setTimeout(() => this.openSocket(), delayMs)
  }

  private buildUrl(): string {
    const baseUrl = getRuntimeConfig().wsBaseUrl.replace(/\/$/, '')
    const normalizedPath = this.options.path.startsWith('/') ? this.options.path : `/${this.options.path}`
    const url = new URL(`${baseUrl}${normalizedPath}`)
    const query = this.options.query ?? {}
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined) {
        url.searchParams.set(key, String(value))
      }
    }
    if (this.state.lastBusinessCursor) {
      url.searchParams.set('after_cursor', this.state.lastBusinessCursor)
    }
    if (this.options.queryTokenEnabled()) {
      const token = this.options.getAccessToken()
      if (token) {
        url.searchParams.set('access_token', token)
      }
    }
    return url.toString()
  }

  private emitState(): void {
    this.options.onStateChange?.({ ...this.state })
  }
}