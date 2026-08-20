import { describe, expect, it } from 'vitest'

import type { WorkflowAppRuntime, WorkflowAppVersion, WorkflowRuntimeRevision } from './types'
import {
  buildRuntimeVersionSelectionInput,
  canSelectWorkflowRuntimeVersion,
  selectRuntimeCandidateVersions,
} from './runtime-version-selection'

function runtime(overrides: Partial<WorkflowAppRuntime> = {}): WorkflowAppRuntime {
  return {
    workflow_runtime_id: 'runtime-stable',
    revision_generation: 7,
    desired_state: 'stopped',
    observed_state: 'stopped',
    ...overrides,
  } as WorkflowAppRuntime
}

function revision(state: WorkflowRuntimeRevision['state'], versionId = 'version-v2'): WorkflowRuntimeRevision {
  return {
    workflow_runtime_revision_id: `revision-${state}`,
    workflow_runtime_id: 'runtime-stable',
    workflow_app_version_id: versionId,
    state,
  } as WorkflowRuntimeRevision
}

function canSelect(
  desiredRevision: WorkflowRuntimeRevision | null,
  targetVersionId = 'version-v2',
): boolean {
  return canSelectWorkflowRuntimeVersion({
    runtime: runtime(),
    desiredRevision,
    targetVersionId,
    triggerSources: [],
    canWriteWorkflows: true,
    runtimeBusy: false,
    allowBreakingContract: false,
    breakingChangeReason: '',
  })
}

describe('Workflow Runtime version selection', () => {
  it('allows a reset failed Runtime to reselect the same version with the current generation', () => {
    expect(canSelect(revision('failed'))).toBe(true)

    expect(buildRuntimeVersionSelectionInput({
      runtime: runtime({ revision_generation: 8 }),
      targetVersionId: 'version-v2',
      allowBreakingContract: false,
      breakingChangeReason: '',
    })).toEqual({
      workflowAppVersionId: 'version-v2',
      expectedGeneration: 8,
      allowBreakingContract: false,
      breakingChangeReason: null,
    })
  })

  it.each(['active', 'staged'] as const)(
    'keeps the same usable %s revision disabled as a no-op',
    (state) => {
      expect(canSelect(revision(state))).toBe(false)
    },
  )

  it('allows recovery when the desired revision summary is missing', () => {
    expect(canSelect(null)).toBe(true)
  })

  it('allows selecting another published version from a usable revision', () => {
    expect(canSelect(revision('active', 'version-v1'), 'version-v2')).toBe(true)
  })

  it('preserves stopped Trigger and breaking-change gates', () => {
    const base = {
      runtime: runtime(),
      desiredRevision: revision('failed'),
      targetVersionId: 'version-v2',
      canWriteWorkflows: true,
      runtimeBusy: false,
      allowBreakingContract: false,
      breakingChangeReason: '',
    }
    expect(canSelectWorkflowRuntimeVersion({
      ...base,
      triggerSources: [{
        workflow_runtime_id: 'runtime-stable',
        enabled: true,
        desired_state: 'running',
        observed_state: 'running',
      }],
    })).toBe(false)
    expect(canSelectWorkflowRuntimeVersion({
      ...base,
      triggerSources: [],
      allowBreakingContract: true,
    })).toBe(false)
  })

  it('never exposes archived versions as Runtime creation or switch candidates', () => {
    const versions = [
      { workflow_app_version_id: 'version-published', state: 'published' },
      { workflow_app_version_id: 'version-archived', state: 'archived' },
      { workflow_app_version_id: 'version-failed', state: 'failed' },
    ] as WorkflowAppVersion[]

    expect(selectRuntimeCandidateVersions(versions).map((version) => version.workflow_app_version_id))
      .toEqual(['version-published'])
  })
})
