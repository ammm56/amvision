import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from '@/shared/api/http-client'
import { inferTaskDeployment, type TaskInferenceDebugInput } from './inference.service'

vi.mock('@/shared/api/http-client', () => ({ apiRequest: vi.fn() }))

function input(overrides: Partial<TaskInferenceDebugInput>): TaskInferenceDebugInput {
  return {
    taskType: 'detection',
    projectId: 'project-1',
    deploymentInstanceId: 'deployment-1',
    inputUri: 'images/input.jpg',
    inputTransportMode: 'memory',
    scoreThreshold: 0.31,
    topK: 7,
    maskThreshold: 0.52,
    keypointConfidenceThreshold: 0.27,
    saveResultImage: false,
    returnPreviewImageBase64: true,
    ...overrides,
  }
}

async function submittedFormData(overrides: Partial<TaskInferenceDebugInput>): Promise<FormData> {
  vi.mocked(apiRequest).mockResolvedValue({} as never)
  await inferTaskDeployment(input(overrides))
  const options = vi.mocked(apiRequest).mock.calls.at(-1)?.[1]
  expect(options?.body).toBeInstanceOf(FormData)
  return options?.body as FormData
}

describe('inference service task-native parameters', () => {
  beforeEach(() => vi.clearAllMocks())

  it('sends only top_k for classification', async () => {
    const body = await submittedFormData({ taskType: 'classification' })

    expect(body.get('top_k')).toBe('7')
    expect(body.has('score_threshold')).toBe(false)
    expect(body.has('mask_threshold')).toBe(false)
  })

  it('sends score and mask thresholds for segmentation', async () => {
    const body = await submittedFormData({ taskType: 'segmentation' })

    expect(body.get('score_threshold')).toBe('0.31')
    expect(body.get('mask_threshold')).toBe('0.52')
    expect(body.has('top_k')).toBe(false)
  })

  it('sends score and keypoint thresholds for pose', async () => {
    const body = await submittedFormData({ taskType: 'pose' })

    expect(body.get('score_threshold')).toBe('0.31')
    expect(body.get('keypoint_confidence_threshold')).toBe('0.27')
  })

  it.each(['detection', 'obb'] as const)('sends only score threshold for %s', async (taskType) => {
    const body = await submittedFormData({ taskType })

    expect(body.get('score_threshold')).toBe('0.31')
    expect(body.has('top_k')).toBe(false)
    expect(body.has('mask_threshold')).toBe(false)
    expect(body.has('keypoint_confidence_threshold')).toBe(false)
  })
})
