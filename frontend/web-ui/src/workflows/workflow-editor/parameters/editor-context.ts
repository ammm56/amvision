/** 专属编辑器只读查看显式上游连接；不改变连线或执行语义。 */
import type { InjectionKey } from 'vue'
import type { WorkflowJsonObject } from '../types'
import type { NumericItemProviders } from './static-numeric-items'

export interface ParameterEditorSource {
  nodeId: string
  nodeTypeId: string
  parameters: WorkflowJsonObject
  outputPort?: string
  /** 仅当前成功且未过期的 Preview 原端口输出，不作为配置持久化。 */
  previewOutput?: unknown
}

export type ParameterEditorSources = Record<string, ParameterEditorSource[]>
export const parameterEditorSourcesKey: InjectionKey<(nodeId: string) => ParameterEditorSources> =
  Symbol('workflow-parameter-sources')

/** 资源保存仅接受当前已成功完成的预览，上传/执行/失败状态均不能复用上次结果。 */
export const parameterPreviewStateKey: InjectionKey<() => {runId:string; succeeded:boolean}> = Symbol('workflow-parameter-preview-state')

/** 仅显式选择当前成功运行的有界显示，不读取完整点云或推断输入空间。 */
export interface ParameterCloudPreview { id:string; label:string; projectId:string; payload:Record<string,unknown> }
export const parameterCloudPreviewsKey: InjectionKey<() => ParameterCloudPreview[]> = Symbol('workflow-parameter-cloud-previews')

export const parameterNumericItemsKey: InjectionKey<NumericItemProviders> = Symbol('workflow-numeric-item-providers')
/** 编辑时提示下游引用影响，保存/发布时统一拦截已知错误。 */
export const parameterDraftIssuesKey: InjectionKey<(nodeId:string, parameter:string, value:unknown) => string[]> = Symbol('workflow-parameter-draft-issues')
