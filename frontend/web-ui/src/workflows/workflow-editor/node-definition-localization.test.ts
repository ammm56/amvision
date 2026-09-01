import { describe, expect, it } from 'vitest'

import {
  resolveNodeDefinitionDisplayName,
  resolveNodeParameterDescription,
  resolveNodeParameterDisplayName,
} from './node-definition-localization'
import type { NodeDefinition, NodeParameterUiField } from './types'

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

describe('save location parameter localization', () => {
  const field: NodeParameterUiField = {
    parameter_name: 'save_location',
    display_name: 'Save Location',
    description: '',
    group_id: '',
    order: 0,
    required: false,
    hidden: false,
    readonly: false,
    default_value: '',
    enum_options: [],
    json_schema: { type: 'string' },
  }

  it('uses concise locale-specific labels and dual-path help', () => {
    expect(resolveNodeParameterDisplayName(field, 'zh-CN')).toBe('保存位置')
    expect(resolveNodeParameterDisplayName(field, 'en-US')).toBe('Save location')
    expect(resolveNodeParameterDisplayName(field, 'ja-JP')).toBe('保存先')
    expect(resolveNodeParameterDisplayName(field, 'ko-KR')).toBe('저장 위치')
    expect(resolveNodeParameterDescription(field, 'zh-CN')).toContain('ObjectStore')
    expect(resolveNodeParameterDescription(field, 'en-US')).toContain('local filesystem')
  })
})

describe('image save parameter localization', () => {
  const buildField = (parameterName: string, title: string, description: string): NodeParameterUiField => ({
    parameter_name: parameterName,
    display_name: title,
    description,
    group_id: '',
    order: 0,
    required: true,
    hidden: false,
    readonly: false,
    default_value: '',
    enum_options: [],
    json_schema: {
      type: 'string',
      'x-amvision-i18n': {
        title: {
          'zh-CN': title,
          'en-US': parameterName === 'save_directory' ? 'Save directory' : 'File name',
        },
        description: {
          'zh-CN': description,
          'en-US': parameterName === 'save_directory'
            ? 'Relative directory uses ObjectStore.'
            : 'Supports {YYYYMMDDhhmmssSSS}.',
        },
      },
    },
  })

  it('shows directory and file name as two independent localized fields', () => {
    const directoryField = buildField('save_directory', '保存目录', '相对目录保存到 ObjectStore。')
    const fileNameField = buildField('file_name', '文件名', '支持 {YYYYMMDDhhmmssSSS}。')

    expect(resolveNodeParameterDisplayName(directoryField, 'zh-CN')).toBe('保存目录')
    expect(resolveNodeParameterDisplayName(directoryField, 'en-US')).toBe('Save directory')
    expect(resolveNodeParameterDisplayName(fileNameField, 'zh-CN')).toBe('文件名')
    expect(resolveNodeParameterDisplayName(fileNameField, 'en-US')).toBe('File name')
    expect(resolveNodeParameterDescription(fileNameField, 'zh-CN')).toContain('{YYYYMMDDhhmmssSSS}')
  })
})
