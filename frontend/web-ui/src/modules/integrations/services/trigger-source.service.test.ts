import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequestWithHeaders } from '@/shared/api/http-client'
import {
  listAllWorkflowTriggerSourcesForRuntime,
  type WorkflowTriggerSource,
} from './trigger-source.service'

vi.mock('@/shared/api/http-client', () => ({
  apiRequest: vi.fn(),
  apiRequestWithHeaders: vi.fn(),
}))

function source(index: number): WorkflowTriggerSource {
  return {
    trigger_source_id: `trigger-${index}`,
    workflow_runtime_id: 'runtime-1',
  } as WorkflowTriggerSource
}

function headers(offset: number, hasMore: boolean, nextOffset: number | null): Headers {
  const values: Record<string, string> = {
    'x-offset': String(offset),
    'x-limit': '100',
    'x-total-count': '101',
    'x-has-more': String(hasMore),
  }
  if (nextOffset !== null) values['x-next-offset'] = String(nextOffset)
  return new Headers(values)
}

describe('TriggerSource list filters', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads every TriggerSource for one exact Runtime across more than 100 records', async () => {
    vi.mocked(apiRequestWithHeaders)
      .mockResolvedValueOnce({
        payload: Array.from({ length: 100 }, (_, index) => source(index)),
        headers: headers(0, true, 100),
      } as never)
      .mockResolvedValueOnce({
        payload: [source(100)],
        headers: headers(100, false, null),
      } as never)

    const result = await listAllWorkflowTriggerSourcesForRuntime('project one', 'runtime/one')

    expect(result).toHaveLength(101)
    expect(vi.mocked(apiRequestWithHeaders)).toHaveBeenNthCalledWith(1, '/workflows/trigger-sources', {
      query: {
        project_id: 'project one',
        workflow_runtime_id: 'runtime/one',
        offset: 0,
        limit: 100,
      },
    })
    expect(vi.mocked(apiRequestWithHeaders)).toHaveBeenNthCalledWith(2, '/workflows/trigger-sources', {
      query: {
        project_id: 'project one',
        workflow_runtime_id: 'runtime/one',
        offset: 100,
        limit: 100,
      },
    })
  })
})
