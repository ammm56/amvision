import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { decodeCloudPreview, rendererUsage, reserveGpu } from '@/workflows/workflow-editor/point-cloud/preview-data'

const policy = { max_points: 100, max_data_bytes: 8192, max_cpu_bytes: 65536, max_gpu_bytes: 65536, max_canvas_pixels: 65536, max_position_error: .0001 }
beforeEach(async () => { const {webcrypto} = await vi.importActual<{webcrypto: Crypto}>('node:crypto'); vi.stubGlobal('crypto', webcrypto) })
afterEach(() => { expect(rendererUsage()).toEqual({cpuBytes: 0, gpuBytes: 0}); vi.unstubAllGlobals() })

export async function body(scalar = false) {
  const raw = new Uint8Array(scalar ? 56 : 40), view = new DataView(raw.buffer)
  ;[0, 1, 2, 3, 4, 5].forEach((v, i) => view.setFloat32(i * 4, v, true))
  view.setBigUint64(24, 0n, true); view.setBigUint64(32, 99n, true)
  const fields = [
    { name: 'positions', dtype: 'float32', components: 3, count: 2, offset: 0, byte_length: 24 },
    { name: 'source_indices', dtype: 'uint64', components: 1, count: 2, offset: 24, byte_length: 16 },
  ]
  if (scalar) {
    view.setBigUint64(40, 18446744073709551614n, true); view.setBigUint64(48, 18446744073709551615n, true)
    fields.push({ name: 'scalar', dtype: 'uint64', components: 1, count: 2, offset: 40, byte_length: 16 })
  }
  return { type: 'point-cloud-preview', format_id: 'amvision.point-cloud-preview.v1', state: 'ready',
    display_point_count: 2, source_point_count: 100, render_origin: [1.5, 2.5, 3.5], bounds: {min:[0,1,2],max:[3,4,5]},
    data: { encoding: 'base64', content_length: raw.length, content: btoa(String.fromCharCode(...raw)), fields, checksum_algorithm: 'sha256', checksum: [...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(b=>b.toString(16).padStart(2,'0')).join('') },
    color: scalar ? { mode: 'scalar', field: 'label', component: 0, min: '18446744073709551614', max: '18446744073709551615', invalid_count: 0 } : {mode:'solid'},
  }
}
it('keeps original coordinates and original source indices after local float32 rendering', async () => {
  const data = await decodeCloudPreview(await body(), policy, new AbortController().signal)
  try { expect(data.point(1)).toEqual({sourceIndex:'99', xyz:[3,4,5],scalar:null}); expect([...data.positions]).toEqual([-1.5,-1.5,-1.5,1.5,1.5,1.5]) }
  finally { data.dispose(); data.dispose() }
})
it('normalizes adjacent uint64 values without collapsing them through Number', async () => {
  const data = await decodeCloudPreview(await body(true), policy, new AbortController().signal)
  try { expect(data.point(1).scalar).toBe('18446744073709551615'); expect(data.colors[0]).toBe(0); expect(data.colors[3]).toBe(1) }
  finally { data.dispose() }
})
it.each(['checksum', 'overlap', 'count', 'dtype', 'extra-field', 'bounds'])('rejects invalid %s and returns CPU budget', async fault => {
  const input = await body()
  if (fault === 'checksum') input.data.checksum = '0'.repeat(64)
  if (fault === 'overlap') input.data.fields[1]!.offset = 0
  if (fault === 'count') input.data.fields[0]!.count = 3
  if (fault === 'dtype') input.data.fields[0]!.dtype = 'uint32'
  if (fault === 'extra-field') input.data.fields.push(input.data.fields[0]!)
  if (fault === 'bounds') input.bounds.min[0] = -1
  await expect(decodeCloudPreview(input, policy, new AbortController().signal)).rejects.toThrow()
})
it('returns reservations after cancellation and refuses aggregate GPU overflow', async () => {
  const abort = new AbortController(); const promise = decodeCloudPreview(await body(), policy, abort.signal); abort.abort()
  await expect(promise).rejects.toThrow()
  const release = reserveGpu(40000, policy)
  try { expect(() => reserveGpu(40000, policy)).toThrow('cloud_gpu_capacity') }
  finally { release(); release() }
})
it('does not allocate when capacity or policy is missing', async () => {
  await expect(decodeCloudPreview(await body(), {...policy,max_cpu_bytes:1}, new AbortController().signal)).rejects.toThrow('cloud_cpu_capacity')
  await expect(decodeCloudPreview(await body(), {...policy,max_position_error:0}, new AbortController().signal)).rejects.toThrow('cloud_renderer_unconfigured')
})
