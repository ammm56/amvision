import {afterEach, expect, it} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {Mesh, PerspectiveCamera, Scene, Vector3} from 'three'
import RoiEditor from '../../../custom_nodes/metrology3d_nodes/frontend/RoiEditor.vue'
import {roiIssues} from '../../../custom_nodes/metrology3d_nodes/frontend/form'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
import {roiDependencyClosure} from '@/workflows/workflow-editor/point-cloud/roi-graph'

const identity={frame_id:'fixture',length_unit:'mm',format_id:'amvision.roi3d.v1'}
const box=(id:string,x:number)=>({...identity,roi_id:id,kind:'box',geometry:{center:[x,0,0],size:[2,2,2],rotation:[[1,0,0],[0,1,0],[0,0,1]]}})
const union=(id:string,...members:string[])=>({...identity,roi_id:id,kind:'union',geometry:{roi_ids:members}})
const source=()=>({kind:'parameters',roi:union('all','left','right'),bounds:[box('left',0),box('right',6)]})
const policy={max_points:1000,max_data_bytes:100000,max_cpu_bytes:10000000,max_gpu_bytes:10000000,max_canvas_pixels:1000000,max_position_error:.001}
const payload={observation_id:'obs',spatial:{frame_id:'fixture',length_unit:'mm'},bounds:{min:[-1,-1,-1],max:[7,1,1]}}
afterEach(()=>{document.body.innerHTML=''})
const button=(text:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!
async function change(element:HTMLInputElement|HTMLSelectElement,value:string,event='change'){
  element.value=value;element.dispatchEvent(new Event(event,{bubbles:true}));await flushPromises()
}

it('edits union members atomically, blocks empty sets and preserves cancellation',async()=>{
  const w=mount(RoiEditor,{props:{modelValue:source()},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  await w.get('button').trigger('click');await flushPromises()
  const checkboxes=[...document.querySelectorAll<HTMLInputElement>('.roi-members input')]
  expect(checkboxes.map(c=>c.value)).toEqual(['left','right'])
  checkboxes.forEach(c=>c.click());await flushPromises()
  expect(button('Apply').disabled).toBe(true)
  checkboxes[1]!.click();await flushPromises();button('Cancel').click();await flushPromises()
  expect(w.emitted('update:modelValue')).toBeUndefined()
  await w.get('button').trigger('click');await flushPromises()
  document.querySelector<HTMLInputElement>('.roi-members input[value="left"]')!.click();await flushPromises()
  button('Apply').click();await flushPromises()
  expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual({...source(),roi:union('all','right')})
  w.unmount();expect(document.querySelector('[role=dialog]')).toBeNull()
})

it('renames member references together and prevents deleting a referenced member',async()=>{
  const w=mount(RoiEditor,{props:{modelValue:source()},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  await w.get('button').trigger('click');await flushPromises()
  const selection=[...document.querySelectorAll('select')].find(s=>s.textContent?.includes('Target ROI'))!
  await change(selection,'0')
  expect(document.querySelector<HTMLButtonElement>('button[title="Referenced by: all"]')!.disabled).toBe(true)
  await change(document.querySelector<HTMLInputElement>('input[aria-label="ROI ID"]')!,'renamed','input')
  button('Apply').click();await flushPromises()
  const expected=source();expected.roi.geometry.roi_ids=['renamed','right'];expected.bounds[0]!.roi_id='renamed'
  expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual(expected)
  w.unmount()
})

it('rejects missing, duplicate, mixed-cycle and cross-space members, including unused dependencies',()=>{
  const slice={...identity,roi_id:'slice',kind:'section-band',geometry:{origin:[0,0,0],normal:[0,0,1],thickness:1,bounds_roi_id:'all'}}
  for(const rois of [[union('all')],[union('all','x')],[union('all','x','x'),box('x',0)],[union('all','slice'),slice],[box('x',0),union('all','slice'),slice],[union('all','x'),{...box('x',0),frame_id:'other'}]])expect(roiIssues(rois).length).toBeGreaterThan(0)
  expect(roiIssues([union('all','x'),box('x',0)])).toEqual([])
})

it('does not display an unchecked member unless that member is explicitly being edited',()=>{
  const rois=[union('all','left'),box('left',0),box('right',6)]
  expect(roiDependencyClosure(rois,['all']).map(r=>r.roi_id)).toEqual(['all','left'])
  expect(roiDependencyClosure(rois,['all','right']).map(r=>r.roi_id)).toEqual(['all','left','right'])
})

it('renders disjoint actual members once, clips unions with sections and releases every buffer',()=>{
  const scene=new Scene(), overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[0,0,0],policy,()=>{},()=>{},error=>{throw error})
  const meshes=()=>{const result:Mesh[]=[];scene.traverse(o=>{if(o instanceof Mesh&&o.geometry.type==='BoxGeometry')result.push(o)});return result}
  const rois=[union('all','shared','left'),union('shared','left','right'),box('left',0),box('right',6)]
  try{
    overlay.update({payload,rois})
    expect(meshes().map(m=>m.getWorldPosition(new Vector3()).x).sort()).toEqual([0,6])
    const slice={...identity,roi_id:'slice',kind:'section-band',geometry:{origin:[0,0,0],normal:[0,0,1],thickness:1,bounds_roi_id:'all'}}
    overlay.update({payload,rois:[...rois,slice]})
    expect(meshes()).toHaveLength(2)
    for(const mesh of meshes())expect(!Array.isArray(mesh.material)&&mesh.material.clippingPlanes?.length).toBe(2)
    overlay.update({payload,rois:[]});expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
  }finally{overlay.dispose()}
  expect(scene.children).toHaveLength(0)
})

it('cleans up partial displays on graph and CPU budget errors',()=>{
  for(const limit of [1,policy.max_cpu_bytes]){
    const scene=new Scene(), overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[0,0,0],{...policy,max_cpu_bytes:limit},()=>{},()=>{},error=>{throw error})
    try{
      const rois=limit===1?[union('all','x'),box('x',0)]:[union('all','other'),union('other','all')]
      expect(()=>overlay.update({payload,rois})).toThrow()
      expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
    }finally{overlay.dispose()}
  }
})
