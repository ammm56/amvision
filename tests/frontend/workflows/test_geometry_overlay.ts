import {expect,it,vi} from 'vitest'
import {Scene,PerspectiveCamera,Mesh,Vector3,type Object3D} from 'three'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
const policy={max_points:1000,max_data_bytes:100000,max_cpu_bytes:10000000,max_gpu_bytes:10000000,max_canvas_pixels:1000000,max_position_error:.001}
const payload={observation_id:'obs',spatial:{frame_id:'fixture',length_unit:'mm'},bounds:{min:[1000000,0,0],max:[1000004,4,4]}}
const roi={roi_id:'r',frame_id:'fixture',length_unit:'mm',kind:'box',geometry:{center:[1000002,2,2],size:[2,2,2],rotation:[[1,0,0],[0,1,0],[0,0,1]]}}
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
