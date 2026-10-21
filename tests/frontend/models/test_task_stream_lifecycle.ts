import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { defineComponent, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSessionStore } from '@/app/stores/session.store'
import { useTaskEvents } from '@/modules/tasks/composables/useTaskEvents'
import { useTrainingTelemetry } from '@/modules/models/composables/useTrainingTelemetry'
import { TaskTestSocket } from './task_lifecycle_support'

enableAutoUnmount(afterEach)
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
beforeEach(() => {
  TaskTestSocket.instances = []
  vi.stubGlobal('WebSocket', TaskTestSocket)
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
})

describe.each(['events', 'telemetry'] as const)('%s stream ownership', (kind) => {
  function setup() {
    const pinia = createPinia()
    const session = useSessionStore(pinia)
    vi.spyOn(session, 'isAuthenticated', 'get').mockReturnValue(true)
    session.websocketQueryTokenEnabled = true
    const id = ref('a')
    const handler = vi.fn()
    const snapshot = vi.fn()
    let stream!: ReturnType<typeof useTaskEvents>
    const wrapper = mount(defineComponent({
      setup() {
        stream = kind === 'events'
          ? useTaskEvents(() => id.value, handler)
          : useTrainingTelemetry(() => id.value, handler, snapshot)
        return () => null
      },
    }), { global: { plugins: [pinia] } })
    function message(socket: TaskTestSocket, taskId: string) {
      socket.message(kind === 'events'
        ? { task_id: taskId, data: { state: 'running' } }
        : { protocol: 'training.telemetry.v1', task_id: taskId, attempt_no: 1, sequence: 1,
            timestamp: '2026-10-21T00:00:00Z', task_type: 'classification', model_type: 'yolo11',
            stage: 'training', granularity: 'batch', metrics: {}, runtime: {} },
      kind === 'events' ? 'progress' : 'training.batch')
    }
    return { wrapper, stream, id, handler, snapshot, message }
  }

  it('binds one connection per task and ignores messages and state from closed connections', () => {
    const { wrapper, stream, id, handler, snapshot, message } = setup()
    stream.start()
    stream.start()
    const old = TaskTestSocket.instances[0]!
    old.onopen?.()
    message(old, 'a')
    expect(handler).toHaveBeenCalledTimes(1)
    id.value = 'b'
    expect(old.close).toHaveBeenCalledTimes(1)
    expect(stream.streamState.value).toBeNull()
    stream.start()
    const current = TaskTestSocket.instances[1]!
    current.onopen?.()
    message(old, 'a')
    old.message({ task_id: 'a' }, 'training.lagging')
    old.onerror?.()
    old.onopen?.()
    old.disconnect()
    message(current, 'a')
    expect(handler).toHaveBeenCalledTimes(1)
    expect(snapshot).not.toHaveBeenCalled()
    expect(stream.streamState.value?.resourceId).toBe('b')
    expect(stream.streamState.value?.connected).toBe(true)
    message(current, 'b')
    expect(handler).toHaveBeenCalledTimes(2)
    expect(TaskTestSocket.active()).toHaveLength(1)
    wrapper.unmount()
    stream.start()
    message(current, 'b')
    expect(handler).toHaveBeenCalledTimes(2)
    expect(TaskTestSocket.active()).toHaveLength(0)
    expect(TaskTestSocket.instances).toHaveLength(2)
    expect(stream.streamState.value).toBeNull()
  })

  it.each(['stop', 'switch', 'unmount'] as const)('cancels pending reconnect on %s', async (exit) => {
    const { wrapper, stream, id } = setup()
    stream.start()
    TaskTestSocket.instances[0]!.disconnect()
    expect(vi.getTimerCount()).toBe(1)
    if (exit === 'stop') stream.stop()
    if (exit === 'switch') id.value = 'b'
    if (exit === 'unmount') wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(20000)
    expect(TaskTestSocket.instances).toHaveLength(1)
    expect(TaskTestSocket.active()).toHaveLength(0)
  })

  it('cannot start for the first time after unmount', () => {
    const { wrapper, stream } = setup()
    wrapper.unmount()
    stream.start()
    expect(TaskTestSocket.instances).toHaveLength(0)
    expect(vi.getTimerCount()).toBe(0)
  })
})
