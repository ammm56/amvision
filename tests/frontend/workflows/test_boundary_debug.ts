import { afterEach, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { Scene, PerspectiveCamera, Raycaster, Vector3 } from 'three'
import { decodeBoundaryDebug } from '@/workflows/workflow-editor/point-cloud/boundary-debug'
import {
  rendererUsage,
  decodeCloudPreview,
} from '@/workflows/workflow-editor/point-cloud/preview-data'
import { createGeometryOverlay } from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import BoundaryDebugSummary from '@/workflows/workflow-editor/point-cloud/BoundaryDebugSummary.vue'

const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
  'node:crypto',
)
const { readFileSync } = await vi.importActual<{
  readFileSync: (path: string, encoding: 'utf8') => string
}>('node:fs')
const { env } = await vi.importActual<{
  env: Record<string, string | undefined>
}>('node:process')
vi.stubGlobal('crypto', webcrypto)
const policy = {
  max_points: 1_000_000,
  max_data_bytes: 64 * 1024 ** 2,
  max_cpu_bytes: 512 * 1024 ** 2,
  max_gpu_bytes: 256 * 1024 ** 2,
  max_canvas_pixels: 4_000_000,
  max_position_error: 0.001,
}
afterEach(() => expect(rendererUsage()).toEqual({ cpuBytes: 0, gpuBytes: 0 }))
async function payload() {
  const specs: [string, string, number[]][] = [
    ['input_source_indices', 'uint64', [4, 7]],
    ['counts', 'uint64', [1, 1, 0, 0]],
    ['heights', 'float64', [2, 3, 0, 0]],
    ['spread', 'float64', [0, 0, 0, 0]],
    ['usable', 'uint8', [1, 1, 0, 0]],
    ['foreground', 'uint8', [1, 0, 0, 0]],
    ['selected', 'uint8', [1, 0, 0, 0]],
    ['grouped', 'uint8', [1, 0, 0, 1]],
    ['components', 'int64', [1, 0, 0, 1]],
    ['bin_rows', 'int64', [0, 1]],
  ]
  const chunks: Uint8Array[] = [],
    fields: Record<string, unknown>[] = []
  let end = 0
  for (const [name, dtype, values] of specs) {
    const width = dtype === 'uint8' ? 1 : 8,
      offset = Math.ceil(end / width) * width,
      b = new Uint8Array(values.length * width),
      view = new DataView(b.buffer)
    for (let i = 0; i < values.length; i++) {
      if (dtype === 'uint8') view.setUint8(i, values[i]!)
      else if (dtype === 'float64') view.setFloat64(i * 8, values[i]!, true)
      else if (dtype === 'int64')
        view.setBigInt64(i * 8, BigInt(values[i]!), true)
      else view.setBigUint64(i * 8, BigInt(values[i]!), true)
    }
    chunks.push(new Uint8Array(offset - end), b)
    fields.push({
      name,
      dtype,
      components: 1,
      count: values.length,
      offset,
      byte_length: b.length,
    })
    end = offset + b.length
  }
  const binary = new Uint8Array(end)
  let cursor = 0
  for (const chunk of chunks) {
    binary.set(chunk, cursor)
    cursor += chunk.length
  }
  const digest = new Uint8Array(
    await webcrypto.subtle.digest('SHA-256', binary),
  )
  const evaluation = {
      frame_id: 'camera',
      length_unit: 'mm',
      origin: [0, 0, 0],
      rotation: [
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
      ],
    },
    hash = 'a'.repeat(64)
  return {
    state: 'ready',
    observation_id: 'o',
    display_point_count: 2,
    source_point_count: 10,
    spatial: { frame_id: 'camera', length_unit: 'mm' },
    data: { content_length: 24 },
    geometry: {
      curves: [
        {
          kind: 'boundary',
          feature_id: 'f',
          reason: null,
          method: { parameters_sha256: hash, resolution: { evaluation } },
        },
      ],
    },
    boundary_debug: [
      {
        format_id: 'amvision.boundary-debug.v1',
        identity: {
          format_id: 'amvision.boundary-debug-ref.v1',
          capture_id: 'c',
          run_id: 'r',
          node_id: 'n',
          invocation_id: 'i',
          observation_id: 'o',
          feature_id: 'f',
          parameters_sha256: hash,
        },
        state: 'ready',
        reason: null,
        stage: 'complete',
        selection_complete: true,
        measurement_reason: null,
        evaluation,
        grid: {
          origin: [0, 0],
          step: 1,
          shape: [2, 2],
          seed_min: [0, 0],
          seed_max: [1, 1],
          selection: 'grid-connected',
          selected_component: 1,
        },
        target_ids: [],
        data: {
          encoding: 'base64',
          checksum_algorithm: 'sha256',
          checksum: Array.from(digest, (b) =>
            b.toString(16).padStart(2, '0'),
          ).join(''),
          content_length: binary.length,
          content: btoa(String.fromCharCode(...binary)),
          fields,
        },
      },
    ],
  }
}
it('reads all cells with original rows; empty and closing cells are not measured heights', async () => {
  const [d] = await decodeBoundaryDebug(
    await payload(),
    policy,
    new AbortController().signal,
  )
  try {
    expect(d!.arrays.counts!.count).toBe(4)
    expect(d!.arrays.input_source_indices!.get(1)).toBe(7)
    expect(d!.arrays.grouped!.get(3)).toBe(1)
    expect(d!.arrays.selected!.get(3)).toBe(0)
  } finally {
    d!.dispose()
  }
})
it.each(['identity', 'digest', 'layout', 'budget', 'cancel'])(
  'rejects %s and releases allocations',
  async (mode) => {
    const p = await payload(),
      abort = new AbortController()
    if (mode === 'identity')
      p.boundary_debug[0]!.identity.observation_id = 'other'
    if (mode === 'digest') p.boundary_debug[0]!.data.checksum = '0'.repeat(64)
    if (mode === 'layout') p.boundary_debug[0]!.data.fields[0]!.count = 500
    if (mode === 'cancel') abort.abort()
    await expect(
      decodeBoundaryDebug(
        p,
        {
          ...policy,
          max_cpu_bytes: mode === 'budget' ? 1 : policy.max_cpu_bytes,
        },
        abort.signal,
      ),
    ).rejects.toThrow()
  },
)
it('links full grid faces to cell rows and reclaims overlay GPU/CPU buffers', async () => {
  const [d] = await decodeBoundaryDebug(
      await payload(),
      policy,
      new AbortController().signal,
    ),
    scene = new Scene(),
    canvas = document.createElement('canvas'),
    picked = vi.fn()
  const overlay = createGeometryOverlay(
    scene,
    new PerspectiveCamera(),
    canvas,
    [0, 0, 0],
    policy,
    () => {},
    () => {},
    () => {},
  )
  try {
    overlay.update({
      payload: { spatial: { frame_id: 'camera', length_unit: 'mm' } },
      debug: d,
      debugLayers: {
        grid: true,
        profiles: false,
        candidates: false,
        partition: false,
      },
      debugSelected: picked,
    })
    const ray = new Raycaster(new Vector3(0.4, 0.3, 5), new Vector3(0, 0, -1))
    scene.updateMatrixWorld(true)
    expect(overlay.pick(ray)).toBe(true)
    expect(picked).toHaveBeenLastCalledWith({ kind: 'cell', index: 0 })
    expect(overlay.focus('debug')).not.toBeNull()
    scene.traverse((node) => {
      if (node.userData.debug?.kind === 'cell')
        expect((node as import('three').Mesh).material).toMatchObject({
          depthTest: false,
        })
    })
  } finally {
    overlay.dispose()
    d!.dispose()
  }
})
it('keeps base evidence when optional debug GPU allocation fails', async () => {
  const [d] = await decodeBoundaryDebug(
      await payload(),
      policy,
      new AbortController().signal,
    ),
    scene = new Scene(),
    failed = vi.fn()
  const overlay = createGeometryOverlay(
    scene,
    new PerspectiveCamera(),
    document.createElement('canvas'),
    [0, 0, 0],
    { ...policy, max_gpu_bytes: 1 },
    () => {},
    () => {},
    () => {},
  )
  try {
    expect(() =>
      overlay.update({
        payload: { spatial: {} },
        debug: d,
        debugLayers: {
          grid: true,
          profiles: false,
          candidates: false,
          partition: false,
        },
        debugFailed: failed,
      }),
    ).not.toThrow()
    expect(failed).toHaveBeenCalledOnce()
  } finally {
    overlay.dispose()
    d!.dispose()
  }
})
it('paginates selected rows without rendering one DOM row per cell', async () => {
  const [d] = await decodeBoundaryDebug(
    await payload(),
    policy,
    new AbortController().signal,
  )
  const wrapper = mount(BoundaryDebugSummary, {
    props: {
      items: [d!],
      selectedId: 'c',
      layers: {
        grid: true,
        profiles: true,
        candidates: true,
        partition: false,
      },
      selection: null,
      error: '',
    },
    global: { plugins: [createI18n({ legacy: false, locale: 'en-US' })] },
  })
  try {
    expect(wrapper.findAll('tbody tr')).toHaveLength(4)
    await wrapper.get('tbody button').trigger('click')
    expect(wrapper.emitted('pick')?.[0]).toEqual([{ kind: 'cell', index: 0 }])
    await wrapper.setProps({ selection: { kind: 'cell', index: 3 } })
    expect(wrapper.get('tr.selected').text()).toContain('h=-')
  } finally {
    wrapper.unmount()
    d!.dispose()
  }
})
it.skipIf(!env.AMVISION_I2_DISPLAY)(
  'reopens the captured full-sample display without a live source cloud',
  async () => {
    const body = JSON.parse(readFileSync(env.AMVISION_I2_DISPLAY!, 'utf8'))
    const actualPolicy = {
      ...policy,
      max_data_bytes: 32 * 1024 ** 2,
      max_cpu_bytes: 128 * 1024 ** 2,
      max_gpu_bytes: 64 * 1024 ** 2,
    }
    const data = await decodeCloudPreview(
      body,
      actualPolicy,
      new AbortController().signal,
    )
    const records = await decodeBoundaryDebug(
      body,
      actualPolicy,
      new AbortController().signal,
    )
    const scene=new Scene()
    const overlay = createGeometryOverlay(
        scene,
        new PerspectiveCamera(),
        document.createElement('canvas'),
        data.origin,
        actualPolicy,
        () => {},
        () => {},
        () => {},
      ),
      failed = vi.fn()
    try {
      expect(records).toHaveLength(3)
      expect(records.every((r) => r.state === 'ready')).toBe(true)
      for (const d of records){
        overlay.update({
          payload: body,
          debug: d,
          debugLayers: {
            grid: true,
            profiles: true,
            candidates: true,
            partition: true,
          },
          debugFailed: failed,
        })
        const root=scene.children[0],usage=rendererUsage()
        for(let i=0;i<10;i++){overlay.activity(false);overlay.visibility(new Set(['hidden-leaf']));overlay.activity(true);overlay.visibility(new Set())}
        expect(scene.children[0]).toBe(root);expect(rendererUsage()).toEqual(usage)
      }
      expect(failed).not.toHaveBeenCalled()
    } finally {
      overlay.dispose()
      data.dispose()
      for (const d of records) d.dispose()
    }
  },
  60_000,
)

it('opens a candidates-only first capture and resets category when switching to a grid', async () => {
  const [d] = await decodeBoundaryDebug(
    await payload(),
    policy,
    new AbortController().signal,
  )
  const candidates = {
    ...d!,
    id: 'candidates',
    grid: null,
    arrays: {
      candidate_closed: { count: 45, components: 1, get: () => 0 },
      candidate_offsets: {
        count: 46,
        components: 1,
        get: (i: number) => i * 3,
      },
    },
  }
  const wrapper = mount(BoundaryDebugSummary, {
    props: {
      items: [candidates, d!],
      selectedId: 'candidates',
      layers: {
        grid: true,
        profiles: true,
        candidates: true,
        partition: false,
      },
      selection: null,
      error: '',
    },
    global: { plugins: [createI18n({ legacy: false, locale: 'en-US' })] },
  })
  try {
    expect(wrapper.findAll('tbody tr')).toHaveLength(20)
    expect(wrapper.get('tbody').text()).toContain('3 points')
    await wrapper.get('tbody button').trigger('click')
    expect(wrapper.emitted('pick')?.[0]).toEqual([
      { kind: 'candidate', index: 0 },
    ])
    await wrapper.setProps({ selection: { kind: 'candidate', index: 25 } })
    expect(wrapper.get('tr.selected button').text()).toBe('25')
    expect(wrapper.findAll('tbody tr')).toHaveLength(20)
    await wrapper.setProps({ selectedId: 'c', selection: null })
    expect(wrapper.findAll('tbody tr')).toHaveLength(4)
  } finally {
    wrapper.unmount()
    d!.dispose()
  }
})
