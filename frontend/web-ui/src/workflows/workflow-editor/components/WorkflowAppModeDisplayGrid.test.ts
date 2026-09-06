import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import type { PreviewNodeDisplay } from '../preview/useWorkflowPreviewDisplays'
import WorkflowAppModeDisplayGrid from './WorkflowAppModeDisplayGrid.vue'

function display(kind: 'image' | 'value'): PreviewNodeDisplay {
  return {
    nodeId: kind,
    nodeTypeId: `core.io.${kind}-preview`,
    outputName: 'body',
    title: kind,
    kind,
    payload: {},
    statusText: '',
    formattedValue: kind === 'value' ? '{\n  "state": "ok"\n}' : '',
    image: kind === 'image'
      ? {
          nodeId: kind,
          title: 'image',
          src: 'data:image/png;base64,AA==',
          displaySrc: null,
          sourceSrc: null,
          statusText: '',
          transportKind: 'base64',
          mediaType: 'image/png',
          width: 1920,
          height: 1768,
          objectKey: null,
          displayWidth: null,
          displayHeight: null,
          displayObjectKey: null,
          sourceWidth: 1920,
          sourceHeight: 1768,
          sourceObjectKey: null,
          displayScale: null,
          previewImageKind: null,
          overlays: [],
          interaction: null,
        }
      : null,
    galleryItems: [],
    columns: [],
    rows: [],
    rowCount: null,
    emptyText: null,
  }
}

describe('WorkflowAppModeDisplayGrid', () => {
  it('renders image and value previews together in their bounded slots', () => {
    const wrapper = mount(WorkflowAppModeDisplayGrid, {
      props: {
        config: {
          format_id: 'amvision.workflow-app-mode.v1',
          title: '',
          displays: [
            { node_id: 'image', output_port: 'body', title: 'Image', size: 'medium' },
            { node_id: 'value', output_port: 'body', title: 'Value', size: 'medium' },
          ],
        },
        displays: {
          '["image","body"]': display('image'),
          '["value","body"]': display('value'),
        },
        nodeTitles: {},
        hasRun: true,
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('.app-mode-displays__slot--image img').exists()).toBe(true)
    expect(wrapper.find('.app-mode-displays__slot--value .workflow-graph-node-preview__json').text())
      .toContain('"state": "ok"')
  })
})
