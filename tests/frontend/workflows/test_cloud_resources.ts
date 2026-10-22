import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import CloudResourcePicker from '@/workflows/workflow-editor/point-cloud/CloudResourcePicker.vue'
import CloudResourceParameter from '@/workflows/workflow-editor/point-cloud/CloudResourceParameter.vue'
import { useWorkflowNodeParameters } from '@/workflows/workflow-editor/parameters/useWorkflowNodeParameters'
import { useWorkflowPreviewDisplays } from '@/workflows/workflow-editor/preview/useWorkflowPreviewDisplays'
import { useWorkflowPreviewInputs } from '@/workflows/workflow-editor/preview/useWorkflowPreviewInputs'
import { useWorkflowAppModeInputs } from '@/workflows/workflow-editor/app-mode/useWorkflowAppModeInputs'
import { buildWorkflowAppRequestExamples } from '@/workflows/workflow-editor/workflow-app-request-examples'
import type { FlowApplicationBinding } from '@/workflows/workflow-editor/types'
import type { WorkflowAppContractInput } from '@/workflows/workflow-editor/app-mode/workflow-app-mode'

const mocks = vi.hoisted(() => ({ project: {} as {selectedProjectId:string}, list: vi.fn(), capability: vi.fn(), import: vi.fn(), remove: vi.fn() }))
vi.mock('@/app/stores/project.store', () => ({ useProjectStore: () => mocks.project }))
vi.mock('@/workflows/workflow-editor/services/measurement-resource.service', () => ({
  listMeasurementResources: mocks.list, readCloudCapabilities: mocks.capability,
  importCloudResource: mocks.import, deleteMeasurementResource: mocks.remove, resourceVersionPath: () => '/resource',
}))
const reference = {project_id:'p',resource_id:'cloud-1',kind:'point-cloud' as const,version:1,sha256:'a'.repeat(64)}
const document = {reference,name:'Fixture cloud',content:{format_id:'amvision.measurement-resource.v2',point_cloud:{point_count:3,spatial:{length_unit:null},fields:[]}}}
const dialog = {props:['title','confirmDisabled','showConfirm'],emits:['confirm','cancel'],template:`<div role="dialog"><h2>{{title}}</h2><slot/><button @click="$emit('cancel')">Cancel dialog</button><button v-if="showConfirm !== false" :disabled="confirmDisabled" @click="$emit('confirm')">Confirm dialog</button></div>`}
const global = () => ({plugins:[createI18n({legacy:false,locale:'en-US'})],stubs:{Teleport:true,ConfirmDialog:dialog}})
let wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => { mocks.project = reactive({selectedProjectId:'p'}); mocks.list.mockResolvedValue([document]); mocks.capability.mockResolvedValue({max_archive_bytes:1024,renderer:null}) })
afterEach(() => { for (const wrapper of wrappers) wrapper.unmount(); wrappers=[]; vi.resetAllMocks() })
function picker() {const w=mount(CloudResourcePicker,{props:{modelValue:reference},global:global()});wrappers.push(w);return w}

it('cancels a pending resource list when project changes and ignores its late result', async()=>{
  let resolve!: (v:unknown)=>void
  mocks.list.mockImplementation(()=>new Promise(r=>{resolve=r}))
  const w=picker();await w.get('button').trigger('click');await flushPromises()
  const signal=mocks.list.mock.calls[0]![1]
  mocks.project.selectedProjectId='other';await flushPromises();expect(signal.aborted).toBe(true)
  resolve([document]);await flushPromises();expect(w.find('[role=dialog]').exists()).toBe(false)
  expect(w.emitted('update:modelValue')).toBeUndefined()
})
it('aborts upload on unmount and does not select a late server commit',async()=>{
  let resolve!: (v:unknown)=>void
  mocks.import.mockImplementation(()=>new Promise(r=>{resolve=r}))
  const w=picker();await w.get('button').trigger('click');await flushPromises()
  await w.get('input[maxlength]').setValue('Imported')
  const input=w.get('input[type=file]');Object.defineProperty(input.element,'files',{value:[new File(['zip'],'cloud.zip')]})
  await input.trigger('change');await flushPromises();const signal=mocks.import.mock.calls[0]![4]
  w.unmount();wrappers=[];expect(signal.aborted).toBe(true)
  resolve(document);await flushPromises();expect(w.emitted('update:modelValue')).toBeUndefined()
})
it('shows referenced-version deletion failure in the resource dialog',async()=>{
  mocks.remove.mockRejectedValue(new Error('Resource is referenced'))
  const w=picker();await w.get('button').trigger('click');await flushPromises()
  await w.get('button[title="Delete version"]').trigger('click')
  await w.findAll('[role=dialog]')[1]!.findAll('button').at(-1)!.trigger('click');await flushPromises()
  expect(w.findAll('[role=dialog]')).toHaveLength(1)
  expect(w.get('[role=alert]').text()).toBe('Resource is referenced')
  expect(w.findAll('tbody tr')).toHaveLength(1)
})
it('does not leave an uncommitted asset mode after cancelling selection',async()=>{
  const w=mount(CloudResourceParameter,{props:{modelValue:{kind:'file'},schema:{'x-ui-widget':'cloud-source','x-live-source-kind':'file'}},global:global()});wrappers.push(w)
  await w.get('select').setValue('asset');await flushPromises()
  await w.get('[role=dialog]').findAll('button').find(b=>b.text()==='Cancel dialog')!.trigger('click')
  expect((w.get('select').element as HTMLSelectElement).value).toBe('file')
  expect(w.emitted('update:modelValue')).toBeUndefined()
})
it('clears the edited file-options draft when committing an asset source',()=>{
  const drafts=ref<Record<string,string>>({})
  const api=useWorkflowNodeParameters({complexParameterDrafts:drafts,readNodeTitle:()=>'',readParameterLabel:()=>'',setStatusMessage:()=>{},setErrorMessage:()=>{}})
  const field={parameter_name:'file_options',widget:'auto',json_schema:{type:'object'},required:false} as any
  const source={parameter_name:'source',json_schema:{'x-ui-widget':'cloud-source','x-asset-clears':['file_options']}} as any
  const node={node:{node_id:'read',parameters:{file_options:{old:true}}},definition:{parameter_ui_schema:{fields:[field]}}} as any
  const input=window.document.createElement('textarea');input.value='{"old":true}'
  input.addEventListener('input',event=>api.updateNodeParameterJsonDraft(node,field,event));input.dispatchEvent(new Event('input'))
  expect(api.hasPendingNodeParameterDrafts()).toBe(true)
  api.updateNodeParameterValue(node,source,{kind:'asset',reference})
  expect(api.hasPendingNodeParameterDrafts()).toBe(false);expect(drafts.value).toEqual({})
  expect(api.commitPendingNodeParameterDrafts([node])).toBe(true)
  expect(node.node.parameters.file_options).toBeUndefined()
})
it('resolves cloud display data using the existing Preview Blob channel',async()=>{
  const view=useWorkflowPreviewDisplays()
  const body={type:'point-cloud-preview',state:'ready',data:{content:'AA=='}}
  const readMemoryBlob=vi.fn().mockResolvedValue({size:200,text:async()=>JSON.stringify(body)})
  await view.refreshDisplayOutputs({project_id:'p',preview_run_id:'r',readMemoryBlob},[{nodeId:'cloud',nodeTypeId:'custom.metrology3d.cloud-preview',outputName:'body',payload:{...body,data:null,paged:true,value_descriptor:{transport_kind:'preview-memory',blob_id:'b'}}}])
  expect(view.previewNodeDisplays.value.cloud!.kind).toBe('cloud')
  expect(view.previewNodeDisplays.value.cloud!.payload).toEqual(body)
  view.revokePreviewImageObjectUrls();expect(view.previewNodeDisplays.value).toEqual({})
})

it('does not submit same-host cloud input as browser JSON or generate a false HTTP example',async()=>{
  const binding: FlowApplicationBinding = {
    binding_id:'cloud', direction:'input', template_port_id:'cloud', binding_kind:'request-point-cloud',
    required:true, config:{}, metadata:{},
  }
  const input: WorkflowAppContractInput = {
    binding_id:'cloud', template_port_id:'cloud', binding_kind:'request-point-cloud',
    payload_type_id:'point-cloud-ref.v1', required:true, config:{}, payload_schema:{}, request_schema:{},
    allowed_media_types:[], max_inline_bytes:null, max_file_bytes:null, max_files:null,
    transports:['local-shared-memory'], charset:null,
  }
  const preview=useWorkflowPreviewInputs({getBindingPayloadTypeId:()=>input.payload_type_id})
  preview.initializePreviewInputs([binding]);preview.previewInputState.value.cloud!.plainValue='forged';preview.previewInputState.value.cloud!.jsonValue='{}'
  expect(preview.hasPreviewBindingValue(binding)).toBe(false)
  expect(await preview.buildPreviewInputBindings([binding])).toEqual({inputBindings:{},fileUploads:[]})
  const app=useWorkflowAppModeInputs();app.initialize([input]);app.states.value.cloud!.json='{}'
  expect(app.hasValue(input)).toBe(false);expect(await app.build([input])).toEqual({inputBindings:{},fileUploads:[]})
  expect(buildWorkflowAppRequestExamples({format_id:'amvision.workflow-app-contract.v1',inputs:[{...input}]},'runtime')).toBeNull()
})
