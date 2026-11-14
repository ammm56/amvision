import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {newEdgeSettings,edgeIssues} from '../../../custom_nodes/metrology3d_nodes/frontend/edge-form'
import {dimensionFeatureChoices} from '../../../custom_nodes/metrology3d_nodes/frontend/dimension-form'
import {decodeEdgeDiagnostic} from '@/workflows/workflow-editor/point-cloud/edge-display'
import EdgeDiagnosticPanel from '@/workflows/workflow-editor/point-cloud/EdgeDiagnosticPanel.vue'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
import {readCloudCapabilities} from '@/workflows/workflow-editor/services/measurement-resource.service'
vi.mock('@/workflows/workflow-editor/services/measurement-resource.service',()=>({readCloudCapabilities:vi.fn()}))
const policy={max_points:100,max_data_bytes:8192,max_cpu_bytes:65536,max_gpu_bytes:65536,max_canvas_pixels:65536,max_position_error:.0001}
beforeEach(async()=>{const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');vi.stubGlobal('crypto',webcrypto);vi.mocked(readCloudCapabilities).mockResolvedValue({renderer:policy} as Awaited<ReturnType<typeof readCloudCapabilities>>)})
afterEach(()=>{expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0});vi.restoreAllMocks();vi.unstubAllGlobals()})
it.each(['height-jump','normal-crease','sampling-boundary'])('keeps physical values unset and clears unrelated %s fields',kind=>{
  const next=newEdgeSettings(kind,{feature_id:'edge',surface:{fake:1},targets:[{fake:1}],evaluation:{frame_id:'part',length_unit:'mm'}})
  expect(next.surface).toBeUndefined();expect(next.targets).toBeUndefined();expect(edgeIssues(next).length).toBeGreaterThan(0)
  if(kind==='sampling-boundary'){expect(next.feature_id).toBeUndefined();expect(next.selection).toBeUndefined()}
})
it('reads measured target IDs from their public selection, not a previous method',()=>{
  const choices=dimensionFeatureChoices({features:[{nodeId:'edge',nodeTypeId:'custom.metrology3d.extract-boundary',outputPort:'features',parameters:{settings:{feature_id:'edge',method:{kind:'normal-crease'},selection:{targets:[{segment_id:'side'},{group_id:'arc'}]}}}}]})
  expect(choices[0]).toMatchObject({segments:['side'],groups:['arc']})
})
async function payload(){
  const raw=new Uint8Array(136),view=new DataView(raw.buffer)
  for(let i=0;i<2;i++){const offset=i*68;view.setFloat64(offset,i,true);view.setBigUint64(offset+24,BigInt(i+10),true);view.setUint8(offset+33,i);view.setBigInt64(offset+36,BigInt(1-i),true);for(const k of [44,52,60])view.setFloat64(offset+k,1,true)}
  return {cloud_id:'c',observation_id:'o',point_count:2,source_point_count:12,vertex_kind:'source',edge_diagnostics:{format_id:'amvision.edge-preview.v1',state:'ready',cloud_id:'c',observation_id:'o',edge:{format_id:'amvision.edge-evidence.v1',method:{kind:'height-jump'},evaluation:{length_unit:'mm'},input_count:2,record_count:2,reports:[{target_id:'edge',reason:'pairing_ambiguous',record_counts:{paired:2},quality:null,segments:[]}]},sampling:null,data:{encoding:'base64',content_length:raw.length,checksum_algorithm:'sha256',checksum:[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(b=>b.toString(16).padStart(2,'0')).join(''),content:btoa(String.fromCharCode(...raw))}}}
}
it('decodes source rows and reciprocal records with exact resource release',async()=>{const p=await payload(),d=await decodeEdgeDiagnostic(p,policy,new AbortController().signal);expect(d.record(0)).toMatchObject({source:10,partner:1,position:[0,0,0]});d.dispose();expect(()=>d.record(0)).toThrow()})
it('updates selected source and pair when the record input changes, then clears invalid selection',async()=>{
  const p=await payload(),w=mount(EdgeDiagnosticPanel,{props:{payload:p,projectId:'p'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
  await vi.waitFor(()=>expect(w.text()).toContain('Source row 10'))
  await w.get('input[type="number"]').setValue('1');expect(w.text()).toContain('Source row 11')
  expect(w.emitted('select')?.at(-1)?.[0]).toMatchObject({points:[[1,0,0],[0,0,0]]})
  await w.get('input[type="number"]').setValue('2');expect(w.emitted('select')?.at(-1)?.[0]).toMatchObject({points:null})
  expect(w.get('button').attributes('disabled')).toBeDefined()
  }finally{w.unmount()}
})
it.each(['identity','checksum','capacity','source','count'])('rejects invalid %s without a reservation leak',async kind=>{const p=await payload();let limits=policy;if(kind==='identity')p.edge_diagnostics.cloud_id='other';if(kind==='checksum')p.edge_diagnostics.data.checksum='0'.repeat(64);if(kind==='capacity')limits={...policy,max_cpu_bytes:1};if(kind==='source')p.source_point_count=10;if(kind==='count')p.edge_diagnostics.edge.record_count=3;await expect(decodeEdgeDiagnostic(p,limits,new AbortController().signal)).rejects.toThrow()})
it('shows failures and drops stale requests after switching and unmounting',async()=>{
  const p=await payload();let finish!:(v:Awaited<ReturnType<typeof readCloudCapabilities>>)=>void
  vi.mocked(readCloudCapabilities).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}))
  const w=mount(EdgeDiagnosticPanel,{props:{payload:p,projectId:'p'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  await w.setProps({payload:{...p,edge_diagnostics:{state:'unavailable',reason:'preview_size_limit'}}});await flushPromises();finish({renderer:policy} as Awaited<ReturnType<typeof readCloudCapabilities>>);await flushPromises();expect(w.text()).toContain('preview_size_limit');expect(w.emitted('select')).toBeUndefined();w.unmount()
})
