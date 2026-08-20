import { describe, expect, it } from 'vitest'

import { parseBackendWorkerDiagnostics } from './backend-worker-diagnostics'

describe('parseBackendWorkerDiagnostics', () => {
  it('parses the active topology and exact profile heartbeats', () => {
    const result = parseBackendWorkerDiagnostics({
      health: 'degraded',
      topology_id: 'amvision-backend-workers',
      topology_generation: 7,
      topology_epoch_id: 'worker-topology-epoch-7',
      topology_state: 'running',
      activated_at: '2026-08-20T10:00:00Z',
      worker_count: 2,
      running_count: 1,
      workers: [
        {
          profile_id: 'training',
          display_name: 'Training Worker',
          health: 'running',
          process_id: 301,
          heartbeat_age_seconds: 0.4,
          enabled_consumer_kinds: ['model-training'],
          max_concurrent_tasks: 1,
        },
        {
          profile_id: 'conversion',
          display_name: 'Conversion Worker',
          health: 'stale',
          reason: 'heartbeat_stale',
          enabled_consumer_kinds: ['model-conversion'],
          max_concurrent_tasks: 2,
        },
      ],
    })

    expect(result.topologyGeneration).toBe(7)
    expect(result.profiles).toHaveLength(2)
    expect(result.profiles[0]).toMatchObject({
      profileId: 'training',
      health: 'running',
      processId: 301,
      enabledConsumerKinds: ['model-training'],
    })
    expect(result.profiles[1]).toMatchObject({
      profileId: 'conversion',
      health: 'stale',
      reason: 'heartbeat_stale',
    })
  })

  it('returns an explicit offline topology for a missing payload', () => {
    expect(parseBackendWorkerDiagnostics(undefined)).toEqual({
      health: 'offline',
      topologyId: null,
      topologyGeneration: null,
      topologyEpochId: null,
      topologyState: null,
      activatedAt: null,
      workerCount: 0,
      runningCount: 0,
      profiles: [],
    })
  })
})
