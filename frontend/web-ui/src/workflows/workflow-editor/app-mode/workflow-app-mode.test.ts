import { describe, expect, it } from 'vitest'

import type { NodeDefinition, WorkflowGraphNode } from '../types'
import {
  buildWorkflowAppModeDisplayCandidates,
  orderWorkflowAppContractInputs,
  readWorkflowAppModeConfig,
  writeWorkflowAppModeConfig,
} from './workflow-app-mode'

describe('workflow app mode metadata', () => {
  it('round trips a normalized v1 config without changing sibling metadata', () => {
    const metadata = writeWorkflowAppModeConfig(
      { retained: true },
      {
        format_id: 'amvision.workflow-app-mode.v1',
        title: '  Station 1  ',
        displays: [{ node_id: 'preview-1', output_port: 'preview', title: ' Main ', size: 'large' }],
      },
    )

    expect(metadata.retained).toBe(true)
    expect(readWorkflowAppModeConfig(metadata)).toEqual({
      format_id: 'amvision.workflow-app-mode.v1',
      title: 'Station 1',
      displays: [{ node_id: 'preview-1', output_port: 'preview', title: 'Main', size: 'large' }],
    })
    expect(writeWorkflowAppModeConfig(metadata, null)).toEqual({ retained: true })
  })

  it('rejects duplicate, empty, or invalid display configuration', () => {
    expect(readWorkflowAppModeConfig({
      app_mode: {
        format_id: 'amvision.workflow-app-mode.v1',
        displays: [
          { node_id: 'preview-1', output_port: 'preview' },
          { node_id: 'preview-1', output_port: 'preview' },
        ],
      },
    })).toBeNull()
    expect(readWorkflowAppModeConfig({
      app_mode: { format_id: 'amvision.workflow-app-mode.v1', displays: [] },
    })).toBeNull()
    expect(readWorkflowAppModeConfig({
      app_mode: {
        format_id: 'amvision.workflow-app-mode.v1',
        displays: [{ node_id: 'preview-1', output_port: 'preview', size: 'huge' }],
      },
    })).toBeNull()
    expect(readWorkflowAppModeConfig({
      app_mode: {
        format_id: 'amvision.workflow-app-mode.v1',
        title: 'x'.repeat(129),
        displays: [{ node_id: 'preview-1', output_port: 'preview', size: 'medium' }],
      },
    })).toBeNull()
  })

  it('only exposes enabled ui.preview outputs', () => {
    const nodes = [
      { node_id: 'preview-1', node_type_id: 'preview', enabled: true },
      { node_id: 'preview-2', node_type_id: 'preview', enabled: false },
      { node_id: 'logic-1', node_type_id: 'logic', enabled: true },
    ] as WorkflowGraphNode[]
    const previewDefinition = {
      node_type_id: 'preview', display_name: 'Image Preview', capability_tags: ['ui.preview'],
      output_ports: [{ name: 'preview', display_name: 'Preview' }],
    } as unknown as NodeDefinition
    const logicDefinition = {
      node_type_id: 'logic', display_name: 'Logic', capability_tags: [], output_ports: [{ name: 'value' }],
    } as unknown as NodeDefinition

    expect(buildWorkflowAppModeDisplayCandidates(nodes, new Map([
      ['preview', previewDefinition], ['logic', logicDefinition],
    ]))).toEqual([{
      node_id: 'preview-1', output_port: 'preview', title: '', size: 'medium',
      node_title: 'Image Preview', output_title: 'Preview',
    }])
  })

  it('orders contract inputs by the explicit App Entry binding order', () => {
    const contract = {
      format_id: 'amvision.workflow-app-contract.v1',
      application_id: 'app-1',
      inputs: [
        { binding_id: 'request_file' },
        { binding_id: 'request_image_ref' },
        { binding_id: 'request_json' },
      ],
      outputs: [],
    } as never
    const application = {
      bindings: [
        { binding_id: 'request_image_ref', direction: 'input' },
        { binding_id: 'request_json', direction: 'input' },
        { binding_id: 'result', direction: 'output' },
        { binding_id: 'request_file', direction: 'input' },
      ],
    } as never

    expect(orderWorkflowAppContractInputs(application, contract).map((item) => item.binding_id)).toEqual([
      'request_image_ref',
      'request_json',
      'request_file',
    ])
  })
})
