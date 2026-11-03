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

async function sample(){
  const raw=new ArrayBuffer(48),view=new DataView(raw)
  for(let c=0;c<3;c++)view.setFloat64(c*8,1000000+c+.125,true)
  view.setBigUint64(24,2n**63n+1n,true);view.setBigUint64(32,0n,true);view.setBigUint64(40,7n,true)
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),b=>b.toString(16).padStart(2,'0')).join('')
  const bounds={min:[1000000.125,1000001.125,1000002.125],max:[1000000.125,1000001.125,1000002.125]}
  const index:DetailIndex={format_id:'amvision.point-cloud-detail.v1',source:{project_id:'p',resource_id:'r',version:1,kind:'point-cloud',sha256:'a'.repeat(64)},generation:'b'.repeat(32),vertex_kind:'source',point_count:1,source_point_count:8,valid_count:1,excluded_count:0,bounds,
    fields:[{name:'positions',dtype:'float64',components:3,offset:0},{name:'serial',dtype:'uint64',components:1,offset:24}],row_bytes:48,logical_offset:32,identity_offset:40,leaf_limit:2,
    blocks:[{block_id:0,count:1,bounds,sha256:hash,byte_length:48}]}
  return {raw,index}
}
it('preserves exact scalar and source identity while projecting only display coordinates',async()=>{
  const {raw,index}=await sample();validateDetailIndex(index,index.source,index.generation)
  const data=await decodeDetailBlock(raw,index,index.blocks[0]!,[1000000,1000000,1000000],{mode:'scalar',field:'serial',component:0,min:(2n**63n).toString(),max:(2n**63n+2n).toString()},policy,new AbortController().signal)
  try{expect(Array.from(data.positions)).toEqual([.125,1.125,2.125]);expect(data.point(0)).toEqual({sourceIndex:'7',xyz:index.bounds.min,scalar:(2n**63n+1n).toString()})}finally{data.dispose();data.dispose()}
  expect(()=>data.point(0)).toThrow('cloud_point_unavailable')
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
it('disposes late responses after view changes and unmount without installing old geometry',async()=>{
  const {index}=await sample();vi.useFakeTimers()
  let complete!:(value:any)=>void
  const data={dispose:vi.fn()},load=vi.fn((_block:DetailBlock,_signal:AbortSignal)=>new Promise<any>(resolve=>{complete=resolve})),target={clear:vi.fn(),add:vi.fn(),complete:vi.fn(),visible:()=>true},report=vi.fn()
  const controller=createDetailController(index,policy,1,load,target,report)
  controller.enable(true);await vi.advanceTimersByTimeAsync(150)
  controller.changed();complete(data);await vi.advanceTimersByTimeAsync(0)
  expect(data.dispose).toHaveBeenCalledOnce();expect(target.add).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(150);controller.dispose();complete(data);await vi.advanceTimersByTimeAsync(0)
  expect(data.dispose).toHaveBeenCalledTimes(2);expect(target.complete).not.toHaveBeenCalled()
  expect(load.mock.calls[0]![1].aborted).toBe(true)
})
it('refuses over-budget views before any fetch; commits only complete visible sets',async()=>{
  const {index}=await sample();vi.useFakeTimers()
  const data={dispose:vi.fn()},load=vi.fn(async()=>data as any),target={clear:vi.fn(),add:vi.fn(),complete:vi.fn(),visible:()=>true},report=vi.fn()
  const limited=createDetailController(index,{...policy,max_points:1},1,load,target,report)
  limited.enable(true);await vi.advanceTimersByTimeAsync(150);expect(load).not.toHaveBeenCalled();expect(report).toHaveBeenLastCalledWith('limited',0);limited.dispose()
  const controller=createDetailController(index,policy,1,load,target,report)
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
