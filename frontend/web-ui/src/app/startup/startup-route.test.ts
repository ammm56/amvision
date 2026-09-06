import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/shared/api/error'
import type { RuntimePreviewSnapshot } from '@/workflows/workflow-editor/services/workflow-runtime-preview.service'
import { resolvePostAuthenticationRoute } from './startup-route'

const preference = {
  mode: 'workflow-runtime-app-mode' as const,
  projectId: 'project-1',
  applicationId: 'workflow-app-1',
  workflowRuntimeId: 'workflow-runtime-1',
}

function snapshot(overrides: Partial<RuntimePreviewSnapshot> = {}): RuntimePreviewSnapshot {
  return {
    workflow_runtime_id: 'workflow-runtime-1',
    project_id: 'project-1',
    application_id: 'workflow-app-1',
    app_mode: { format_id: 'amvision.workflow-app-mode.v1', title: '', displays: [] },
    ...overrides,
  } as RuntimePreviewSnapshot
}

describe('resolvePostAuthenticationRoute', () => {
  it('keeps an explicit route ahead of the startup preference', async () => {
    const getSnapshot = vi.fn()
    await expect(resolvePostAuthenticationRoute({
      explicitRedirect: '/deployments',
      preference,
      getSnapshot,
    })).resolves.toEqual({ path: '/deployments', resetPreference: false })
    expect(getSnapshot).not.toHaveBeenCalled()
  })

  it('keeps projects as the unchanged default', async () => {
    await expect(resolvePostAuthenticationRoute({
      explicitRedirect: undefined,
      preference: { mode: 'projects' },
    })).resolves.toEqual({ path: '/projects', resetPreference: false })
  })

  it('opens the configured Runtime App Mode after identity validation', async () => {
    await expect(resolvePostAuthenticationRoute({
      explicitRedirect: undefined,
      preference,
      getSnapshot: vi.fn().mockResolvedValue(snapshot()),
    })).resolves.toEqual({
      path: '/workflows/runtime/workflow-runtime-1/app-mode',
      resetPreference: false,
    })
  })

  it('resets a mismatched or permanently unavailable target', async () => {
    await expect(resolvePostAuthenticationRoute({
      explicitRedirect: undefined,
      preference,
      getSnapshot: vi.fn().mockResolvedValue(snapshot({ project_id: 'project-2' })),
    })).resolves.toEqual({ path: '/projects', resetPreference: true })

    await expect(resolvePostAuthenticationRoute({
      explicitRedirect: undefined,
      preference,
      getSnapshot: vi.fn().mockRejectedValue(new ApiError(404, { message: 'not found' })),
    })).resolves.toEqual({ path: '/projects', resetPreference: true })
  })

  it('resets a target whose active version no longer exposes App Mode', async () => {
    await expect(resolvePostAuthenticationRoute({
      explicitRedirect: undefined,
      preference,
      getSnapshot: vi.fn().mockResolvedValue(snapshot({ app_mode: null })),
    })).resolves.toEqual({ path: '/projects', resetPreference: true })
  })

  it('preserves the target on transient backend failures', async () => {
    await expect(resolvePostAuthenticationRoute({
      explicitRedirect: undefined,
      preference,
      getSnapshot: vi.fn().mockRejectedValue(new ApiError(503, { message: 'offline' })),
    })).resolves.toEqual({
      path: '/workflows/runtime/workflow-runtime-1/app-mode',
      resetPreference: false,
    })
  })
})
