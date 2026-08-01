import { shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n, setI18nLocale } from '@/platform/i18n'
import WorkflowApplicationSummaryPanel from './WorkflowApplicationSummaryPanel.vue'
import WorkflowInspectorShell from './WorkflowInspectorShell.vue'
import WorkflowPreviewInputPanel from './WorkflowPreviewInputPanel.vue'

function mountInspector() {
  return shallowMount(WorkflowInspectorShell, {
    global: { plugins: [i18n] },
    props: {
      collapsed: false,
      showNewAppDraftPanel: false,
      newWorkflowAppDraft: {
        displayName: '',
        applicationId: '',
        graphId: '',
        graphVersion: '',
        description: '',
      },
      newWorkflowAppSaveBlocker: null,
      showAppContractPanel: true,
      appInputBindings: [],
      appOutputBindings: [],
      inspectorDetail: {
        kind: 'application' as const,
        applicationId: 'inspection-app',
        templateInputText: 'request_image_ref',
        templateOutputText: 'result',
        previewRunText: null,
      },
      readGraphNodeTitle: () => '',
      bindingEndpointText: () => '',
      bindingDisplayName: () => '',
      bindingKindSelectOptions: () => [],
      getBindingPayloadTypeId: () => '',
      previewInputBindings: [],
      previewInputState: {},
      previewBlockingMessages: [],
      imageRefTransportKindOptions: [],
      lastPreviewRun: null,
      lastPreviewFailureMessage: '',
      lastPreviewFailureNodeLabel: '',
      lastPreviewFailureLocation: '',
      lastPreviewFailureDetailMessage: '',
      lastPreviewFailureDetails: null,
      lastPreviewFailureDetailsJson: '',
      lastPreviewHttpResponse: null,
      lastPreviewHttpResponseBodyValue: null,
      lastPreviewHttpStatus: null,
      lastPreviewHttpResponseJson: '',
      lastPreviewHttpResponseBodyJson: '',
      hasPreviewNodeDisplays: false,
    },
  })
}

describe('WorkflowInspectorShell', () => {
  beforeEach(() => setI18nLocale('zh-CN'))

  it('在同一连续面板中同时显示属性和 Preview 输入', () => {
    const wrapper = mountInspector()

    expect(wrapper.find('.local-tabs').exists()).toBe(false)
    expect(wrapper.findComponent(WorkflowApplicationSummaryPanel).exists()).toBe(true)
    expect(wrapper.findComponent(WorkflowPreviewInputPanel).exists()).toBe(true)
  })
})
