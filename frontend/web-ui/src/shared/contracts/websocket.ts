export interface WebSocketEnvelope<TPayload = Record<string, unknown>> {
  stream: string
  event_type: string
  event_version: string
  occurred_at: string
  resource_kind: string
  resource_id: string
  cursor: string | null
  payload: TPayload
}

export interface ResourceStreamState {
  resourceId: string
  stream: string
  connected: boolean
  stale: boolean
  lastBusinessCursor: string | null
  lastBusinessOccurredAt: string | null
  lastDisconnectReason: string | null
  reconnectAttempt: number
  lastError: string | null
}

export function isControlEvent(eventType: string): boolean {
  return eventType.endsWith('.connected') || eventType.endsWith('.heartbeat') || eventType.endsWith('.lagging')
}