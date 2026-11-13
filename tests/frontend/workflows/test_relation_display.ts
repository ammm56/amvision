import {expect,it} from 'vitest'
import {mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {measurementItems} from '@/workflows/workflow-editor/point-cloud/measurement-display'
import {measurementUnit} from '@/workflows/workflow-editor/point-cloud/arc-display'
import MeasurementSummary from '@/workflows/workflow-editor/point-cloud/MeasurementSummary.vue'
import RelationEvidenceSummary from '@/workflows/workflow-editor/point-cloud/RelationEvidenceSummary.vue'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
import {relationDistanceStrokes} from '@/workflows/workflow-editor/point-cloud/relation-display'
import {Scene,PerspectiveCamera,LineSegments} from 'three'

function payload(){
  const selector=(position:number[])=>({kind:'coordinate',position})
  const support=(role:string,point:number[])=>({role,point_count:2,source_point_count:2,point:{point,reason:null,origin:'specified',source_index:null,logical_index:null,feature_id:null},feature:null,plane:null})
  return {observation_id:'obs',spatial:{frame_id:'fixture',length_unit:'mm'},bounds:{min:[0,0,0],max:[3,4,0]},measurements:{format_id:'amvision.measurement-evidence3d.v1',observation_id:'obs',frame_id:'fixture',length_unit:'mm',items:[{
    kind:'measure-relation',component:'distance',item_id:'relation',valid:true,value:5,reason:null,diagnostic:null as null|{role:string;stage:string},
    method:{method_id:'measure-relation',method_version:1,parameters:{item_id:'relation',space:{kind:'spatial',frame_id:'fixture',length_unit:'mm'},relation:{kind:'point-point',reference:selector([0,0,0]),target:selector([3,4,0])}}},
    support:[support('reference',[0,0,0]),support('target',[3,4,0])],geometry:{kind:'geometric-relation',contacts_unique:true,endpoints:[[0,0,0],[3,4,0]],support_pairs:[]},quality:{usable:true,metrics:{observation_id:'obs',items:[]}},
  }]}}
}

it('does not call a rejected nonunique relation valid',()=>{
  const item={...measurementItems(payload())[0]!,valid:false,value:null,reason:'quality_failed',geometry:{contacts_unique:false}}
  const wrapper=mount(RelationEvidenceSummary,{props:{item,zh:true}})
  try{expect(wrapper.text()).toContain('最近点对不唯一');expect(wrapper.text()).not.toContain('距离有效')}finally{wrapper.unmount()}
})

it('shows rejected closest-pair evidence even when invalid results have no drawable geometry',()=>{
  const base=measurementItems(payload())[0]!
  for(const value of [0,1,null]){
    const item={...base,valid:false,value:null,reason:'insufficient_quality',geometry:null,quality:{...base.quality,metrics:{observation_id:'obs',items:[{item_id:'contacts_unique',unit:'1',valid:value!==null,value,reason:value===null?'unavailable':null}]}}}
    const wrapper=mount(RelationEvidenceSummary,{props:{item,zh:true}})
    try{
      expect(wrapper.text().includes('最近点对不唯一')).toBe(value===0)
      expect(wrapper.text()).not.toContain('距离有效')
    }finally{wrapper.unmount()}
  }
})

it('keeps zero and negative values visible and never replaces an invalid value with zero',()=>{
  for(const value of [0,-.7071067811865475]){
    const item={...measurementItems(payload())[0]!,value}
    const wrapper=mount(MeasurementSummary,{props:{items:[item],selected:'relation',unit:'mm'},global:{plugins:[createI18n({legacy:false,locale:'zh-CN'})]}})
    try{expect(wrapper.text()).toContain(value.toFixed(4))}finally{wrapper.unmount()}
  }
  const item={...measurementItems(payload())[0]!,valid:false,value:null,reason:'outside_support'}
  const wrapper=mount(MeasurementSummary,{props:{items:[item],selected:'relation',unit:'mm'},global:{plugins:[createI18n({legacy:false,locale:'zh-CN'})]}})
  try{expect(wrapper.text()).not.toContain('0.0000');expect(wrapper.text()).toContain('outside_support')}finally{wrapper.unmount()}
})

it('reads relation evidence and separates angle units from distances',()=>{
  const value=payload(),before=JSON.stringify(value)
  expect(measurementItems(value)[0]).toMatchObject({kind:'measure-relation',value:5,component:'distance',query:null})
  expect(measurementUnit({kind:'measure-relation',component:'angle'},'mm')).toBe('rad')
  expect(measurementUnit({kind:'measure-relation',component:'distance'},'mm')).toBe('mm')
  expect(JSON.stringify(value)).toBe(before)
  value.measurements.items[0]!.support[0]!.point.origin='measured'
  expect(()=>measurementItems(value)).toThrow('cloud_preview_invalid')
})

it('rejects wrong spaces and invented closest pairs',()=>{
  const value=payload()
  value.measurements.items[0]!.method.parameters.space.frame_id='other'
  expect(()=>measurementItems(value)).toThrow()
  const next=payload();next.measurements.items[0]!.geometry.contacts_unique=false
  expect(()=>measurementItems(next)).toThrow()
})

it('uses existing result selection, shows point source, and clears old relation on switching',async()=>{
  const items=measurementItems(payload()),before=JSON.stringify(items)
  const wrapper=mount(MeasurementSummary,{props:{items,selected:'relation',unit:'mm'},global:{plugins:[createI18n({legacy:false,locale:'zh-CN'})]}})
  try{
    expect(wrapper.text()).toContain('点点距离')
    expect(wrapper.text()).toContain('指定坐标')
    expect(wrapper.text()).toContain('5.0000')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['relation']])
    await wrapper.setProps({items:[],selected:''})
    expect(wrapper.text()).not.toContain('指定坐标')
    expect(wrapper.text()).not.toContain('5.0000')
    expect(JSON.stringify(items)).toBe(before)
  }finally{wrapper.unmount()}
})

it('reuses overlay drawing and releases all relation geometry on switch and disposal',()=>{
  const scene=new Scene(),policy={max_points:100,max_data_bytes:10000,max_cpu_bytes:100000,max_gpu_bytes:100000,max_canvas_pixels:10000,max_position_error:.01}
  const overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[0,0,0],policy,()=>{},()=>{},e=>{throw e})
  try{
    overlay.update({payload:payload(),selectedMeasurement:'relation'})
    let lines=0;scene.traverse(o=>{if(o instanceof LineSegments)lines++})
    expect(lines).toBeGreaterThan(0)
    expect(rendererUsage().gpuBytes).toBeGreaterThan(0)
    const empty=payload();empty.measurements.items=[]
    overlay.update({payload:empty})
    expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
  }finally{overlay.dispose()}
  expect(scene.children).toHaveLength(0)
})

it('draws projected dimensions separately from original 3D construction endpoints',()=>{
  const method={parameters:{space:{kind:'projection',plane:{origin:[0,0,2],rotation:[[1,0,0],[0,1,0],[0,0,1]]}}}}
  const geometry={endpoints:[[0,0,10],[3,4,20]]},before=JSON.stringify({method,geometry})
  const strokes=relationDistanceStrokes(method,geometry)
  expect(strokes.dimension.map(p=>p.toArray())).toEqual([[0,0,2],[3,4,2]])
  expect(strokes.dimension[0]!.distanceTo(strokes.dimension[1]!)).toBe(5)
  expect(strokes.construction.map(p=>p.toArray())).toEqual([[0,0,10],[0,0,2],[3,4,20],[3,4,2]])
  expect(JSON.stringify({method,geometry})).toBe(before)
  expect(relationDistanceStrokes(method,{endpoints:null})).toEqual({dimension:[],construction:[]})
})
