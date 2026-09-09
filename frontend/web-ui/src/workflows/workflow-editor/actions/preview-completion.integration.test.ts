import { computed, ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWorkflowEditorActions } from './useWorkflowEditorActions'
import { useWorkflowSaveRunOrchestration } from './useWorkflowSaveRunOrchestration'
import { useWorkflowSaveRunFeedback } from './useWorkflowSaveRunFeedback'
import { useWorkflowPreviewDisplays } from '../preview/useWorkflowPreviewDisplays'
import type { WorkflowPreviewRun } from '../types'

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
vi.mock('@/platform/i18n', () => ({ translate: (key: string) => key }))
vi.mock('../services/workflow-template.service', () => ({ validateWorkflowTemplate: vi.fn() }))
vi.mock('../services/workflow-application.service', () => ({ validateWorkflowApplication: vi.fn() }))
vi.mock('../services/workflow-app.service', () => ({ saveWorkflowApp: vi.fn() }))
vi.mock('../services/workflow-runtime.service', () => ({readProjectObjectContentBlob:vi.fn()}))

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  setupTransport()
})

it('renders image and false value after async completion through the editor feedback pipeline', async () => {
  const running = { preview_run_id: 'run-1', project_id: 'p', application_id: 'app', state: 'running', node_records: [] } as unknown as WorkflowPreviewRun

  const displays = useWorkflowPreviewDisplays()
  const actions = useWorkflowEditorActions()
  const feedback = useWorkflowSaveRunFeedback({
    replaceRouteWithSavedApp: vi.fn(), refreshSavedWorkflowApp: vi.fn(), resetPreviewRun: actions.resetPreviewRun,
    revokePreviewImageObjectUrls: displays.revokePreviewImageObjectUrls, refreshPreviewNodeDisplays: displays.refreshPreviewNodeDisplays,
    focusGraphNode: vi.fn(), setActionError: actions.setActionError, setActionStatus: actions.setActionStatus,
  })
  actions.setPreviewFeedback(feedback.applyPreviewRunFeedback)
  const template = { nodes: [{ node_id: 'image', node_type_id: 'core.io.image-preview', parameters: {} }], template_inputs: [], edges: [] }
  const orchestration = useWorkflowSaveRunOrchestration({
    workflowApp: ref({}), isNewApp: computed(() => false), selectedProjectId: computed(() => 'p'),
    readNewWorkflowAppSaveBlocker: () => null, buildCurrentTemplate: () => template, buildCurrentApplication: () => ({ application_id: 'app', bindings: [] }),
    runWorkflowPreflight: () => null, applyWorkflowValidationIssue: vi.fn(), buildPreviewInputBindings: async () => ({ inputBindings: {}, fileUploads: [] }),
    saveWorkflowDocument: actions.saveWorkflowDocument, runWorkflowPreview: actions.runWorkflowPreview,
    applyWorkflowSaveFeedback: feedback.applyWorkflowSaveFeedback, applyPreviewRunFeedback: feedback.applyPreviewRunFeedback,
    clearActionMessages: actions.clearActionMessages, revokePreviewImageObjectUrls: displays.revokePreviewImageObjectUrls,
    setActionError: actions.setActionError, clearContextMenu: vi.fn(),
  } as unknown as Parameters<typeof useWorkflowSaveRunOrchestration>[0])
  await orchestration.runPreview()
  expect(displays.hasPreviewNodeDisplays.value).toBe(false)
  const terminal = { ...running, state: 'succeeded', node_records: [
    { node_id: 'image', node_type_id: 'core.io.image-preview', outputs: { body: { type: 'image-preview', image: { transport_kind: 'inline-base64', media_type: 'image/png', image_base64: 'aW1hZ2U=', width: 2, height: 2 } } } },
    { node_id: 'value', node_type_id: 'core.io.value-preview', outputs: { body: { type: 'value-preview', value: false } } },
  ] } as unknown as WorkflowPreviewRun
  for (const node of terminal.node_records as any[]) {
    send('display.updated',{node_id:node.node_id,node_type_id:node.node_type_id,output_port:'body',payload:node.outputs.body})
  }
  await flushPromises()
  expect(actions.previewing.value).toBe(true)
  send('run.finished',{status:'succeeded'})
  await flushPromises()
  expect(displays.getPreviewNodeDisplay('value')?.payload.value).toBe(false)
  expect(displays.getPreviewNodeDisplay('image')?.image?.src).toContain('data:image/png;base64,')
  expect(actions.previewing.value).toBe(false)
  displays.revokePreviewImageObjectUrls()
})
