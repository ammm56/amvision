import { vi } from 'vitest'

import type {
  ModelConversionTaskDetail,
  ModelTaskType,
  ModelTrainingOutputFileDetail,
  ModelTrainingTaskDetail,
} from '@/modules/models/services/model.service'

export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

export function trainingTask(taskId: string, taskType: ModelTaskType = 'classification'): ModelTrainingTaskDetail {
  return {
    task_id: taskId, task_type: taskType, model_type: 'yolo11', display_name: `training ${taskId}`,
    project_id: 'project-1', created_at: '2026-10-21T00:00:00Z', state: 'running', current_attempt_no: 1,
    progress: { epoch: 1, max_epochs: 4, percent: 25 }, result: {}, metadata: {}, dataset_export_id: 'export-1',
    model_version_id: null, latest_checkpoint_model_version_id: null, output_object_prefix: `task-runs/${taskId}`,
    checkpoint_object_key: null, latest_checkpoint_object_key: `task-runs/${taskId}/last.pt`, labels_object_key: null,
    metrics_object_key: null, validation_metrics_object_key: null, summary_object_key: null,
    best_metric_name: null, best_metric_value: null, training_summary: {},
    available_actions: ['save', 'pause', 'terminate', 'resume', 'delete'],
    control_status: { status: 'idle', pending_action: null, resume_count: 0, resume_checkpoint_object_key: null },
    task_spec: {}, events: [],
  }
}

export function conversionTask(taskId: string): ModelConversionTaskDetail {
  return {
    task_id: taskId, display_name: `conversion ${taskId}`, project_id: 'project-1', created_at: '2026-10-21T00:00:00Z',
    state: 'succeeded', current_attempt_no: 1, progress: {}, result: {}, metadata: {}, source_model_version_id: 'source-1',
    target_formats: ['onnx'], requested_target_formats: ['onnx'], produced_formats: ['onnx'],
    builds: [], report_summary: {}, task_spec: {}, events: [],
  }
}

export function outputFile(taskId: string, name: string): ModelTrainingOutputFileDetail {
  return {
    file_name: name, file_kind: 'json', file_status: 'ready', task_state: 'running',
    object_key: `${taskId}/${name}`, size_bytes: 128, updated_at: '2026-10-21T00:00:00Z',
    payload: { marker: `${taskId}/${name}` }, text_content: null, lines: [],
  }
}

/** 保留关闭后的回调，显式模拟已经进入事件队列的晚到消息。 */
export class TaskTestSocket {
  static instances: TaskTestSocket[] = []
  onopen: (() => void) | null = null
  onclose: ((event: { reason: string; code: number }) => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  closed = false
  close = vi.fn(() => {
    this.closed = true
    this.onclose?.({ reason: 'client closed', code: 1000 })
  })

  constructor(readonly url: string) { TaskTestSocket.instances.push(this) }

  message(payload: Record<string, unknown>, eventType = 'progress'): void {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify({
      stream: 'tasks.events', event_type: eventType, event_version: '1',
      occurred_at: '2026-10-21T00:00:00Z', resource_kind: 'task',
      resource_id: payload.task_id, cursor: 'cursor-1', payload,
    }) }))
  }

  disconnect(): void { this.onclose?.({ reason: 'network', code: 1006 }) }

  static active(): TaskTestSocket[] { return this.instances.filter((socket) => !socket.closed) }
}
