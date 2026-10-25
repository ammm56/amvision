import {expect,it} from 'vitest'
import {Scene,PerspectiveCamera,LineSegments} from 'three'
import {measurementItems} from '@/workflows/workflow-editor/point-cloud/measurement-display'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'

const policy={max_points:100,max_data_bytes:10000,max_cpu_bytes:100000,max_gpu_bytes:100000,max_canvas_pixels:10000,max_position_error:.001}
/** 独立有限显示证据；不使用渲染器输出生成期望端点。 */
function payload(kind:string,component:string,valid=true):Record<string,unknown>{
  const support=(role:string)=>({role,content_sha256:'a'.repeat(64),point_count:4,source_point_count:4,vertex_kind:'source',bounds:{min:[0,0,0],max:[4,2,0]},feature:null})
  const corners=[[0,0,0],[4,0,0],[4,2,0],[0,2,0]]
  const extent={kind:'projected-extents',origin:[0,0,0],axes:[[1,0,0],[0,1,0]],limits:[0,0,4,2],corners,contacts:corners.map((point,vertex_index)=>({point,projected:point,vertex_index,source_index:vertex_index,lineage:null,tied_count:1})),candidates:null}
  const pair={kind:'edge-pair-distance',query_position:[0,0,0],direction:[1,0,0],endpoints:[[0,0,0],[4,0,0]],line_parameters:[0,0],query_parameters:[0,4],segment_ids:['a','b'],signed_distance:4}
  const hole={kind:'circle-dimensions',circle:{center:[0,0,0],normal:[0,0,1],radius:2},display_direction:[1,0,0],diameter_endpoints:[[-2,0,0],[2,0,0]]}
  return {observation_id:'obs',spatial:{frame_id:'fixture',length_unit:'mm'},bounds:{min:[-2,-2,0],max:[4,2,0]},measurements:{format_id:'amvision.measurement-evidence3d.v1',observation_id:'obs',frame_id:'fixture',length_unit:'mm',items:[{kind,component,item_id:'quantity',valid,value:valid?(component==='center_x'?0:4):null,reason:valid?null:'outside_support',diagnostic:valid?null:{stage:'support'},geometry:valid?(kind==='measure-extents'?extent:kind==='measure-edge-pair'?pair:hole):null,support:kind==='measure-edge-pair'?[support('reference'),support('target')]:[support('source')],method:{method_version:1,method_id:kind},quality:{usable:valid,metrics:{observation_id:'obs',items:[]}}}]}}
}
it.each([
  ['measure-extents','u',[0,0,0,4,0,0]],
  ['measure-edge-pair','distance',[0,0,0,4,0,0]],
  ['measure-hole','diameter',[-2,0,0,2,0,0]],
])('renders %s exact construction endpoints and frees all buffers', (kind,component,expected)=>{
  const scene=new Scene(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[0,0,0],policy,()=>{},()=>{},e=>{throw e})
  try{
    const body=payload(kind as string,component as string)
    expect(measurementItems(body)).toHaveLength(1)
    overlay.update({payload:body})
    const lines:LineSegments[]=[];scene.traverse(o=>{if(o instanceof LineSegments)lines.push(o)})
    expect(lines).toHaveLength(1)
    expect(Array.from(lines[0]!.geometry.getAttribute('position').array)).toEqual(expected)
    overlay.update({payload:payload(kind as string,component as string,false)})
    expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
    overlay.update({payload:body});expect(rendererUsage().gpuBytes).toBeGreaterThan(0)
  }finally{overlay.dispose()}
  expect(scene.children).toHaveLength(0);expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
})
it('renders a zero-valued center only as selected center evidence and rejects malformed input',()=>{
  const body=payload('measure-hole','center_x')
  expect(measurementItems(body)[0]!.value).toBe(0)
  const scene=new Scene(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[0,0,0],policy,()=>{},()=>{},e=>{throw e})
  try{
    overlay.update({payload:body,selectedMeasurement:'quantity'})
    expect(rendererUsage().gpuBytes).toBeGreaterThan(0)
    const wrong={...body,spatial:{frame_id:'wrong',length_unit:'mm'}}
    expect(()=>overlay.update({payload:wrong})).toThrow()
    expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
  }finally{overlay.dispose()}
})
