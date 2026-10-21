import { onBeforeUnmount } from 'vue'

import type { ModelTaskType } from '../services/model.service'

export interface ModelTaskTarget {
  taskType: ModelTaskType
  taskId: string
  isCurrent: () => boolean
}

/** 任务详情的请求归属；写操作只隔离返回结果，不把取消读取当作撤销服务端操作。 */
export function useModelTaskScope(
  getTaskType: () => ModelTaskType | null,
  getTaskId: () => string,
) {
  let disposed = false
  let generation = 0
  const reads = new Map<string, AbortController>()

  function capture(): ModelTaskTarget | null {
    const taskType = getTaskType()
    const taskId = getTaskId()
    if (disposed || !taskType || !taskId) return null
    const currentGeneration = generation
    return {
      taskType,
      taskId,
      isCurrent: () => !disposed
        && currentGeneration === generation
        && getTaskType() === taskType
        && getTaskId() === taskId,
    }
  }

  function cancelRead(channel: string): void {
    reads.get(channel)?.abort()
    reads.delete(channel)
  }

  function startRead(channel: string) {
    const target = capture()
    if (!target) return null
    cancelRead(channel)
    const controller = new AbortController()
    reads.set(channel, controller)
    return {
      ...target,
      signal: controller.signal,
      isCurrent: () => target.isCurrent() && !controller.signal.aborted,
    }
  }

  function invalidate(): void {
    generation += 1
    reads.forEach((controller) => controller.abort())
    reads.clear()
  }

  onBeforeUnmount(() => {
    disposed = true
    invalidate()
  })

  return { capture, startRead, cancelRead, invalidate }
}
