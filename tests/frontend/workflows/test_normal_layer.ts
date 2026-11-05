import {expect,it} from 'vitest'
import {Scene,LineSegments} from 'three'
import {createNormalLayer} from '@/workflows/workflow-editor/point-cloud/normal-layer'
import {rendererUsage,type CloudDisplayData} from '@/workflows/workflow-editor/point-cloud/preview-data'
const policy={max_points:100,max_data_bytes:100000,max_cpu_bytes:100000,max_gpu_bytes:100000,max_canvas_pixels:10000,max_position_error:.001}
const data:CloudDisplayData={positions:new Float32Array([0,0,0,1,0,0,2,0,0]),colors:new Float32Array(9),count:3,origin:[0,0,0],dispose(){},point(i){return {sourceIndex:String(i),xyz:[i,0,0],scalar:null,normal:{vector:i===2?[0,0,0]:[0,0,1],valid:i!==2,oriented:i===0,reason:i===2?4:0}}}}
it('draws signed arrows, unsigned axes and no invalid placeholder; releases replacements',()=>{
  const scene=new Scene(),before=rendererUsage(),layer=createNormalLayer(scene,data,policy,()=>{})
  try{
    layer.update({length:2,stride:1});expect(scene.children).toHaveLength(1)
    const p=(scene.children[0] as LineSegments).geometry.getAttribute('position')
    expect(p.count).toBe(8);expect(Array.from(p.array).slice(0,6)).toEqual([0,0,0,0,0,2])
    expect(Array.from(p.array).slice(-6)).toEqual([1,0,-1,1,0,1])
    layer.update({length:1,stride:2});expect((scene.children[0] as LineSegments).geometry.getAttribute('position').count).toBe(6)
    layer.update(null);expect(scene.children).toHaveLength(0);expect(rendererUsage()).toEqual(before)
  }finally{layer.dispose()}
  layer.update({length:1,stride:1});expect(scene.children).toHaveLength(0)
})
it('rejects bad settings and budget/precision failures without leaking buffers',()=>{
  const scene=new Scene(),before=rendererUsage(),layer=createNormalLayer(scene,data,{...policy,max_gpu_bytes:1},()=>{})
  expect(()=>layer.update({length:1,stride:0})).toThrow('invalid')
  expect(()=>layer.update({length:1,stride:1})).toThrow('capacity');expect(rendererUsage()).toEqual(before);layer.dispose()
  const precision=createNormalLayer(scene,data,policy,()=>{})
  expect(()=>precision.update({length:1e40,stride:1})).toThrow('precision');expect(rendererUsage()).toEqual(before);expect(scene.children).toHaveLength(0);precision.dispose()
})
