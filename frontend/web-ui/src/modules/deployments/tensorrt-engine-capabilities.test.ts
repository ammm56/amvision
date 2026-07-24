import { describe, expect, it } from 'vitest'

import {
  formatTensorRtShape,
  parseTensorRtEngineCapabilities,
} from './tensorrt-engine-capabilities'

describe('TensorRT engine capabilities', () => {
  it('parses dynamic multiple-profile metadata without using model names', () => {
    const capabilities = parseTensorRtEngineCapabilities({
      input_shape_mode: 'dynamic',
      optimization_profile_count: 2,
      optimization_profiles: [
        {
          index: 0,
          inputs: [
            {
              input_name: 'images',
              min_shape: [1, 3, 320, 320],
              opt_shape: [1, 3, 640, 640],
              max_shape: [4, 3, 640, 640],
            },
          ],
        },
        {
          index: 1,
          inputs: [
            {
              input_name: 'images',
              min_shape: [1, 3, 640, 640],
              opt_shape: [2, 3, 960, 960],
              max_shape: [8, 3, 1280, 1280],
            },
          ],
        },
      ],
    })

    expect(capabilities?.inputShapeMode).toBe('dynamic')
    expect(capabilities?.optimizationProfiles).toHaveLength(2)
    expect(capabilities?.optimizationProfiles[1]?.inputs[0]?.maxShape).toEqual([
      8,
      3,
      1280,
      1280,
    ])
    expect(formatTensorRtShape([1, 3, 640, 640])).toBe('1 × 3 × 640 × 640')
  })

  it('rejects partial, inconsistent, or invalid metadata', () => {
    expect(parseTensorRtEngineCapabilities({
      input_shape_mode: 'static',
    })).toBeNull()
    expect(parseTensorRtEngineCapabilities({
      input_shape_mode: 'dynamic',
      optimization_profile_count: 2,
      optimization_profiles: [],
    })).toBeNull()
    expect(parseTensorRtEngineCapabilities({
      input_shape_mode: 'dynamic',
      optimization_profile_count: 1,
      optimization_profiles: [
        {
          index: 0,
          inputs: [
            {
              input_name: 'images',
              min_shape: [4, 3, 640, 640],
              opt_shape: [2, 3, 640, 640],
              max_shape: [1, 3, 640, 640],
            },
          ],
        },
      ],
    })).toBeNull()
  })
})
