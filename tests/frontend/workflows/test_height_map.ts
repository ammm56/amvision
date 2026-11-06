import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import HeightMapSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/HeightMapSettingsEditor.vue'
import {newHeightMap,heightMapIssues} from '../../../custom_nodes/metrology3d_nodes/frontend/height-map-form'
import {put,type Form} from '../../../custom_nodes/metrology3d_nodes/frontend/form'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'
import {decodeHeightMap} from '@/workflows/workflow-editor/point-cloud/height-map-display'
import HeightMapPanel from '@/workflows/workflow-editor/point-cloud/HeightMapPanel.vue'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
import {readCloudCapabilities} from '@/workflows/workflow-editor/services/measurement-resource.service'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({default:{template:'<div />'}}))
vi.mock('@/workflows/workflow-editor/services/measurement-resource.service',()=>({readCloudCapabilities:vi.fn()}))
const policy={max_points:100,max_data_bytes:8192,max_cpu_bytes:65536,max_gpu_bytes:65536,max_canvas_pixels:65536,max_position_error:.0001}
const valid=():Form=>({frame:{kind:'current-frame',frame_id:'fixture'},length_unit:'mm',grid:{kind:'orthographic-height',origin:[0,0,0],column_direction:[1,0,0],row_direction:[0,1,0],height_direction:[0,0,1],column_step:1,row_step:2},width:3,height:2,aggregation:'mean'})
const button=(text:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!
const plugins=()=>[createI18n({legacy:false,locale:'en-US'})]
beforeEach(async()=>{
  vi.stubGlobal('ResizeObserver',class{observe(){} disconnect(){}})
  const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');vi.stubGlobal('crypto',webcrypto)
  vi.mocked(readCloudCapabilities).mockResolvedValue({renderer:policy} as Awaited<ReturnType<typeof readCloudCapabilities>>)
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({createImageData:(w:number,h:number)=>({data:new Uint8ClampedArray(w*h*4)}),putImageData:vi.fn(),strokeRect:vi.fn()} as unknown as CanvasRenderingContext2D)
})
afterEach(()=>{expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0});vi.restoreAllMocks();vi.unstubAllGlobals();document.body.innerHTML=''})
async function payload(dtype='float32'){
  const b=dtype==='float32'?4:8,raw=new Uint8Array(6*(b*3+8)),view=new DataView(raw.buffer)
  for(let field=0;field<3;field++)for(let i=0;i<6;i++){const v=i===0?0:i===1?3:NaN;if(b===4)view.setFloat32((field*6+i)*b,v,true);else view.setFloat64((field*6+i)*b,v,true)}
  view.setBigUint64(18*b,1n,true);view.setBigUint64(18*b+8,2n,true)
  const data={encoding:'base64',content_length:raw.length,content:btoa(String.fromCharCode(...raw)),checksum_algorithm:'sha256',checksum:[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(b=>b.toString(16).padStart(2,'0')).join('')}
  return {cloud_id:'cloud',observation_id:'observation',spatial:{frame_id:'fixture',length_unit:'mm'},vertex_kind:'source',point_count:3,height_map:{format_id:'amvision.height-map-preview.v1',state:'ready',cloud_id:'cloud',observation_id:'observation',evidence:{format_id:'amvision.height-map.v1',parameters:valid(),pose:null,input_count:3,vertex_kind:'source',dtype,outside_count:0,occupied_count:2,max_rounding_error:0},data}}
}
it('requires explicit physical parameters and an exclusive coordinate source',()=>{
  expect(trustedParameterEditor('custom.metrology3d.cloud-to-height-map','settings')).toBe(HeightMapSettingsEditor)
  expect(heightMapIssues(newHeightMap()).length).toBeGreaterThan(0)
  expect(heightMapIssues(valid())).toEqual([])
  for(const method of ['minimum','maximum','mean','median'])expect(heightMapIssues({...valid(),aggregation:method})).toEqual([])
  for(const [path,value] of [['width',0],['height',1.5],['grid.origin',[NaN,0,0]],['grid.column_step',0],['grid.row_direction',[1,0,0]],['grid.height_direction',[0,0,-1]],['frame.pose_id','old']])expect(heightMapIssues(put(valid(),path as string,value)).length).toBeGreaterThan(0)
})
it('applies only valid parameters, removes conflicting frame keys and drops stale drafts',async()=>{
  const w=mount(HeightMapSettingsEditor,{props:{modelValue:valid(),nodeType:'custom.metrology3d.cloud-to-height-map'},attachTo:document.body,global:{plugins:plugins()}})
  try{
    await w.get('button').trigger('click');await flushPromises();button('Apply').click();await flushPromises();expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual(valid())
    await w.get('button').trigger('click');await flushPromises();const source=document.querySelector<HTMLSelectElement>('[aria-label="Coordinate source"]')!;source.value='pose-frame';source.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises();expect(button('Apply').disabled).toBe(true)
    source.value='current-frame';source.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises();expect(button('Apply').disabled).toBe(true)
    button('Cancel').click();await flushPromises();expect(w.emitted('update:modelValue')).toHaveLength(1)
    await w.get('button').trigger('click');await flushPromises();await w.setProps({inputSources:{cloud:[]}});expect(document.querySelector('[role=dialog]')).toBeNull()
    await w.get('button').trigger('click');await flushPromises();await w.setProps({disabled:true});expect(document.querySelector('[role=dialog]')).toBeNull()
  }finally{w.unmount()}
})
it.each(['float32','float64'])('decodes %s without turning empty cells into zero; projects exact cell corners',async dtype=>{
  const decoded=await decodeHeightMap(await payload(dtype),policy,new AbortController().signal)
  try{expect(decoded.cell(0,0)).toMatchObject({count:1,height:0,min:0,max:0});expect(decoded.cell(0,2)).toMatchObject({count:0,height:null,corners:null});expect(decoded.cell(0,1).corners![0]).toEqual([.5,-1,3]);expect(decoded.cell(0,1).corners![7]).toEqual([1.5,1,3])}finally{decoded.dispose()}
  expect(()=>decoded.cell(0,0)).toThrow()
})
it.each(['identity','checksum','grid','counts','capacity','pose'])('rejects malformed %s and releases every reservation',async failure=>{
  const body=await payload();let limits=policy
  if(failure==='identity')body.height_map.cloud_id='other'
  if(failure==='checksum')body.height_map.data.checksum='0'.repeat(64)
  if(failure==='grid')body.height_map.evidence.parameters.width=1.5
  if(failure==='counts')body.height_map.evidence.input_count=4
  if(failure==='capacity')limits={...policy,max_cpu_bytes:1}
  if(failure==='pose')body.height_map.evidence.parameters.frame={kind:'pose-frame',pose_id:'missing',target_frame_id:'fixture'}
  await expect(decodeHeightMap(body,limits,new AbortController().signal)).rejects.toThrow()
})
it('uses inverse historical pose for display only and rejects affine distortion',async()=>{
  const body=await payload(),e=body.height_map.evidence as Record<string,unknown>
  e.parameters={...valid(),frame:{kind:'pose-frame',pose_id:'pose',target_frame_id:'datum'}}
  const pose={state:'found',pose_id:'pose',source_frame_id:'fixture',target_frame_id:'datum',length_unit:'mm',transform:{matrix:[[0,-1,0,10],[1,0,0,20],[0,0,1,30],[0,0,0,1]]}}
  e.pose=pose
  const decoded=await decodeHeightMap(body,policy,new AbortController().signal)
  try{expect(decoded.cell(0,0).corners![0]).toEqual([-21,10.5,-30])}finally{decoded.dispose()}
  pose.transform.matrix=[[2,0,0,0],[0,.5,0,0],[0,0,1,0],[0,0,0,1]]
  await expect(decodeHeightMap(body,policy,new AbortController().signal)).rejects.toThrow()
})
it('selects empty cells without invented values and clears selection on unmount',async()=>{
  const body=await payload(),w=mount(HeightMapPanel,{props:{payload:body,projectId:'p'},global:{plugins:plugins()}})
  try{await vi.waitFor(()=>expect(w.findAll('input')).toHaveLength(2));const inputs=w.findAll('input');await inputs[0]!.setValue(0);await inputs[1]!.setValue(0);expect(w.text()).toContain('Contributors1');expect(w.emitted('select')!.at(-1)![0]).toMatchObject({payload:body,corners:expect.any(Array)});await inputs[1]!.setValue(2);expect(w.text()).toContain('No data');expect(w.emitted('select')!.at(-1)![0]).toEqual({payload:body,corners:null})}finally{w.unmount();await flushPromises()}
})
it('ignores late capabilities after payload replacement and unmount',async()=>{
  let finish!:(v:Awaited<ReturnType<typeof readCloudCapabilities>>)=>void
  vi.mocked(readCloudCapabilities).mockImplementationOnce(()=>new Promise(r=>{finish=r}))
  const old=await payload(),next=await payload();next.cloud_id='new';next.height_map.cloud_id='new'
  const w=mount(HeightMapPanel,{props:{payload:old,projectId:'p'},global:{plugins:plugins()}})
  await w.setProps({payload:next});await flushPromises();expect(rendererUsage().cpuBytes).toBeGreaterThan(0)
  w.unmount();finish({renderer:policy} as Awaited<ReturnType<typeof readCloudCapabilities>>);await flushPromises();expect(rendererUsage().cpuBytes).toBe(0)
  expect((w.emitted('select')??[]).every(e=>(e[0] as {payload:unknown}).payload!==old)).toBe(true)
})
