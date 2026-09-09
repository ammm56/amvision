import { beforeEach, expect, it, vi } from 'vitest'
import { loadPreviewDisplayResult } from './previewDisplayResults'
import { useWorkflowPreviewDisplays } from './useWorkflowPreviewDisplays'
import { flushPromises } from '@vue/test-utils'
import type { WorkflowPreviewRun } from '../types'

const io = vi.hoisted(() => ({ request: vi.fn(), legacy: vi.fn(), image: vi.fn() }))
vi.mock('@/shared/api/http-client', () => ({ apiRequest: io.request }))
vi.mock('../services/workflow-runtime.service', () => ({ getWorkflowPreviewRun: io.legacy,
  readProjectObjectContentBlob: io.image, readWorkflowPreviewRunArtifactBlob: io.image }))
vi.mock('@/platform/i18n', () => ({ translate: (key: string) => key }))
const run = { preview_run_id: 'run', project_id: 'p', state: 'cancelled', node_records: [] } as unknown as WorkflowPreviewRun
const descriptor = (i: number) => ({ display_id: `${i}`, node_id: `n${i}`, node_type_id: 'custom.display', output_port: 'body', duration_ms: 1 })
const manifest = (count = 1) => ({ format_id: 'amvision.workflow-preview-displays.v1', preview_run_id: 'run', displays: Array.from({length:count}, (_,i)=>descriptor(i)) })
beforeEach(() => { vi.resetAllMocks() })

it('loads legacy results only when explicitly declared by the server', async () => {
  io.request.mockResolvedValue({ ...manifest(0), legacy: true })
  io.legacy.mockResolvedValue(run)
  expect((await loadPreviewDisplayResult(run, new AbortController().signal)).run).toBe(run)
  io.request.mockRejectedValueOnce(new Error('permission denied'))
  await expect(loadPreviewDisplayResult(run, new AbortController().signal)).rejects.toThrow('permission denied')
  expect(io.legacy).toHaveBeenCalledTimes(1)
})

it('limits node result requests to four and preserves other values after one fails', async () => {
  let active = 0, maximum = 0
  io.request.mockImplementation(async (path: string) => {
    if (path.endsWith('/displays')) return manifest(12)
    active++
    maximum = Math.max(maximum, active)
    await new Promise(resolve => setTimeout(resolve, 2))
    active--
    if (path.endsWith('/3')) throw new Error('missing asset')
    return { type: 'value-preview', value: false }
  })
  const result = await loadPreviewDisplayResult(run, new AbortController().signal)
  expect(maximum).toBe(4)
  expect(result.errors).toEqual(['n3: missing asset'])
  expect(result.run.node_records).toHaveLength(11)
  const displays = useWorkflowPreviewDisplays()
  await displays.refreshPreviewNodeDisplays(result.run)
  expect(displays.getPreviewNodeDisplay('n0')?.payload.value).toBe(false)
})

it('merges the display into the original record without doubling durations', async () => {
  io.request.mockImplementation(async (path:string) => path.endsWith('/displays') ? manifest(1) : {type:'value-preview',value:42})
  const original = {...run,node_records:[{node_id:'n0',node_type_id:'custom.display',duration_ms:3,inputs:{},outputs:{body:{type:'value-preview',value:'redacted'}},runtime_kind:'python-callable'}]}
  const result = await loadPreviewDisplayResult(original,new AbortController().signal)
  expect(result.run.node_records).toHaveLength(1)
  expect(result.run.node_records[0]?.duration_ms).toBe(3)
  expect(result.run.node_records[0]?.outputs).toEqual({body:{type:'value-preview',value:42}})
  expect(original.node_records[0]?.outputs.body.value).toBe('redacted')
})

it.each([0, false, null, '', { a: [1, 2] }])('renders complete value %j without a truthiness fallback', async (value) => {
  const displays = useWorkflowPreviewDisplays()
  await displays.refreshDisplayOutputs(run, [{ nodeId: 'n', nodeTypeId: 'custom.display', outputName: 'body', payload: {type:'value-preview',value} }])
  expect(displays.getPreviewNodeDisplay('n')?.payload.value).toEqual(value)
})

it('does not fetch a storage source image until the viewer is opened', async () => {
  const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:source')
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  io.image.mockResolvedValue(new Blob(['source']))
  const displays = useWorkflowPreviewDisplays()
  await displays.refreshDisplayOutputs(run, [{ nodeId: 'image', nodeTypeId:'custom.image', outputName:'body', payload:{type:'image-preview',image:{
    source_width:9000,source_height:6000,display_scale:0.1,
    display_image:{image_base64:'aW1hZ2U=',width:900,height:600},
    source_image:{transport_kind:'storage-ref',object_key:'projects/p/source.png',width:9000,height:6000},
  }}}])
  expect(io.image).not.toHaveBeenCalled()
  const image = displays.getPreviewNodeDisplay('image')!.image!
  expect(image.sourceWidth).toBe(9000)
  displays.openImageViewer(image)
  await flushPromises()
  expect(io.image).toHaveBeenCalledTimes(1)
  expect(displays.activeImageViewer.value?.sourceSrc).toBe('blob:source')
  displays.closeImageViewer()
  await displays.refreshDisplayOutputs(run, [], {reopenImageViewerNodeId:'image'})
  expect(displays.activeImageViewer.value).toBeNull()
  expect(revoke).toHaveBeenCalledWith('blob:source')
  create.mockRestore(); revoke.mockRestore()
})

it('does not publish stale images after the document identity changes', async () => {
  const displays = useWorkflowPreviewDisplays()
  let current = true
  let finish!: (blob: Blob) => void
  io.image.mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
  const create = vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:stale')
  const revoke = vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined)
  const result = displays.refreshDisplayOutputs(run, [{nodeId:'n',nodeTypeId:'custom.display',outputName:'body',payload:{type:'image-preview',image:{transport_kind:'storage-ref',object_key:'projects/p/image.png'}}}], {isCurrent:()=>current})
  current = false
  finish(new Blob(['image']))
  await result
  expect(displays.getPreviewNodeDisplay('n')).toBeNull()
  expect(revoke).toHaveBeenCalledWith('blob:stale')
  create.mockRestore(); revoke.mockRestore()
})
