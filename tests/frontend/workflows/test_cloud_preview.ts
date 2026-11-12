import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { decodeCloudPreview, decodePreviewBytes, rendererUsage, reserveGpu } from '@/workflows/workflow-editor/point-cloud/preview-data'

const policy = { max_points: 100, max_data_bytes: 8192, max_cpu_bytes: 65536, max_gpu_bytes: 65536, max_canvas_pixels: 65536, max_position_error: .0001 }
beforeEach(async () => { const {webcrypto} = await vi.importActual<{webcrypto: Crypto}>('node:crypto'); vi.stubGlobal('crypto', webcrypto) })
afterEach(() => { expect(rendererUsage()).toEqual({cpuBytes: 0, gpuBytes: 0}); vi.unstubAllGlobals() })

it.each([false,true])('keeps normal state separate from position validity, corrupt=%s',async corrupt=>{
  const input=await body(),raw=new Uint8Array(70),view=new DataView(raw.buffer)
  raw.set(Uint8Array.from(atob(input.data.content),c=>c.charCodeAt(0)))
  view.setFloat32(48,1,true)
  raw.set([1,0,1,0,0,2],64)
  if(corrupt)view.setFloat32(48,0,true)
  input.data.fields.push(...[
    {name:'normals',dtype:'float32',components:3,count:2,offset:40,byte_length:24},
    ...['normal_valid','normal_oriented','normal_reason'].map((name,i)=>({name,dtype:'uint8',components:1,count:2,offset:64+i*2,byte_length:2})),
  ])
  input.data.content_length=70;input.data.content=btoa(String.fromCharCode(...raw));input.data.checksum=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(b=>b.toString(16).padStart(2,'0')).join('')
  const spatial={frame_id:'sensor',length_unit:'mm'},payload={...input,spatial,normal_info:{...spatial,method:{method_id:'estimate-normals',method_version:1},orientation:{kind:'direction'}}}
  if(corrupt){await expect(decodeCloudPreview(payload,policy,new AbortController().signal)).rejects.toThrow();return}
  const display=await decodeCloudPreview(payload,policy,new AbortController().signal)
  try{expect(display.point(0).normal).toEqual({vector:[0,0,1],valid:true,oriented:true,reason:0});expect(display.point(1).normal).toEqual({vector:[0,0,0],valid:false,oriented:false,reason:2});expect(display.count).toBe(2)}finally{display.dispose()}
})

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
    display_point_count: 2, point_count: 100, vertex_kind: 'source', source_point_count: 100, render_origin: [1.5, 2.5, 3.5], bounds: {min:[0,1,2],max:[3,4,5]},
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

it('validates multi-megabyte base64 without regex stack overflow and releases on checksum failure',async()=>{
  const input=await body()
  input.data.content='AAAA'.repeat(4_000_000);input.data.content_length=12_000_000
  await expect(decodeCloudPreview(input,{...policy,max_data_bytes:12_000_000,max_cpu_bytes:100_000_000},new AbortController().signal)).rejects.toThrow('cloud_preview_checksum')
})

it('allows cancellation between decode blocks and releases the complete reservation',async()=>{
  const input=await body(),controller=new AbortController()
  input.data.content='AAAA'.repeat(4_000_000);input.data.content_length=12_000_000
  const timer=setTimeout(()=>controller.abort(new Error('cancelled-during-decode')),0)
  try{
    await expect(decodeCloudPreview(input,{...policy,max_data_bytes:12_000_000,max_cpu_bytes:100_000_000},controller.signal)).rejects.toThrow('cancelled-during-decode')
  }finally{clearTimeout(timer)}
})

it.each([196608,196609,196610])('keeps all bytes and padding across a Base64 block boundary (%i bytes)',async size=>{
  const raw=Uint8Array.from({length:size},(_,i)=>i%251)
  const content=btoa(Array.from(raw,value=>String.fromCharCode(value)).join(''))
  const checksum=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(b=>b.toString(16).padStart(2,'0')).join('')
  const decoded=await decodePreviewBytes({content_length:size,content,encoding:'base64',checksum_algorithm:'sha256',checksum},new AbortController().signal)
  expect(decoded.length).toBe(raw.length)
  expect(decoded.every((value,index)=>value===raw[index])).toBe(true)
})

it.each(['source','generated'])('decodes ordered %s identities without conflating generated vertices with source rows',async kind=>{
  const input=await body(),raw=Uint8Array.from(atob(input.data.content),c=>c.charCodeAt(0)),view=new DataView(raw.buffer)
  input.vertex_kind=kind
  if(kind==='source'){view.setBigUint64(24,99n,true);view.setBigUint64(32,0n,true)}
  else{input.point_count=2;input.data.fields[1]!.name='vertex_indices';view.setBigUint64(24,0n,true);view.setBigUint64(32,1n,true)}
  input.data.content=btoa(String.fromCharCode(...raw));input.data.checksum=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(b=>b.toString(16).padStart(2,'0')).join('')
  const data=await decodeCloudPreview(input,policy,new AbortController().signal)
  try{if(kind==='source'){expect(data.point(0).sourceIndex).toBe('99');expect(data.point(1).sourceIndex).toBe('0')}else{expect(data.point(1).sourceIndex).toBeNull();expect(data.point(1).vertexIndex).toBe('1')}}finally{data.dispose()}
})

it('keeps voxel keys and complete member counts separate from original row identity',async()=>{
  const input=await body(),raw=new Uint8Array(104),view=new DataView(raw.buffer)
  raw.set(Uint8Array.from(atob(input.data.content),c=>c.charCodeAt(0)))
  input.vertex_kind='generated';input.point_count=2;input.data.fields[1]!.name='vertex_indices'
  view.setBigUint64(32,1n,true)
  ;[-2n,0n,1n,4n,5n,6n].forEach((v,i)=>view.setBigInt64(40+i*8,v,true))
  view.setBigUint64(88,10n,true);view.setBigUint64(96,20n,true)
  input.data.fields.push({name:'voxel_keys',dtype:'int64',components:3,count:2,offset:40,byte_length:48},
    {name:'member_counts',dtype:'uint64',components:1,count:2,offset:88,byte_length:16})
  input.data.content_length=104;input.data.content=btoa(String.fromCharCode(...raw))
  input.data.checksum=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(b=>b.toString(16).padStart(2,'0')).join('')
  const voxel_aggregation={method_id:'resample-cloud',method_version:1,parameters:{settings:{kind:'voxel-centroid',grid_origin:[0,0,0],voxel_size:1,frame_id:'original',length_unit:'mm'}}}
  const data=await decodeCloudPreview({...input,lineage_kind:'voxel-aggregate',voxel_aggregation,voxel_grid:{origin:[0,0,0],axes:[[1,0,0],[0,1,0],[0,0,1]]}},policy,new AbortController().signal)
  try{expect(data.point(0)).toMatchObject({sourceIndex:null,vertexIndex:'0',voxelKey:['-2','0','1'],memberCount:'10',voxelFrame:'original',voxelUnit:'mm'})}finally{data.dispose()}
  await expect(decodeCloudPreview({...input,lineage_kind:'voxel-aggregate'},policy,new AbortController().signal)).rejects.toThrow()
  await expect(decodeCloudPreview({...input,lineage_kind:'voxel-aggregate',vertex_kind:'source'},policy,new AbortController().signal)).rejects.toThrow()
})
