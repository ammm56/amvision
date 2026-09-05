import { expect, test, type Page, type Route } from 'playwright/test'

const API_ORIGIN = 'http://127.0.0.1:5600'
const API_PREFIX = '/api/v1'
const DEFAULT_TOKEN = 'amvision-default-user-token'

const currentUser = {
  principal_id: 'user-e2e',
  principal_type: 'user',
  project_ids: ['project-1'],
  scopes: ['*'],
  username: 'e2e-user',
  display_name: 'E2E User',
  auth_provider_kind: 'local',
  auth_credential_kind: 'user-token',
}

const bootstrap = {
  auth_mode: 'local',
  bearer_auth_enabled: true,
  websocket_query_token_enabled: false,
  current_user: currentUser,
  providers: [],
  visible_projects: [{ project_id: 'project-1', display_name: 'E2E Project' }],
  capabilities: {},
  devices: {},
}

const application = {
  project_id: 'project-1',
  object_key: 'workflows/projects/project-1/applications/app-e2e/application.json',
  application_id: 'app-e2e',
  display_name: 'E2E Inspection App',
  description: 'Playwright workflow gate',
  created_at: '2026-08-16T01:00:00+08:00',
  updated_at: '2026-08-16T01:05:00+08:00',
  created_by: 'user-e2e',
  updated_by: 'user-e2e',
  template_id: 'template-e2e',
  template_version: '1.0.0',
  template_summary: null,
  binding_count: 2,
  input_binding_ids: ['image'],
  output_binding_ids: ['detections'],
}

const runtime = {
  format_id: 'workflow-app-runtime-v1',
  workflow_runtime_id: 'runtime-e2e',
  project_id: 'project-1',
  application_id: 'app-e2e',
  display_name: 'E2E Runtime',
  application_snapshot_object_key: 'workflows/runtime/runtime-e2e/application.json',
  template_snapshot_object_key: 'workflows/runtime/runtime-e2e/template.json',
  desired_state: 'running',
  observed_state: 'running',
  request_timeout_seconds: 30,
  heartbeat_interval_seconds: 5,
  heartbeat_timeout_seconds: 20,
  created_at: '2026-08-16T01:00:00+08:00',
  updated_at: '2026-08-16T01:05:00+08:00',
  heartbeat_at: '2026-08-16T01:05:00+08:00',
  health_summary: { ready: true },
  metadata: {},
}

function responseHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    'access-control-allow-origin': 'http://127.0.0.1:5601',
    'access-control-allow-headers': 'authorization,content-type',
    'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
    'content-type': 'application/json; charset=utf-8',
    ...extra,
  }
}

async function fulfillJson(
  route: Route,
  payload: unknown,
  headers: Record<string, string> = {},
): Promise<void> {
  await route.fulfill({
    status: 200,
    headers: responseHeaders(headers),
    body: JSON.stringify(payload),
  })
}

async function installApiMocks(page: Page): Promise<{
  authenticatedRequests: string[]
  applicationListRequests: string[]
}> {
  const authenticatedRequests: string[] = []
  const applicationListRequests: string[] = []

  await page.route(`${API_ORIGIN}${API_PREFIX}/**`, async (route) => {
    const request = route.request()
    if (request.method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: responseHeaders() })
      return
    }

    const url = new URL(request.url())
    const path = url.pathname.slice(API_PREFIX.length)
    if (request.headers().authorization === `Bearer ${DEFAULT_TOKEN}`) {
      authenticatedRequests.push(path)
    }

    if (path === '/system/bootstrap') {
      await fulfillJson(route, bootstrap)
      return
    }
    if (path === '/system/me') {
      await fulfillJson(route, currentUser)
      return
    }
    if (path === '/projects') {
      await fulfillJson(route, bootstrap.visible_projects, {
        'x-offset': '0',
        'x-limit': '100',
        'x-total-count': '1',
        'x-has-more': 'false',
      })
      return
    }
    if (path === '/workflows/node-catalog') {
      await fulfillJson(route, {
        node_pack_manifests: [],
        payload_contracts: [],
        node_definitions: [
          { node_type_id: 'core.image-input' },
          { node_type_id: 'core.detection-output' },
        ],
        palette_groups: [],
      })
      return
    }
    if (path === '/workflows/projects/project-1/applications') {
      applicationListRequests.push(request.url())
      await fulfillJson(route, [application], {
        'x-offset': '0',
        'x-limit': '50',
        'x-total-count': '1',
        'x-has-more': 'false',
      })
      return
    }
    if (path === '/workflows/app-runtimes') {
      await fulfillJson(route, [runtime], {
        'x-offset': '0',
        'x-limit': '100',
        'x-total-count': '1',
        'x-has-more': 'false',
      })
      return
    }
    if (path === '/workflows/app-runtimes/runtime-e2e/health') {
      await fulfillJson(route, runtime)
      return
    }

    await route.fulfill({
      status: 404,
      headers: responseHeaders(),
      body: JSON.stringify({ error: { code: 'e2e_mock_missing', message: path } }),
    })
  })

  return { authenticatedRequests, applicationListRequests }
}

test('workflow apps 页面完成鉴权、加载、健康刷新和手动刷新', async ({ page }) => {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.addInitScript(() => {
    localStorage.clear()
    sessionStorage.clear()
    localStorage.setItem('amvision.web-ui.locale', 'zh-CN')
  })
  const requests = await installApiMocks(page)

  await page.goto('/workflows/apps')

  await expect(page).toHaveURL(/\/workflows\/apps$/)
  await expect(page.getByRole('heading', { level: 1, name: '应用' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'E2E Inspection App' })).toBeVisible()
  await expect(page.getByText('app-e2e', { exact: true })).toBeVisible()
  await expect(page.getByText('running', { exact: true })).toBeVisible()
  await expect(page.locator('.summary-grid > div').nth(0)).toContainText('1')
  await expect(page.locator('.summary-grid > div').nth(1)).toContainText('1')
  await expect(page.locator('.summary-grid > div').nth(2)).toContainText('1')
  await expect(page.locator('.summary-grid > div').nth(3)).toContainText('2')

  await page.getByRole('button', { name: '刷新' }).click()
  await expect.poll(() => requests.applicationListRequests.length).toBeGreaterThanOrEqual(2)

  expect(requests.authenticatedRequests).toContain('/system/me')
  expect(requests.authenticatedRequests).toContain(
    '/workflows/projects/project-1/applications',
  )
  expect(consoleErrors).toEqual([])
  expect(pageErrors).toEqual([])
})

test('workflow app 详情使用不可变版本创建 Runtime 并以 generation CAS 切换版本', async ({ page }) => {
  const versionV1 = {
    format_id: 'amvision.workflow-app-version.v1',
    workflow_app_version_id: 'workflow-app-version-v1',
    project_id: 'project-1',
    application_id: 'app-e2e',
    version_number: 1,
    display_version: 'v1',
    release_notes: 'initial',
    application_snapshot_object_key: 'workflows/projects/project-1/applications/app-e2e/versions/workflow-app-version-v1/application.snapshot.json',
    template_snapshot_object_key: 'workflows/projects/project-1/applications/app-e2e/versions/workflow-app-version-v1/template.snapshot.json',
    contract_snapshot_object_key: 'workflows/projects/project-1/applications/app-e2e/versions/workflow-app-version-v1/contract.snapshot.json',
    dependency_manifest_object_key: 'workflows/projects/project-1/applications/app-e2e/versions/workflow-app-version-v1/dependencies.json',
    content_fingerprint: 'sha256:v1',
    contract_fingerprint: 'sha256:contract',
    state: 'published',
    created_at: '2026-08-18T01:00:00+08:00',
    completed_at: '2026-08-18T01:00:01+08:00',
    created_by: 'user-e2e',
    error: null,
  }
  const versionV2 = {
    ...versionV1,
    workflow_app_version_id: 'workflow-app-version-v2',
    version_number: 2,
    display_version: 'v2',
    release_notes: 'compatible update',
    content_fingerprint: 'sha256:v2',
    created_at: '2026-08-19T01:00:00+08:00',
    completed_at: '2026-08-19T01:00:01+08:00',
  }
  const applicationDocument = {
    ...application,
    valid: true,
    draft_fingerprint: 'sha256:draft-v2',
    application: {
      format_id: 'amvision.flow-application.v1',
      application_id: 'app-e2e',
      display_name: 'E2E Inspection App',
      description: 'Playwright workflow version gate',
      runtime_mode: 'python-json-workflow',
      template_ref: {
        template_id: 'template-e2e',
        template_version: '1.0.0',
        source_kind: 'json-file',
        metadata: {},
      },
      bindings: [],
      metadata: {},
    },
  }
  const templateDocument = {
    valid: true,
    project_id: 'project-1',
    object_key: 'workflows/projects/project-1/templates/template-e2e/versions/1.0.0/template.json',
    template_id: 'template-e2e',
    template_version: '1.0.0',
    node_count: 0,
    edge_count: 0,
    template_input_ids: [],
    template_output_ids: [],
    referenced_node_type_ids: [],
    created_at: '2026-08-18T01:00:00+08:00',
    updated_at: '2026-08-19T01:00:00+08:00',
    template: {
      format_id: 'amvision.workflow-graph-template.v1',
      template_id: 'template-e2e',
      template_version: '1.0.0',
      display_name: 'E2E graph',
      description: '',
      nodes: [],
      edges: [],
      template_inputs: [],
      template_outputs: [],
      groups: [],
      metadata: {},
    },
  }
  let runtimeState = {
    ...runtime,
    desired_state: 'stopped',
    observed_state: 'stopped',
    active_revision_id: 'workflow-runtime-revision-v1',
    desired_revision_id: 'workflow-runtime-revision-v1',
    revision_generation: 1,
    heartbeat_at: null,
    worker_process_id: null,
  }
  let revisions = [
    {
      format_id: 'amvision.workflow-runtime-revision.v1',
      workflow_runtime_revision_id: 'workflow-runtime-revision-v1',
      workflow_runtime_id: 'runtime-e2e',
      generation: 1,
      workflow_app_version_id: 'workflow-app-version-v1',
      execution_policy_snapshot_object_key: null,
      expected_snapshot_fingerprint: 'sha256:v1',
      state: 'active',
      created_at: '2026-08-18T01:00:00+08:00',
      activated_at: '2026-08-18T01:00:01+08:00',
      failed_at: null,
      error: null,
      created_by: 'user-e2e',
    },
  ]
  const selectVersionBodies: Record<string, unknown>[] = []
  const createRuntimeBodies: Record<string, unknown>[] = []

  await page.addInitScript(() => {
    localStorage.clear()
    sessionStorage.clear()
    localStorage.setItem('amvision.web-ui.locale', 'zh-CN')
  })
  await page.route(`${API_ORIGIN}${API_PREFIX}/**`, async (route) => {
    const request = route.request()
    if (request.method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: responseHeaders() })
      return
    }
    const path = new URL(request.url()).pathname.slice(API_PREFIX.length)
    if (path === '/system/bootstrap') return fulfillJson(route, bootstrap)
    if (path === '/system/me') return fulfillJson(route, currentUser)
    if (path === '/projects') return fulfillJson(route, bootstrap.visible_projects)
    if (path === '/workflows/projects/project-1/applications/app-e2e') return fulfillJson(route, applicationDocument)
    if (path === '/workflows/projects/project-1/applications/app-e2e/versions') return fulfillJson(route, [versionV2, versionV1])
    if (path === '/workflows/projects/project-1/applications/app-e2e/versions/workflow-app-version-v1') return fulfillJson(route, versionV1)
    if (path === '/workflows/projects/project-1/applications/app-e2e/versions/workflow-app-version-v2') return fulfillJson(route, versionV2)
    if (path === '/workflows/projects/project-1/templates/template-e2e/versions/1.0.0') return fulfillJson(route, templateDocument)
    if (path === '/workflows/trigger-sources') return fulfillJson(route, [])
    if (path === '/workflows/app-runtimes' && request.method() === 'GET') return fulfillJson(route, [runtimeState])
    if (path === '/workflows/app-runtimes/runtime-e2e/health') return fulfillJson(route, runtimeState)
    if (path === '/workflows/app-runtimes/runtime-e2e/revisions') return fulfillJson(route, revisions)
    if (path.startsWith('/workflows/app-runtimes/runtime-e2e/revisions/')) {
      const revisionId = path.split('/').at(-1)
      return fulfillJson(route, revisions.find((revision) => revision.workflow_runtime_revision_id === revisionId) ?? revisions[0])
    }
    if (path === '/workflows/app-runtimes/runtime-e2e/select-version') {
      const body = request.postDataJSON() as Record<string, unknown>
      selectVersionBodies.push(body)
      const nextRevision = {
        ...revisions[0],
        workflow_runtime_revision_id: 'workflow-runtime-revision-v2',
        generation: 2,
        workflow_app_version_id: 'workflow-app-version-v2',
        expected_snapshot_fingerprint: 'sha256:v2',
        state: 'staged',
        activated_at: null,
        created_at: '2026-08-19T02:00:00+08:00',
      }
      revisions = [nextRevision, ...revisions]
      runtimeState = {
        ...runtimeState,
        desired_revision_id: nextRevision.workflow_runtime_revision_id,
        revision_generation: 2,
      }
      return fulfillJson(route, runtimeState)
    }
    if (path === '/workflows/app-runtimes' && request.method() === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>
      createRuntimeBodies.push(body)
      return fulfillJson(route, {
        ...runtimeState,
        workflow_runtime_id: 'runtime-created-from-v2',
        active_revision_id: null,
        desired_revision_id: 'workflow-runtime-revision-created',
        revision_generation: 1,
      })
    }
    if (path === '/workflows/app-runtimes/runtime-created-from-v2/revisions') {
      return fulfillJson(route, [{ ...revisions[0], workflow_runtime_id: 'runtime-created-from-v2' }])
    }
    if (path === '/workflows/app-runtimes/runtime-created-from-v2/revisions/workflow-runtime-revision-created') {
      return fulfillJson(route, {
        ...revisions[0],
        workflow_runtime_revision_id: 'workflow-runtime-revision-created',
        workflow_runtime_id: 'runtime-created-from-v2',
        workflow_app_version_id: 'workflow-app-version-v2',
      })
    }
    await route.fulfill({
      status: 404,
      headers: responseHeaders(),
      body: JSON.stringify({ error: { code: 'e2e_mock_missing', message: path } }),
    })
  })

  await page.goto('/workflows/apps/app-e2e')

  await expect(page.getByRole('heading', { level: 2, name: '版本记录' })).toBeVisible()
  await expect(page.getByText('v2', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('generation 1', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '切换版本', exact: true }).click()
  const versionDialog = page.getByRole('dialog', { name: '切换版本' })
  await expect(versionDialog.getByText('v1', { exact: true }).first()).toBeVisible()
  await versionDialog.locator('.ui-select__button').click()
  await versionDialog.getByRole('option', { name: /v2 \(#2\)/ }).click()
  await versionDialog.getByRole('button', { name: '切换版本', exact: true }).click()
  await expect.poll(() => selectVersionBodies.length).toBe(1)
  expect(selectVersionBodies[0]).toEqual({
    workflow_app_version_id: 'workflow-app-version-v2',
    expected_generation: 1,
    allow_breaking_contract: false,
    breaking_change_reason: null,
  })
  await expect(page.getByText('generation 2', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '创建 runtime' }).click()
  const createDialog = page.getByRole('dialog', { name: '创建 runtime' })
  await expect(createDialog.locator('.ui-select__value')).toHaveText(['v2 (#2)', 'none', '否'])
  await createDialog.getByRole('button', { name: '创建 runtime', exact: true }).click()
  await expect.poll(() => createRuntimeBodies.length).toBe(1)
  expect(createRuntimeBodies[0]).toMatchObject({
    project_id: 'project-1',
    application_id: null,
    workflow_app_version_id: 'workflow-app-version-v2',
    metadata: {
      default_execution_metadata: {
        workflow_run_record_mode: 'none',
        return_timing_metadata_enabled: false,
        return_node_timings_enabled: false,
      },
    },
  })
})
