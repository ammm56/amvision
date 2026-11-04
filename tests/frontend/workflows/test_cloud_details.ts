import { afterEach, expect, it, vi } from 'vitest'
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto')
import { createDetailController } from '@/workflows/workflow-editor/point-cloud/detail-controller'
import { decodeDetailBlock, validateDetailIndex } from '@/workflows/workflow-editor/point-cloud/asset-details'
import { rendererUsage } from '@/workflows/workflow-editor/point-cloud/preview-data'
import type { DetailIndex, DetailBlock } from '@/workflows/workflow-editor/point-cloud/asset-details'
import { Scene, PointsMaterial } from 'three'
import { createDetailLayer } from '@/workflows/workflow-editor/point-cloud/detail-layer'

const policy={max_points:10,max_data_bytes:4096,max_cpu_bytes:65536,max_gpu_bytes:65536,max_canvas_pixels:10000,max_position_error:.0001}
vi.stubGlobal('crypto',webcrypto)
afterEach(()=>{vi.useRealTimers();expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})})

it('restores normal status from asset leaf records and rejects missing state',async()=>{
  const {index}=await sample(),raw=new ArrayBuffer(67),view=new DataView(raw)
  index.bounds.min.forEach((v,i)=>view.setFloat64(i*8,v,true));view.setBigUint64(24,2n**63n+1n,true)
  view.setFloat64(48,1,true);view.setUint8(56,1);view.setUint8(57,0);view.setUint8(58,0);view.setUint32(59,0,true);view.setUint32(63,7,true)
  const spatial={frame_id:'sensor',length_unit:'mm'}
  const full:DetailIndex={...index,spatial,normal_info:{...spatial,method:{method_id:'estimate-normals',method_version:1},orientation:{kind:'unoriented'}},fields:[...index.fields,{name:'normals',dtype:'float64',components:3,offset:32},...['normal_valid','normal_oriented','normal_reason'].map((name,i)=>({name,dtype:'uint8',components:1,offset:56+i}))],row_bytes:67,logical_offset:59,identity_offset:63,blocks:[{...index.blocks[0]!,byte_length:67,sha256:[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(b=>b.toString(16).padStart(2,'0')).join('')}]}
  validateDetailIndex(full,full.source,full.generation)
  const data=await decodeDetailBlock(raw,full,full.blocks[0]!,full.bounds.min,{mode:'solid'},policy,new AbortController().signal)
  try{expect(data.point(0).normal).toEqual({vector:[0,0,1],valid:true,oriented:false,reason:0})}finally{data.dispose()}
  expect(()=>validateDetailIndex({...full,fields:full.fields.filter(f=>f.name!=='normal_reason')},full.source,full.generation)).toThrow()
})

async function sample(){
  const raw=new ArrayBuffer(40),view=new DataView(raw)
  for(let c=0;c<3;c++)view.setFloat64(c*8,1000000+c+.125,true)
  view.setBigUint64(24,2n**63n+1n,true);view.setUint32(32,0,true);view.setUint32(36,7,true)
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),b=>b.toString(16).padStart(2,'0')).join('')
  const bounds={min:[1000000.125,1000001.125,1000002.125],max:[1000000.125,1000001.125,1000002.125]}
  const index:DetailIndex={format_id:'amvision.point-cloud-detail.v1',source:{project_id:'p',resource_id:'r',version:1,kind:'point-cloud',sha256:'a'.repeat(64)},generation:'b'.repeat(32),vertex_kind:'source',point_count:1,source_point_count:8,valid_count:1,excluded_count:0,bounds,
    fields:[{name:'positions',dtype:'float64',components:3,offset:0},{name:'serial',dtype:'uint64',components:1,offset:24}],row_bytes:40,logical_dtype:'uint32',identity_dtype:'uint32',logical_offset:32,identity_offset:36,leaf_limit:2,
    blocks:[{block_id:0,count:1,bounds,sha256:hash,byte_length:40}]}
  return {raw,index}
}
it('preserves exact scalar and source identity while projecting only display coordinates',async()=>{
  const {raw,index}=await sample();validateDetailIndex(index,index.source,index.generation)
  const data=await decodeDetailBlock(raw,index,index.blocks[0]!,[1000000,1000000,1000000],{mode:'scalar',field:'serial',component:0,min:(2n**63n).toString(),max:(2n**63n+2n).toString()},policy,new AbortController().signal)
  try{expect(Array.from(data.positions)).toEqual([.125,1.125,2.125]);expect(data.point(0)).toEqual({sourceIndex:'7',xyz:index.bounds.min,scalar:(2n**63n+1n).toString()})}finally{data.dispose();data.dispose()}
  expect(()=>data.point(0)).toThrow('cloud_point_unavailable')
})
it('uses explicit independent row widths and rejects old or undersized descriptors',async()=>{
  const {raw,index}=await sample()
  const old={...index} as Partial<DetailIndex>;delete old.logical_dtype
  expect(()=>validateDetailIndex(old,index.source,index.generation)).toThrow('cloud_preview_invalid')
  expect(()=>validateDetailIndex({...index,source_point_count:2**32+1},index.source,index.generation)).toThrow('cloud_preview_invalid')
  const expanded=new ArrayBuffer(44),view=new DataView(expanded)
  new Uint8Array(expanded).set(new Uint8Array(raw).slice(0,36))
  view.setBigUint64(36,2n**32n,true)
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',expanded)),b=>b.toString(16).padStart(2,'0')).join('')
  const wide:DetailIndex={...index,source_point_count:2**32+1,identity_dtype:'uint64',row_bytes:44,
    blocks:[{...index.blocks[0]!,byte_length:44,sha256:hash}]}
  validateDetailIndex(wide,wide.source,wide.generation)
  const data=await decodeDetailBlock(expanded,wide,wide.blocks[0]!,index.bounds.min,{mode:'solid'},policy,new AbortController().signal)
  try{expect(data.point(0).sourceIndex).toBe('4294967296')}finally{data.dispose()}
})
it('rejects checksum, source, layout, precision and cancelled reads without retained buffers',async()=>{
  const {raw,index}=await sample(),block=index.blocks[0]!
  expect(()=>validateDetailIndex(index,{...index.source,project_id:'other'},index.generation)).toThrow()
  expect(()=>validateDetailIndex({...index,row_bytes:47},index.source,index.generation)).toThrow()
  await expect(decodeDetailBlock(raw,index,{...block,sha256:'0'.repeat(64)},[0,0,0],{mode:'solid'},policy,new AbortController().signal)).rejects.toThrow('cloud_preview_checksum')
  const abort=new AbortController();abort.abort()
  await expect(decodeDetailBlock(raw,index,block,[0,0,0],{mode:'solid'},policy,abort.signal)).rejects.toThrow()
  await expect(decodeDetailBlock(raw,index,block,[-100000000,0,0],{mode:'solid'},policy,new AbortController().signal)).rejects.toThrow('cloud_position_precision')
  await expect(decodeDetailBlock(raw,index,block,[0,0,0],{mode:'solid'},{...policy,max_cpu_bytes:1},new AbortController().signal)).rejects.toThrow()
})
it('preserves wide generated vertex identity and rejects mismatched generated rows',async()=>{
  const {raw,index}=await sample(),wideRaw=new ArrayBuffer(48),view=new DataView(wideRaw)
  new Uint8Array(wideRaw).set(new Uint8Array(raw).slice(0,32))
  view.setBigUint64(32,2n**32n,true);view.setBigUint64(40,2n**32n,true)
  const digest=async()=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',wideRaw)),b=>b.toString(16).padStart(2,'0')).join('')
  const wide:DetailIndex={...index,vertex_kind:'generated',point_count:2**32+1,excluded_count:2**32,
    logical_dtype:'uint64',identity_dtype:'uint64',identity_offset:40,row_bytes:48,
    blocks:[{...index.blocks[0]!,byte_length:48,sha256:await digest()}]}
  validateDetailIndex(wide,wide.source,wide.generation)
  const data=await decodeDetailBlock(wideRaw,wide,wide.blocks[0]!,wide.bounds.min,{mode:'solid'},policy,new AbortController().signal)
  try{expect(data.point(0)).toMatchObject({sourceIndex:null,vertexIndex:'4294967296'})}finally{data.dispose()}
  view.setBigUint64(40,0n,true)
  await expect(decodeDetailBlock(wideRaw,wide,{...wide.blocks[0]!,sha256:await digest()},wide.bounds.min,{mode:'solid'},policy,new AbortController().signal)).rejects.toThrow('cloud_preview_invalid')
})
it('disposes late responses after view changes and unmount without installing old geometry',async()=>{
  const {index}=await sample();vi.useFakeTimers()
  let complete!:(value:any)=>void
  const data={dispose:vi.fn()},load=vi.fn((_block:DetailBlock,_signal:AbortSignal)=>new Promise<any>(resolve=>{complete=resolve})),target={clear:vi.fn(),add:vi.fn(),complete:vi.fn(),visible:()=>true},report=vi.fn()
  const controller=createDetailController(index,policy,()=>1,load,target,report)
  controller.enable(true);await vi.advanceTimersByTimeAsync(150)
  controller.changed();complete(data);await vi.advanceTimersByTimeAsync(0)
  expect(data.dispose).toHaveBeenCalledOnce();expect(target.add).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(150);controller.dispose();complete(data);await vi.advanceTimersByTimeAsync(0)
  expect(data.dispose).toHaveBeenCalledTimes(2);expect(target.complete).not.toHaveBeenCalled()
  expect(load.mock.calls[0]![1].aborted).toBe(true)
})
it('re-evaluates the shared point budget after comparison selection',async()=>{
  const {index}=await sample();vi.useFakeTimers();let base=10
  const target={clear:vi.fn(),add:vi.fn(),complete:vi.fn(),visible:()=>true},report=vi.fn(),load=vi.fn(async()=>({dispose:vi.fn()}) as any)
  const controller=createDetailController(index,policy,()=>base,load,target,report)
  controller.enable(true);await vi.advanceTimersByTimeAsync(150)
  expect(load).not.toHaveBeenCalled();expect(report).toHaveBeenLastCalledWith('limited',0)
  base=1;controller.changed();await vi.advanceTimersByTimeAsync(150)
  expect(load).toHaveBeenCalledOnce();expect(report).toHaveBeenLastCalledWith('ready',1)
  controller.dispose()
})
it('decodes saved centroid cells with current mapping and exact original member counts',async()=>{
  const {index}=await sample(),raw=new ArrayBuffer(64),view=new DataView(raw)
  index.bounds={min:[12,22,30],max:[12,22,30]}
  for(let c=0;c<3;c++)view.setFloat64(c*8,index.bounds.min[c]!,true)
  view.setBigInt64(24,1n,true);view.setBigInt64(32,-1n,true);view.setBigUint64(48,3n,true)
  const hash=()=>crypto.subtle.digest('SHA-256',raw).then(b=>Array.from(new Uint8Array(b),n=>n.toString(16).padStart(2,'0')).join(''))
  const saved:DetailIndex={...index,vertex_kind:'generated',fields:[index.fields[0]!],logical_offset:56,identity_offset:60,row_bytes:64,
    voxel:{keys_offset:24,members_offset:48,aggregation:{method_id:'resample-cloud',method_version:1,parameters:{settings:{kind:'voxel-centroid',frame_id:'original',length_unit:'m'}}},grid:{origin:[10,20,30],axes:[[0,2,0],[-2,0,0],[0,0,2]]}},
    blocks:[{...index.blocks[0]!,bounds:index.bounds,byte_length:64,sha256:await hash()}]}
  validateDetailIndex(saved,saved.source,saved.generation)
  const data=await decodeDetailBlock(raw,saved,saved.blocks[0]!,saved.bounds.min,{mode:'solid'},policy,new AbortController().signal)
  try{expect(data.point(0)).toMatchObject({sourceIndex:null,vertexIndex:'0',voxelKey:['1','-1','0'],memberCount:'3',voxelFrame:'original',voxelUnit:'m'});expect(data.point(0).voxelCorners![7]).toEqual([10,24,32])}finally{data.dispose()}
  view.setBigUint64(48,0n,true)
  await expect(decodeDetailBlock(raw,saved,{...saved.blocks[0]!,sha256:await hash()},saved.bounds.min,{mode:'solid'},policy,new AbortController().signal)).rejects.toThrow('cloud_preview_invalid')
})
it('refuses over-budget views before any fetch; commits only complete visible sets',async()=>{
  const {index}=await sample();vi.useFakeTimers()
  const data={dispose:vi.fn()},load=vi.fn(async()=>data as any),target={clear:vi.fn(),add:vi.fn(),complete:vi.fn(),visible:()=>true},report=vi.fn()
  const limited=createDetailController(index,{...policy,max_points:1},()=>1,load,target,report)
  limited.enable(true);await vi.advanceTimersByTimeAsync(150);expect(load).not.toHaveBeenCalled();expect(report).toHaveBeenLastCalledWith('limited',0);limited.dispose()
  const controller=createDetailController(index,policy,()=>1,load,target,report)
  controller.enable(true);await vi.advanceTimersByTimeAsync(150);expect(target.add).toHaveBeenCalledWith(data);expect(target.complete).toHaveBeenCalledOnce();expect(report).toHaveBeenLastCalledWith('ready',1);controller.dispose()
})

it('owns real Three geometry and releases decoded, CPU and GPU allocations once',async()=>{
  const {raw,index}=await sample(),scene=new Scene(),material=new PointsMaterial()
  const layer=createDetailLayer(scene,material,policy)
  layer.colors({min:1000000,max:1000005})
  const data=await decodeDetailBlock(raw,index,index.blocks[0]!,index.bounds.min,{mode:'solid'},policy,new AbortController().signal)
  layer.add(data);expect(layer.objects()).toHaveLength(1);expect(layer.objects()[0]!.visible).toBe(false)
  expect(Array.from(layer.objects()[0]!.geometry.getAttribute('color').array)).not.toEqual(Array.from(data.colors))
  layer.colors({min:1000000,max:1000005});layer.visible(true)
  expect(layer.point(layer.objects()[0],0)?.sourceIndex).toBe('7')
  expect(rendererUsage().gpuBytes).toBe(24)
  layer.clear();layer.clear();expect(scene.children).toHaveLength(0);material.dispose()
})

it.each(['checksum', 'missing', 'gpu-budget'])('releases a partially loaded view after %s failure, then allows explicit retry',async reason=>{
  const {raw,index}=await sample()
  const layerPolicy={...policy,max_gpu_bytes:reason==='gpu-budget'?24:policy.max_gpu_bytes}
  const material=new PointsMaterial(),scene=new Scene(),layer=createDetailLayer(scene,material,layerPolicy)
  const two={...index,blocks:[index.blocks[0]!,{...index.blocks[0]!,block_id:1}]}
  let failing=true,completed=false
  const report=vi.fn(),load=vi.fn(async(block:DetailBlock)=>{
    if(failing&&block.block_id===1&&reason==='missing')throw new Error('resource_not_found')
    return decodeDetailBlock(raw,index,failing&&block.block_id===1&&reason==='checksum'?{...block,sha256:'0'.repeat(64)}:block,
      index.bounds.min,{mode:'solid'},policy,new AbortController().signal)
  })
  const create=()=>createDetailController(two,policy,()=>1,load,{visible:()=>true,
    clear(){completed=false;layer.clear()},add:layer.add,
    complete(){completed=true;layer.visible(true)}},report)
  let controller=create()
  try{
    controller.enable(true)
    await vi.waitFor(()=>expect(report).toHaveBeenLastCalledWith('error',0,reason==='checksum'?'cloud_preview_checksum':reason==='missing'?'resource_not_found':'cloud_gpu_capacity'))
    expect(completed).toBe(false);expect(layer.objects()).toHaveLength(0);expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
    vi.useFakeTimers()
    const calls=load.mock.calls.length,reports=report.mock.calls.length
    for(let i=0;i<20;i++){controller.changed();controller.enable(i%2===0);await vi.advanceTimersByTimeAsync(200)}
    expect(load).toHaveBeenCalledTimes(calls);expect(report).toHaveBeenCalledTimes(reports)
    controller.dispose();vi.useRealTimers()
    failing=false;layerPolicy.max_gpu_bytes=policy.max_gpu_bytes;controller=create();controller.enable(true)
    await vi.waitFor(()=>expect(report).toHaveBeenLastCalledWith('ready',2))
    expect(completed).toBe(true);expect(layer.objects()).toHaveLength(2);expect(report).toHaveBeenLastCalledWith('ready',2)
  }finally{controller.dispose();material.dispose()}
})
