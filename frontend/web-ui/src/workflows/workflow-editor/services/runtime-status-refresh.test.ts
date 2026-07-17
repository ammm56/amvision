import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { WorkflowTriggerSource } from '@/modules/integrations/services/trigger-source.service'
import {
  refreshWorkflowTriggerSourceStatuses,
} from '@/modules/integrations/services/trigger-source.service'
import type { WorkflowAppRuntime } from '../types'
import { refreshWorkflowAppRuntimeStatuses } from './workflow-runtime.service'

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }))

vi.mock('@/shared/api/http-client', () => ({
  apiRequest,
  apiRequestWithHeaders: vi.fn(),
}))

function runtime(id: string, observedState = 'running'): WorkflowAppRuntime {
  return {
    workflow_runtime_id: id,
    observed_state: observedState,
    health_summary: { cached: true },
  } as unknown as WorkflowAppRuntime
}

function triggerSource(id: string, observedState = 'running'): WorkflowTriggerSource {
  return {
    trigger_source_id: id,
    observed_state: observedState,
    health_summary: { cached: true },
  } as unknown as WorkflowTriggerSource
}

describe('runtime status refresh', () => {
  beforeEach(() => {
    apiRequest.mockReset()
  })

  it('uses runtime health responses and marks failed refreshes as unknown', async () => {
    apiRequest.mockImplementation((path: string) => path.includes('runtime-ok')
      ? Promise.resolve(runtime('runtime-ok', 'stopped'))
      : Promise.reject(new Error('worker unavailable')))

    const result = await refreshWorkflowAppRuntimeStatuses([
      runtime('runtime-ok'),
      runtime('runtime-failed'),
    ])

    expect(result.items.map((item) => item.observed_state)).toEqual(['stopped', 'unknown'])
    expect(result.items[1]?.last_error).toContain('worker unavailable')
    expect(result.failedRuntimeIds).toEqual(['runtime-failed'])
  })

  it('merges TriggerSource health and never retains stale running after a refresh failure', async () => {
    apiRequest.mockImplementation((path: string) => path.includes('trigger-ok')
      ? Promise.resolve({
          trigger_source_id: 'trigger-ok',
          enabled: false,
          desired_state: 'stopped',
          observed_state: 'stopped',
          last_triggered_at: null,
          last_error: null,
          health_summary: { adapter_running: false },
        })
      : Promise.reject(new Error('adapter unavailable')))

    const result = await refreshWorkflowTriggerSourceStatuses([
      triggerSource('trigger-ok'),
      triggerSource('trigger-failed'),
    ])

    expect(result.items.map((item) => item.observed_state)).toEqual(['stopped', 'unknown'])
    expect(result.items[0]?.health_summary).toEqual({ adapter_running: false })
    expect(result.items[1]?.last_error).toContain('adapter unavailable')
    expect(result.failedTriggerSourceIds).toEqual(['trigger-failed'])
    expect(Object.keys(result.healthByTriggerSourceId)).toEqual(['trigger-ok'])
  })
})
