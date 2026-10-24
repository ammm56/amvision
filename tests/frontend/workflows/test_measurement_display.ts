import {expect,it} from 'vitest'
import {Scene,PerspectiveCamera,LineSegments} from 'three'
import {measurementItems} from '@/workflows/workflow-editor/point-cloud/measurement-display'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
import {planeColorData,fillPlaneColors,planeColorSummary} from '@/workflows/workflow-editor/point-cloud/plane-colors'
const policy={max_points:100,max_data_bytes:10000,max_cpu_bytes:100000,max_gpu_bytes:100000,max_canvas_pixels:10000,max_position_error:.001}
function payload(valid=true){return {observation_id:'obs',spatial:{frame_id:'fixture',length_unit:'mm'},bounds:{min:[0,0,0],max:[1,1,5]},measurements:{format_id:'amvision.measurement-evidence3d.v2',observation_id:'obs',frame_id:'fixture',length_unit:'mm',items:[{kind:'height-query',method:{method_id:'height-query'},item_id:'height',valid,value:valid?5:null,reason:valid?null:'outside_support',geometry:valid?{kind:'directional-distance',endpoints:[[0,0,0],[0,0,5]]}:null,support:[{role:'reference',coverage:{triangle:[[0,0,0],[1,0,0],[0,1,0]]}},{role:'target',coverage:{triangle:[[0,0,5],[1,0,5],[0,1,5]]}}],quality:{usable:valid,metrics:{observation_id:'obs',items:[]}}}]}}}
it('rejects cross-observation evidence and stale valid values in invalid results',()=>{
  expect(measurementItems(payload())[0]!.value).toBe(5)
  const wrong=payload();wrong.measurements.observation_id='old';expect(()=>measurementItems(wrong)).toThrow()
  const failed=payload(false);failed.measurements.items[0]!.value=5;expect(()=>measurementItems(failed)).toThrow()
  const previous=payload();previous.measurements.format_id='amvision.measurement-evidence3d.v1';expect(()=>measurementItems(previous)).toThrow()
})
it('draws actual endpoints, clears invalid measurements and releases bounded overlay buffers',()=>{
  const scene=new Scene(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[0,0,0],policy,()=>{},()=>{},e=>{throw e})
  try{
    overlay.update({payload:payload(),selectedMeasurement:'height'})
    const lines:LineSegments[]=[];scene.traverse(o=>{if(o instanceof LineSegments)lines.push(o)})
    expect(lines).toHaveLength(3)
    expect(Array.from(lines[0]!.geometry.getAttribute('position').array)).toEqual([0,0,0,0,0,5])
    overlay.update({payload:payload(false)})
    const remaining:LineSegments[]=[];scene.traverse(o=>{if(o instanceof LineSegments)remaining.push(o)})
    expect(remaining).toHaveLength(0);expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
  }finally{overlay.dispose()}
})
it('validates support samples against the exact preview and preserves the original colors',()=>{
  const value={display_point_count:3,data:{checksum:'same'},geometry:{planes:[{feature_id:'p',samples:{data_sha256:'same',classes:[0,1,2],residuals:[null,-.2,.1]}}]}}
  const samples=planeColorData(value,'p')!,original=new Float32Array(9).fill(.3),target=new Float32Array(9)
  expect(planeColorSummary(samples)).toEqual({support:1,rejected:1,unrelated:1,extent:.2})
  expect(planeColorSummary({classes:[0],residuals:[null]})?.extent).toBeNull()
  fillPlaneColors(target,original,samples,'support');expect(target[0]).toBeCloseTo(.48);expect(target[4]).toBeCloseTo(.68);expect(target[6]).toBeCloseTo(.88)
  fillPlaneColors(target,original,samples,'residual');expect(Array.from(target.slice(3,6))).toEqual([0,0,1]);expect(target[7]).toBeCloseTo(.5)
  fillPlaneColors(target,original,null,'original');expect(target).toEqual(original)
  value.data.checksum='other';expect(()=>planeColorData(value,'p')).toThrow()
})
