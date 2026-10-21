import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from '@/shared/api/http-client'
import {
  getModelConversionTaskDetail, getModelTrainingTaskDetail,
  getModelTrainingOutputFileDetail, listModelTrainingOutputFiles,
} from '@/modules/models/services/model.service'

vi.mock('@/shared/api/http-client', () => ({ apiRequest: vi.fn() }))
beforeEach(() => vi.clearAllMocks())

describe('model task read cancellation', () => {
  it.each([
    ['training detail', (signal: AbortSignal) => getModelTrainingTaskDetail('classification', 'a', signal)],
    ['conversion detail', (signal: AbortSignal) => getModelConversionTaskDetail('classification', 'a', signal)],
    ['file list', (signal: AbortSignal) => listModelTrainingOutputFiles('classification', 'a', signal)],
    ['file content', (signal: AbortSignal) => getModelTrainingOutputFileDetail('classification', 'a', 'metrics', signal)],
  ] as const)('forwards the %s signal to the existing HTTP client', async (_name, read) => {
    const controller = new AbortController()
    await read(controller.signal)
    expect(apiRequest).toHaveBeenCalledWith(expect.stringContaining('/a'), { signal: controller.signal })
  })
})
