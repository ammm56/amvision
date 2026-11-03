import {expect,it} from 'vitest'
import {Scene,PerspectiveCamera} from 'three'
import {curveItems,curveStrokes} from '@/workflows/workflow-editor/point-cloud/boundary-display'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
const policy={max_points:100,max_data_bytes:10000,max_cpu_bytes:100000,max_gpu_bytes:100000,max_canvas_pixels:100000,max_position_error:.001}
function payload(){
  const segments=[{segment_id:'left',start:0,count:2,closed:false,role:'open',orientation:'open'},{segment_id:'right',start:2,count:2,closed:false,role:'open',orientation:'open'}]
  return {observation_id:'obs',spatial:{frame_id:'fixture',length_unit:'mm'},bounds:{min:[0,0,0],max:[11,1,1]},geometry:{format_id:'amvision.geometry-preview.v1',observation_id:'obs',frame_id:'fixture',length_unit:'mm',planes:[],rois:[],frame:null,curves:[{kind:'line',feature_id:'edge',valid:true,reason:null,vertex_kind:'generated',points:[[0,0,0],[1,0,0],[10,0,0],[11,0,0]],support_point_count:4,topology:{point_count:4,segments},geometry:{origin:[0,0,0],direction:[1,0,0]},method:{method_id:'fit-line',method_version:1,evaluation:{frame_id:'fixture',length_unit:'mm',origin:[0,0,0],rotation:[[1,0,0],[0,1,0],[0,0,1]]},parameters:{evaluation:{kind:'feature',frame_id:'fixture',length_unit:'mm'}}},quality:{usable:true,metrics:{observation_id:'obs'}},intervals:[{segment_id:'left',start:0,end:1},{segment_id:'right',start:10,end:11}]}]}}
}
it('preserves separate support intervals and never draws across the gap',()=>{
  const strokes=curveStrokes(curveItems(payload()),policy)
  expect(strokes).toHaveLength(4)
  expect(strokes.filter(s=>s.fitted).map(s=>s.points)).toEqual([[[0,0,0],[1,0,0]],[[10,0,0],[11,0,0]]])
})
it('draws inherited circle arcs on the resolved nonzero-height plane',()=>{
  const p=payload(),line=p.geometry.curves[0]!
  const circle={...line,kind:'circle',feature_id:'arc',points:[[1,0,3],[0,1,3]],support_point_count:2,
    topology:{point_count:2,segments:[{segment_id:'arc',start:0,count:2,closed:false,role:'open',orientation:'open'}]},
    geometry:{center:[0,0,3],normal:[0,0,1],radius:1},
    method:{...line.method,method_id:'fit-circle',evaluation:{...line.method.evaluation,origin:[0,0,3]}},
    intervals:[{segment_id:'arc',start_angle:0,sweep:Math.PI/2}]}
  const strokes=curveStrokes(curveItems({...p,geometry:{...p.geometry,curves:[circle]}}),policy)
  const fitted=strokes.find(s=>s.fitted)!
  expect(fitted.points[0]).toEqual([1,0,3])
  expect(fitted.points.at(-1)![0]).toBeCloseTo(0)
  expect(fitted.points.at(-1)![1]).toBeCloseTo(1)
  expect(fitted.points.every(point=>point[2]===3)).toBe(true)
  for(const evaluation of [undefined,null]){
    const broken={...circle,method:{...circle.method,evaluation}}
    expect(()=>curveItems({...p,geometry:{...p.geometry,curves:[broken]}})).toThrow('cloud_preview_invalid')
  }
})
it('rejects old format, wrong method version, cross-frame and mismatched segment evidence',()=>{
  for(const mode of ['format','frame','segment','version']){
    const p=payload()
    if(mode==='format')p.geometry.format_id='amvision.geometry-preview.v2'
    if(mode==='frame')p.spatial.frame_id='wrong'
    if(mode==='segment')p.geometry.curves[0]!.intervals[0]!.segment_id='wrong'
    if(mode==='version')p.geometry.curves[0]!.method.method_version=0
    expect(()=>curveItems(p)).toThrow('cloud_preview_invalid')
  }
})
it('reclaims curve buffers on redraw, capacity error and close',()=>{
  const scene=new Scene(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[0,0,0],policy,()=>{},()=>{},e=>{throw e})
  try{overlay.update({payload:payload()});expect(rendererUsage().gpuBytes).toBeGreaterThan(0);overlay.update({payload:{spatial:{frame_id:'fixture',length_unit:'mm'}}});expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0});expect(()=>curveStrokes(curveItems(payload()),{...policy,max_points:0})).toThrow('cloud_preview_capacity')}
  finally{overlay.dispose()}
  expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
})
