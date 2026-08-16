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
