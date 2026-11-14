import {expect,it} from 'vitest'
import {mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {measurementItems} from '@/workflows/workflow-editor/point-cloud/measurement-display'
import MeasurementSummary from '@/workflows/workflow-editor/point-cloud/MeasurementSummary.vue'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
import {Scene,PerspectiveCamera,Points} from 'three'
function payload(valid=true){const summary={observation_id:'obs',target_count:2,source_point_count:9,valid,reason:valid?null:'target_support_failed',diagnostic_only:!valid,counts:{covered:valid?2:1,extended:0,invalid_target:0,invalid_reference:0,outside_support:valid?0:1,support_quality_failed:0,extension_limit_exceeded:0},diagnostic:{count:2,minimum:-1,maximum:1,peak_to_valley:2,mean:0,rms:1,minimum_source:{source_index:2,logical_index:0,tie_count:1},maximum_source:{source_index:3,logical_index:1,tie_count:1}}};return {observation_id:'obs',spatial:{frame_id:'fixture',length_unit:'mm'},bounds:{min:[0,0,-1],max:[1,1,1]},measurements:{format_id:'amvision.measurement-evidence3d.v1',observation_id:'obs',frame_id:'fixture',length_unit:'mm',items:[{kind:'measure-deviation',item_id:'mean',component:'mean',value:valid?0:null,valid,reason:summary.reason,summary,method:{method_id:'measure-deviation',method_version:1,parameters:{frame_id:'fixture',length_unit:'mm'}},quality:{usable:valid,metrics:{observation_id:'obs',items:[]}},support:[{role:'reference',point_count:5,plane:{geometry:{normal:[0,0,1]}}},{role:'target',point_count:2}],geometry:valid?{kind:'datum-deviation',endpoints:[[0,0,-1],[1,1,1]]}:null}]}}}
it('shows valid zero separately from failure diagnostics and clears old results',async()=>{
  const good=measurementItems(payload()),bad=measurementItems(payload(false)),w=mount(MeasurementSummary,{props:{items:good,selected:'mean',unit:'mm'},global:{plugins:[createI18n({legacy:false,locale:'zh-CN'})]}})
  try{expect(w.text()).toContain('0.0000');expect(w.text()).toContain('目标点数');await w.setProps({items:bad});expect(w.text()).not.toContain('0.0000');expect(w.text()).toContain('诊断统计');await w.setProps({items:[],selected:''});expect(w.text()).not.toContain('诊断统计')}finally{w.unmount()}
})
it('rejects cross-observation or incomplete counts instead of drawing stale evidence',()=>{
  const p=payload();p.measurements.items[0]!.summary.observation_id='old';expect(()=>measurementItems(p)).toThrow();const q=payload();q.measurements.items[0]!.summary.counts.covered=1;expect(()=>measurementItems(q)).toThrow()
})
it('marks measured extremes without drawing a false distance and releases graphics',()=>{
  const scene=new Scene(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[0,0,0],{max_points:100,max_data_bytes:10000,max_cpu_bytes:100000,max_gpu_bytes:100000,max_canvas_pixels:10000,max_position_error:.01},()=>{},()=>{},e=>{throw e})
  try{overlay.update({payload:payload(),selectedMeasurement:'mean'});let points=0;scene.traverse(o=>{if(o instanceof Points)points++});expect(points).toBe(2);overlay.update({payload:payload(false)});expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})}finally{overlay.dispose()}
})
