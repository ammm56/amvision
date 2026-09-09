import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWorkflowEditorActions, type WorkflowPreviewRunActionInput } from './useWorkflowEditorActions'
const io = vi.hoisted(() => ({ options: null as any, revision: '', seq: 0, create: vi.fn(), submit: vi.fn(), release: vi.fn(), cancel: vi.fn(), validate: vi.fn() }))
vi.mock('../services/workflow-preview-session.service', () => ({
 PREVIEW_FORMAT: 'amvision.workflow-preview-session.v1', createPreviewSession: io.create, submitPreviewSession: io.submit, releasePreviewSession: io.release, cancelPreviewSession: io.cancel,
 PreviewSessionConnection: class {
   constructor(public identity: any, options: any) { io.options = options }
   async connect() { send('session.snapshot', {watermark: 0, run: null, nodes: [], displays: [], values: []}, 0) }
   close() {}
   async readBlob() { return new Blob(['image'], { type: 'image/png' }) }
 }
}))
const identity = {format_id:'amvision.workflow-preview-session.v1', session_id:'session',epoch:'epoch',memory_limit_bytes:1024}
function send(type:string, payload:object, seq=++io.seq) { io.options.onEvent({...identity, run_id:seq?'run':null, document_revision:seq?io.revision:null,type,payload,seq}) }
function setupTransport() {
 io.seq=0; io.revision=''; sessionStorage.clear(); io.create.mockResolvedValue(identity); io.release.mockResolvedValue(undefined)
 io.submit.mockImplementation(async (_sid, body) => { io.revision=body.document_revision; send('run.accepted',{run_id:'run',document_revision:io.revision,state:'accepted'}); return {...identity,run_id:'run',state:'accepted'} })
}

vi.mock('@/platform/i18n', () => ({translate:(key:string)=>key}))
vi.mock('../services/workflow-template.service', () => ({validateWorkflowTemplate:io.validate}))
vi.mock('../services/workflow-application.service', () => ({validateWorkflowApplication:vi.fn()}))
vi.mock('../services/workflow-app.service', () => ({saveWorkflowApp:vi.fn()}))
const input={projectId:'p',application:{application_id:'app'},template:{nodes:[]},inputBindings:{}} as unknown as WorkflowPreviewRunActionInput
beforeEach(()=>{setActivePinia(createPinia());vi.clearAllMocks();io.validate.mockResolvedValue({});setupTransport()})
it('guards duplicate execution during validation and until the actual terminal event',async()=>{
 let finish!:()=>void;io.validate.mockImplementation(()=>new Promise<void>(resolve=>{finish=resolve}))
 const actions=useWorkflowEditorActions();const pending=actions.runWorkflowPreview(input)
 expect(actions.previewing.value).toBe(true);expect(await actions.runWorkflowPreview(input)).toBeNull();expect(io.submit).not.toHaveBeenCalled()
 finish();await pending;expect(io.submit).toHaveBeenCalledTimes(1);expect(actions.previewing.value).toBe(true)
 send('run.finished',{status:'succeeded'});expect(actions.previewing.value).toBe(false);actions.resetPreviewRun()
})
it('submits explicit node scope to the v1 memory session',async()=>{
 const actions=useWorkflowEditorActions();await actions.runWorkflowPreview({...input,executionScope:{kind:'node',targetNodeId:'mask-editor-1'}})
 expect(io.submit).toHaveBeenCalledWith('session',expect.objectContaining({execution_scope:{kind:'node',target_node_id:'mask-editor-1'}}))
 expect(io.submit.mock.calls[0]![1]).not.toHaveProperty('execution_metadata');actions.resetPreviewRun()
})
it('cancellation remains busy until confirmed and only sends one request',async()=>{
 const actions=useWorkflowEditorActions();await actions.runWorkflowPreview(input)
 await actions.cancelPreviewRun();await actions.cancelPreviewRun();expect(io.cancel).toHaveBeenCalledTimes(1)
 expect(actions.previewing.value).toBe(true);expect(actions.previewCancelling.value).toBe(true)
 send('run.finished',{status:'cancelled'});expect(actions.previewing.value).toBe(false);expect(actions.previewCancelling.value).toBe(false);actions.resetPreviewRun()
})
it('explicit reset releases the session and removes restore identity',async()=>{
 const actions=useWorkflowEditorActions();await actions.runWorkflowPreview(input);expect(sessionStorage.length).toBe(1)
 actions.resetPreviewRun();expect(io.release).toHaveBeenCalledWith('session');expect(sessionStorage.length).toBe(0)
 await actions.restorePreviewRun('other','app');expect(io.create).toHaveBeenCalledTimes(1)
})
