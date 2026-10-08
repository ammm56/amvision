/** 专属编辑器只读查看显式上游连接；不改变连线或执行语义。 */
import type { InjectionKey } from 'vue'
import type { WorkflowJsonObject } from '../types'

export interface ParameterEditorSource {
  nodeId: string
  nodeTypeId: string
  parameters: WorkflowJsonObject
}

export type ParameterEditorSources = Record<string, ParameterEditorSource[]>
export const parameterEditorSourcesKey: InjectionKey<(nodeId: string) => ParameterEditorSources> =
  Symbol('workflow-parameter-sources')
