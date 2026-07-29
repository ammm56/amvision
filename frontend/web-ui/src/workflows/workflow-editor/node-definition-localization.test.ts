import { describe, expect, it } from 'vitest'

import { resolveNodeDefinitionDisplayName } from './node-definition-localization'
import type { NodeDefinition } from './types'

function buildDefinition(): NodeDefinition {
  return {
    format_id: 'amvision.node-definition.v1',
    node_type_id: 'custom.opencv.draw-detections',
    display_name: 'Draw Detections',
    category: 'opencv.output.render',
    description: '',
    implementation_kind: 'custom-node',
    runtime_kind: 'python-callable',
    input_ports: [],
    output_ports: [],
    parameter_schema: {},
    parameter_ui_schema: null,
    capability_tags: [],
    runtime_requirements: {},
    node_pack_id: 'opencv.nodes',
    node_pack_version: '0.1.3',
    metadata: {
      i18n: {
        display_name: {
          'zh-CN': '绘制检测框',
          'en-US': 'Draw Detections',
        },
      },
    },
  }
}

describe('node definition display name', () => {
  it('keeps the canonical English node name in every locale', () => {
    const definition = buildDefinition()

    expect(resolveNodeDefinitionDisplayName(definition, 'zh-CN')).toBe('Draw Detections')
    expect(resolveNodeDefinitionDisplayName(definition, 'en-US')).toBe('Draw Detections')
    expect(resolveNodeDefinitionDisplayName(definition, 'ja-JP')).toBe('Draw Detections')
    expect(resolveNodeDefinitionDisplayName(definition, 'ko-KR')).toBe('Draw Detections')
  })
})
