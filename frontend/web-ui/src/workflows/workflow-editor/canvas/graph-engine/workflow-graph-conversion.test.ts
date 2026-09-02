import { describe, expect, it } from 'vitest'

import type { WorkflowGraphTemplate } from '../../types'
import { canvasSnapshotToWorkflowTemplate, workflowTemplateToCanvasSnapshot } from './workflow-graph-conversion'

function createTemplate(): WorkflowGraphTemplate {
  return {
    format_id: 'amvision.workflow-graph-template.v1',
    template_id: 'workflow-graph-20260902090000',
    template_version: '1.0.0',
    display_name: '说明节点往返测试',
    description: '',
    nodes: [],
    edges: [],
    template_inputs: [],
    template_outputs: [],
    groups: [{
      group_id: 'group-1',
      name: '说明分组',
      enabled: true,
      rect: { x: 0, y: 0, width: 800, height: 600 },
      member_node_ids: [],
      member_note_ids: ['note-1'],
      membership_policy: 'full-containment',
      color: '#667085',
      collapsed: false,
      locked: false,
      metadata: {},
    }],
    notes: [{
      note_id: 'note-1',
      title: '操作说明',
      content: '## 步骤\n\n1. 输入图片\n2. 执行流程',
      content_format: 'markdown',
      rect: { x: 80, y: 60, width: 360, height: 240 },
      tone: 'info',
      collapsed: false,
      locked: false,
      metadata: { source: 'test' },
    }],
    metadata: {},
  }
}

describe('workflow graph conversion', () => {
  it('无损往返说明节点和分组归属', () => {
    const source = createTemplate()
    const snapshot = workflowTemplateToCanvasSnapshot(source)

    snapshot.notes[0]!.title = '已编辑说明'
    snapshot.notes[0]!.rect.x = 120

    const exported = canvasSnapshotToWorkflowTemplate(source, snapshot)
    expect(exported.notes[0]).toMatchObject({
      note_id: 'note-1',
      title: '已编辑说明',
      rect: { x: 120, y: 60, width: 360, height: 240 },
    })
    expect(exported.groups[0]?.member_note_ids).toEqual(['note-1'])
    expect(source.notes[0]?.title).toBe('操作说明')
    expect(source.notes[0]?.rect.x).toBe(80)
  })

  it('兼容没有 notes 和 member_note_ids 的旧文档', () => {
    const legacy = createTemplate() as WorkflowGraphTemplate & {
      notes?: WorkflowGraphTemplate['notes']
    }
    delete (legacy as unknown as Record<string, unknown>).notes
    delete (legacy.groups[0] as unknown as Record<string, unknown>).member_note_ids

    const snapshot = workflowTemplateToCanvasSnapshot(legacy)
    expect(snapshot.notes).toEqual([])
    expect(snapshot.groups[0]?.member_note_ids).toEqual([])
  })
})
