import type { WorkflowTriggerSource } from '@/modules/integrations/services/trigger-source.service'
import type { WorkflowAppRuntimeSelectVersionInput } from './services/workflow-runtime.service'
import type { WorkflowAppRuntime, WorkflowAppVersion, WorkflowRuntimeRevision } from './types'

type RuntimeVersionSelectionTrigger = Pick<
  WorkflowTriggerSource,
  'workflow_runtime_id' | 'enabled' | 'desired_state' | 'observed_state'
>

export interface RuntimeVersionSelectionGate {
  runtime: WorkflowAppRuntime
  desiredRevision: WorkflowRuntimeRevision | null
  targetVersionId: string
  triggerSources: RuntimeVersionSelectionTrigger[]
  canWriteWorkflows: boolean
  runtimeBusy: boolean
  allowBreakingContract: boolean
  breakingChangeReason: string
}

export interface RuntimeVersionSelectionInputOptions {
  runtime: Pick<WorkflowAppRuntime, 'revision_generation'>
  targetVersionId: string
  allowBreakingContract: boolean
  breakingChangeReason: string
}

/** Runtime 创建与停机切版只允许选择当前仍为 published 的不可变版本。 */
export function selectRuntimeCandidateVersions(versions: WorkflowAppVersion[]): WorkflowAppVersion[] {
  return versions.filter((version) => version.state === 'published')
}

/**
 * 判断当前 target 是否已经由可用的 desired revision 表示。
 * failed revision 不是有效目标；重新选择同一版本会创建更大的 generation，属于恢复动作。
 */
export function isCurrentUsableDesiredVersion(
  desiredRevision: WorkflowRuntimeRevision | null,
  targetVersionId: string,
): boolean {
  if (!desiredRevision || desiredRevision.workflow_app_version_id !== targetVersionId) return false
  return desiredRevision.state === 'staged' || desiredRevision.state === 'active'
}

/**
 * 汇总 Runtime 版本选择的前端门禁。后端仍会用 expected_generation 做最终 CAS 校验。
 */
export function canSelectWorkflowRuntimeVersion(options: RuntimeVersionSelectionGate): boolean {
  const {
    runtime,
    desiredRevision,
    targetVersionId,
    triggerSources,
    canWriteWorkflows,
    runtimeBusy,
    allowBreakingContract,
    breakingChangeReason,
  } = options
  if (!canWriteWorkflows || runtimeBusy || !targetVersionId) return false
  if (runtime.desired_state !== 'stopped' || runtime.observed_state !== 'stopped') return false
  if (isCurrentUsableDesiredVersion(desiredRevision, targetVersionId)) return false

  const boundTriggers = triggerSources.filter(
    (source) => source.workflow_runtime_id === runtime.workflow_runtime_id,
  )
  if (boundTriggers.some(
    (source) => source.enabled || source.desired_state !== 'stopped' || source.observed_state !== 'stopped',
  )) return false
  return !allowBreakingContract || Boolean(breakingChangeReason.trim())
}

/** 构造选择版本请求；generation 始终取发起操作时页面持有的 Runtime CAS 值。 */
export function buildRuntimeVersionSelectionInput(
  options: RuntimeVersionSelectionInputOptions,
): WorkflowAppRuntimeSelectVersionInput {
  return {
    workflowAppVersionId: options.targetVersionId,
    expectedGeneration: options.runtime.revision_generation,
    allowBreakingContract: options.allowBreakingContract,
    breakingChangeReason: options.allowBreakingContract ? options.breakingChangeReason.trim() : null,
  }
}
