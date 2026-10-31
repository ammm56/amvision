import {expect,it,vi} from 'vitest'
import {Scene,PerspectiveCamera,Mesh,Vector3,type Object3D} from 'three'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
import type {TransformControls} from 'three/addons/controls/TransformControls.js'
const policy={max_points:1000,max_data_bytes:100000,max_cpu_bytes:10000000,max_gpu_bytes:10000000,max_canvas_pixels:1000000,max_position_error:.001}
const payload={observation_id:'obs',spatial:{frame_id:'fixture',length_unit:'mm'},bounds:{min:[1000000,0,0],max:[1000004,4,4]}}
const roi={roi_id:'r',frame_id:'fixture',length_unit:'mm',kind:'box',geometry:{center:[1000002,2,2],size:[2,2,2],rotation:[[1,0,0],[0,1,0],[0,0,1]]}}
it('writes physical ROI dimensions without cumulative scale and focuses only selected geometry',()=>{
  for(const kind of ['box','cylinder']){
    const scene=new Scene(),changed=vi.fn(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[1000000,0,0],policy,()=>{},()=>{},e=>{throw e})
    const value=kind==='box'?roi:{...roi,kind,geometry:{center:roi.geometry.center,axis:[0,0,1],radius:2,length:4}}
    try{
      overlay.update({payload,rois:[value],selectedId:'r',mode:'scale',changed})
      let control:TransformControls|undefined
      scene.traverse(o=>{if((o as Object3D&{controls?:TransformControls}).controls)control=(o as Object3D&{controls:TransformControls}).controls})
      const c=control!;expect(c.space).toBe('local')
      c.object!.scale.set(2,3,2);c.dispatchEvent({type:'objectChange'})
      expect(changed.mock.lastCall![0].geometry).toMatchObject(kind==='box'?{size:[4,6,4]}:{radius:4,length:12})
      c.object!.scale.set(3,4,3);c.dispatchEvent({type:'objectChange'})
      expect(changed.mock.lastCall![0].geometry).toMatchObject(kind==='box'?{size:[6,8,6]}:{radius:6,length:16})
      c.object!.scale.set(-1,1,1);c.dispatchEvent({type:'objectChange'});expect(changed).toHaveBeenCalledTimes(2)
      expect(overlay.focus('roi')!.center.distanceTo(new Vector3(2,2,2))).toBeLessThan(1e-12);expect(overlay.focus('measurement')).toBeNull()
    }finally{overlay.dispose()}
    expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
  }
})
it('uses physical local coordinates and releases geometry/control budgets on replacement and close',()=>{
  const scene=new Scene(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[1000000,0,0],policy,()=>{},()=>{},error=>{throw error})
  try{
    overlay.update({payload,rois:[roi],selectedId:'r',changed:()=>{}})
    const meshes:Mesh[]=[];scene.traverse(o=>{if(o instanceof Mesh)meshes.push(o)})
    const cube=meshes.find(m=>m.geometry.type==='BoxGeometry')!;expect(cube.getWorldPosition(new Vector3()).toArray()).toEqual([2,2,2]);expect(rendererUsage().gpuBytes).toBeGreaterThan(0)
    overlay.update({payload,rois:[]});expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
    overlay.update({payload,rois:[roi]});expect(rendererUsage().gpuBytes).toBeGreaterThan(0)
  } finally {overlay.dispose()}
  expect(scene.children).toHaveLength(0);expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
})
it('rejects cross-frame overlays and budget failures without leaving partial buffers',()=>{
  for(const max_gpu_bytes of [1,policy.max_gpu_bytes]){
    const scene=new Scene(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[0,0,0],{...policy,max_gpu_bytes},()=>{},()=>{},error=>{throw error})
    expect(()=>overlay.update({payload,rois:[{...roi,frame_id:max_gpu_bytes===1?'fixture':'wrong'}]})).toThrow()
    expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0});overlay.dispose()
  }
})
it('keeps section finite geometry fixed while the bounded slab has explicit clip planes',()=>{
  const scene=new Scene(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[1000000,0,0],policy,()=>{},()=>{},error=>{throw error})
  overlay.update({payload,rois:[roi,{...roi,roi_id:'slice',kind:'section-band',geometry:{origin:[1000002,2,2],normal:[0,0,1],thickness:1,bounds_roi_id:'r'}}]})
  const clipped:Mesh[]=[];scene.traverse(o=>{if(o instanceof Mesh&&!Array.isArray(o.material)&&o.material.clippingPlanes?.length)clipped.push(o)})
  expect(clipped).toHaveLength(1);expect(clipped[0]!.getWorldPosition(new Vector3()).toArray()).toEqual([2,2,2]);overlay.dispose();expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
})

it('refreshes dependent section bounds after drag and does not allocate after unmount',async()=>{
  const scene=new Scene(),failed=vi.fn()
  const overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[1000000,0,0],policy,()=>{},()=>{},failed)
  const section={...roi,roi_id:'slice',kind:'section-band',geometry:{origin:[1000002,2,2],normal:[0,0,1],thickness:1,bounds_roi_id:'r'}}
  let current=structuredClone(roi)
  const draw=()=>overlay.update({payload,rois:[current,section],selectedId:'r',changed:()=>{}})
  const control=()=>{
    let result:{dragging:boolean}|undefined
    scene.traverse(o=>{const c=(o as Object3D&{controls?:{dragging:boolean}}).controls;if(c)result=c})
    return result!
  }
  const clippedCenter=()=>{
    let result:number[]|undefined
    scene.traverse(o=>{if(o instanceof Mesh&&!Array.isArray(o.material)&&o.material.clippingPlanes?.length)result=o.getWorldPosition(new Vector3()).toArray()})
    return result
  }
  try{
    draw();const first=control();first.dragging=true
    current.geometry.center=[1000007,2,2];draw()
    expect(clippedCenter()).toEqual([2,2,2])
    first.dragging=false;await Promise.resolve()
    expect(clippedCenter()).toEqual([7,2,2])
    const second=control();second.dragging=true;second.dragging=false;overlay.dispose();await Promise.resolve()
    expect(scene.children).toHaveLength(0);expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0});expect(failed).not.toHaveBeenCalled()
  }finally{overlay.dispose()}
})

it('toggles all shared leaf instances without rebuilding geometry or reallocating buffers',()=>{
  const scene=new Scene(),changed=vi.fn(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[1000000,0,0],policy,()=>{},()=>{},e=>{throw e})
  const section={...roi,roi_id:'slice',kind:'section-band',geometry:{origin:[1000002,2,2],normal:[0,0,1],thickness:1,bounds_roi_id:'r'}}
  try{
    overlay.update({payload,rois:[roi,section],selectedId:'r',changed})
    const root=scene.children[0],before=rendererUsage(),objects: Object3D[]=[]
    scene.traverse(o=>objects.push(o))
    for(let i=0;i<20;i++){
      overlay.visibility(new Set(['r']));expect(overlay.focus('roi')).toBeNull()
      for(const object of objects.filter(o=>o.userData.roiId==='r'))expect(object.visible).toBe(false)
      overlay.visibility(new Set());expect(overlay.focus('roi')).not.toBeNull()
    }
    const after:Object3D[]=[];scene.traverse(o=>after.push(o))
    expect(after).toEqual(objects);expect(scene.children[0]).toBe(root)
    expect(rendererUsage()).toEqual(before);expect(changed).not.toHaveBeenCalled()
  }finally{overlay.dispose()}
  expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
})

it('focuses the visible clipped slab, not the enclosing finite box or an empty anchor',()=>{
  const scene=new Scene(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[1000000,0,0],policy,()=>{},()=>{},e=>{throw e})
  const section={...roi,roi_id:'slice',kind:'section-band',geometry:{origin:[1000002,2,2.75],normal:[0,0,1],thickness:.5,bounds_roi_id:'r'}}
  try{
    overlay.update({payload,rois:[roi,section],selectedId:'slice',changed:()=>{}})
    expect(overlay.focus('roi')!.center.toArray()).toEqual([2,2,2.75])
    overlay.visibility(new Set(['r']));expect(overlay.focus('roi')).toBeNull()
    overlay.visibility(new Set());expect(overlay.focus('roi')!.center.toArray()).toEqual([2,2,2.75])
  }finally{overlay.dispose()}
  expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
})

it('cancels only the active gesture and ignores old controls after scope replacement and disposal',async()=>{
  const scene=new Scene(),changed=vi.fn(),failed=vi.fn(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[1000000,0,0],policy,()=>{},()=>{},failed)
  const findControl=()=>{let result:TransformControls|undefined;scene.traverse(o=>{const c=(o as Object3D&{controls?:TransformControls}).controls;if(c)result=c});return result!}
  const start={...roi,geometry:{...roi.geometry,center:[1000003,2,2]}}
  const draw=(value= start,scope='one')=>overlay.update({payload,rois:[value],selectedId:'r',roiScope:scope,changed})
  try{
    draw();const c=findControl(),root=scene.children[0]
    c.dragging=true;c.dispatchEvent({type:'mouseDown',mode:'translate'})
    c.object!.position.x=8;c.dispatchEvent({type:'objectChange'})
    draw(changed.mock.lastCall![0]);expect(changed.mock.lastCall![0].geometry.center[0]).toBe(1000008)
    overlay.visibility(new Set(['r']));expect(changed.mock.lastCall![0]).toEqual(start)
    expect(c.dragging).toBe(false);expect(c.object).toBeUndefined();expect(overlay.focus('roi')).toBeNull()
    overlay.update({payload,rois:[start],selectedId:'r',roiScope:'one',changed,hiddenRoiIds:new Set(['r'])})
    expect(scene.children[0]).toBe(root)
    overlay.visibility(new Set());expect(findControl()).toBe(c)
    c.dragging=true;c.dispatchEvent({type:'mouseDown',mode:'translate'});draw(start,'two')
    const calls=changed.mock.calls.length;c.dispatchEvent({type:'objectChange'});c.dragging=false;await Promise.resolve()
    expect(changed).toHaveBeenCalledTimes(calls)
    const latest=findControl();overlay.dispose();latest.dispatchEvent({type:'objectChange'});await Promise.resolve()
    expect(changed).toHaveBeenCalledTimes(calls);expect(failed).not.toHaveBeenCalled()
  }finally{overlay.dispose()}
  expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
})
