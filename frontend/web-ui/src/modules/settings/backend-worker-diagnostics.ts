export interface BackendWorkerProfileDiagnostics {
  profileId: string
  displayName: string
  health: string
  reason: string | null
  workerInstanceId: string | null
  processId: number | null
  heartbeatAgeSeconds: number | null
  enabledConsumerKinds: string[]
  maxConcurrentTasks: number | null
}

export interface BackendWorkerTopologyDiagnostics {
  health: string
  topologyId: string | null
  topologyGeneration: number | null
  topologyEpochId: string | null
  topologyState: string | null
  activatedAt: string | null
  workerCount: number
  runningCount: number
  profiles: BackendWorkerProfileDiagnostics[]
}

export function parseBackendWorkerDiagnostics(value: unknown): BackendWorkerTopologyDiagnostics {
  const record = isRecord(value) ? value : {}
  const workers = Array.isArray(record.workers) ? record.workers : []
  return {
    health: readString(record.health) ?? 'offline',
    topologyId: readString(record.topology_id),
    topologyGeneration: readNumber(record.topology_generation),
    topologyEpochId: readString(record.topology_epoch_id),
    topologyState: readString(record.topology_state),
    activatedAt: readString(record.activated_at),
    workerCount: readNumber(record.worker_count) ?? 0,
    runningCount: readNumber(record.running_count) ?? 0,
    profiles: workers.filter(isRecord).map((worker) => ({
      profileId: readString(worker.profile_id) ?? '-',
      displayName: readString(worker.display_name) ?? readString(worker.profile_id) ?? '-',
      health: readString(worker.health) ?? 'offline',
      reason: readString(worker.reason),
      workerInstanceId: readString(worker.worker_instance_id),
      processId: readNumber(worker.process_id),
      heartbeatAgeSeconds: readNumber(worker.heartbeat_age_seconds),
      enabledConsumerKinds: Array.isArray(worker.enabled_consumer_kinds)
        ? worker.enabled_consumer_kinds.filter((item): item is string => typeof item === 'string' && item.length > 0)
        : [],
      maxConcurrentTasks: readNumber(worker.max_concurrent_tasks),
    })),
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}

function readNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}
