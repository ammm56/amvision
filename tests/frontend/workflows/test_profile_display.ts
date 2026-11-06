import { afterEach, expect, it } from 'vitest'
import { profileIdentity, profilePoint } from '@/workflows/workflow-editor/point-cloud/profile-display'
import { decodeCloudPreview, rendererUsage } from '@/workflows/workflow-editor/point-cloud/preview-data'

const source={format_id:'amvision.calibrated-profiles.v1',point_count:6,profile_count:4,calibration_id:'scanner',calibration_revision:'r1'}
const policy={max_points:100,max_data_bytes:10000,max_cpu_bytes:100000,max_gpu_bytes:100000,max_canvas_pixels:100000,max_position_error:.001}
afterEach(()=>expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0}))
it('keeps acquired profile IDs distinct from logical record and generated vertex IDs',()=>{
  expect(profileIdentity(source,6,1)).toEqual({count:4,empty:1,id:'scanner',revision:'r1'})
  expect(profilePoint(8n,2n,6)).toEqual({line:'8',sample:'2'})
  expect(()=>profilePoint(8,2n,6)).toThrow()
  expect(()=>profilePoint(8n,6n,6)).toThrow()
  expect(()=>profileIdentity(source,5,1)).toThrow()
  expect(()=>profileIdentity(source,6,4)).toThrow()
  expect(profileIdentity(null,6,null)).toBeNull()
})
async function body() {
  const bytes=new Uint8Array(96), view=new DataView(bytes.buffer)
  ;[1,2,3,4,5,6].forEach((x,i)=>view.setFloat64(i*8,x,true))
  ;[1n,5n,3n,9n,1n,0n].forEach((x,i)=>view.setBigUint64(48+i*8,x,true))
  const fields=[{name:'positions',dtype:'float64',components:3,count:2,offset:0,byte_length:48},
    ...['source_indices','acquisition_line_id','profile_sample_index'].map((name,i)=>({name,dtype:'uint64',components:1,count:2,offset:48+i*16,byte_length:16}))]
  const checksum=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('')
  return {type:'point-cloud-preview',format_id:'amvision.point-cloud-preview.v1',state:'ready',point_count:2,source_point_count:6,display_point_count:2,
    vertex_kind:'source',profile_source:source,profile_empty_count:1,color:{mode:'solid'},render_origin:[1,2,3],bounds:{min:[1,2,3],max:[4,5,6]},
    data:{content_length:96,encoding:'base64',checksum_algorithm:'sha256',checksum,content:btoa(String.fromCharCode(...bytes)),fields}}
}
it('decodes the bounded sampled profile identity and releases failed or cancelled data',async()=>{
  const value=await body(), data=await decodeCloudPreview(value,policy,new AbortController().signal)
  try { expect(data.point(1).profile).toEqual({line:'9',sample:'0'});expect(data.point(1).sourceIndex).toBe('5') } finally { data.dispose() }
  await expect(decodeCloudPreview({...value,profile_empty_count:4},policy,new AbortController().signal)).rejects.toThrow()
  const controller=new AbortController();controller.abort()
  await expect(decodeCloudPreview(value,policy,controller.signal)).rejects.toThrow()
  await expect(decodeCloudPreview({...value,data:{...value.data,fields:value.data.fields.slice(0,-1)}},policy,new AbortController().signal)).rejects.toThrow()
})
