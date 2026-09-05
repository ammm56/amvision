import { test, expect } from 'playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const runtimeId = process.env.AMVISION_RUNTIME_PREVIEW_ID
const appId = process.env.AMVISION_RUNTIME_PREVIEW_APP_ID
test.skip(!runtimeId || !appId, 'Requires an explicitly selected development validation Runtime')

test('published readonly graph displays actual Runtime image and JSON without executing on navigation', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  const config = JSON.parse(readFileSync(resolve('../../sdks/dotnet/src/Amvar.Vision/Config/config_workflow-app-20260831130620.json'), 'utf8').replace(/^\uFEFF/, ''))
  const section = Object.values(config).find((value) => value && typeof value === 'object' && 'access_token' in value) as { access_token: string }
  const headers = { Authorization: `Bearer ${section.access_token}` }
  const invocations: string[] = []
  const nodeCatalogRequests: string[] = []
  page.on('request', (request) => { if (/\/(invoke|runs|preview-runs)(\?|$)/.test(request.url()) && request.method() === 'POST') invocations.push(request.url()) })
  page.on('request', (request) => { if (request.url().includes('/workflows/node-catalog')) nodeCatalogRequests.push(request.url()) })
  await page.goto(`/workflows/apps/${appId}`)
  await page.getByRole('button', { name: 'Runtime 监视', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/workflows/runtime/${runtimeId}/monitor$`))
  await expect(page.getByRole('status')).toHaveText('等待下次执行')
  await expect(page.locator('[data-node-id="image_preview"] header strong')).toHaveText('Image Preview', { timeout: 15000 })
  await expect(page.locator('[data-node-id="image_preview"] .runtime-canvas__ports')).toContainText('image')
  await expect(page.locator('[data-node-id="app-entry-boundary"]')).toContainText('request_json')
  expect(nodeCatalogRequests.some((url) => new URL(url).searchParams.get('resolve_parameter_ui') === 'false')).toBe(true)
  expect(invocations).toEqual([])
  expect(await page.locator('vite-error-overlay').count()).toBe(0)
  const invoke = async (sequence: number) => {
    const response = await page.request.post(`http://127.0.0.1:5600/api/v1/workflows/app-runtimes/${runtimeId}/invoke?response_mode=run`, {
      headers, data: { input_bindings: { request_json: { value: { sequence, flag: false, zero: 0, text: 'Runtime 真实结果' } } }, execution_metadata: { workflow_run_record_mode: 'none' } },
    })
    expect(response.ok()).toBe(true)
    const result = await response.json()
    expect(result.state).toBe('succeeded')
    await expect(page.getByText(result.workflow_run_id, { exact: true })).toBeVisible()
    await expect(page.getByRole('status')).toHaveText('已显示执行结果')
  }
  await invoke(1)
  const json = page.locator('[data-node-id="json_preview"] .workflow-graph-node-preview__json')
  await expect(json).toContainText('"sequence": 1')
  const image = page.locator('[data-node-id="image_preview"] .workflow-graph-node-preview img')
  await expect(image).toBeVisible()
  await expect.poll(() => image.evaluate((element) => (element as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  expect(await page.locator('.runtime-canvas input,.runtime-canvas select,.runtime-canvas textarea').count()).toBe(0)
  const screenshotDir = process.env.AMVISION_QA_SCREENSHOT_DIR
  if (screenshotDir) await page.screenshot({ path: resolve(screenshotDir, 'runtime-preview-desktop.png') })
  await image.dblclick()
  await expect(page.locator('.image-viewer[role="dialog"]')).toBeVisible()
  expect(await page.locator('.image-viewer__interaction-actions').count()).toBe(0)
  await page.locator('.image-viewer__close').click()
  await invoke(2)
  await expect(json).toContainText('"sequence": 2')
  await expect(json).not.toContainText('"sequence": 1')
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('等待下次执行')
  expect(await page.locator('.workflow-graph-node-preview').count()).toBe(0)
  expect(invocations).toEqual([])
  await invoke(3)
  const runtimeApi = `http://127.0.0.1:5600/api/v1/workflows/app-runtimes/${runtimeId}`
  const beforeRestart = await (await page.request.get(`${runtimeApi}/preview-snapshot`, { headers })).json()
  let runtimeStarted = false
  try {
    const stopResponse = await page.request.post(`${runtimeApi}/stop`, { headers })
    expect(stopResponse.ok()).toBe(true)
    await expect(page.getByRole('status')).toHaveText(/已断开|Runtime 未运行/, { timeout: 30_000 })
    const startResponse = await page.request.post(`${runtimeApi}/start`, { headers })
    expect(startResponse.ok()).toBe(true)
    runtimeStarted = true
    await expect.poll(async () => {
      const response = await page.request.get(`${runtimeApi}/preview-snapshot`, { headers })
      const current = await response.json()
      return current.observed_state === 'running'
        && current.worker_instance_id !== beforeRestart.worker_instance_id
    }, { timeout: 60_000 }).toBe(true)
    await expect(page.getByRole('status')).toHaveText('等待下次执行', { timeout: 30_000 })
    await invoke(4)
    if (screenshotDir) await page.screenshot({ path: resolve(screenshotDir, 'runtime-preview-reconnected.png') })
  } finally {
    if (!runtimeStarted) await page.request.post(`${runtimeApi}/start`, { headers })
  }
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Performance.enable')
  const sample = async () => {
    await cdp.send('HeapProfiler.collectGarbage')
    const metrics = await cdp.send('Performance.getMetrics')
    return {
      heapBytes: metrics.metrics.find((metric) => metric.name === 'JSHeapUsedSize')!.value,
      dom: await cdp.send('Memory.getDOMCounters'),
    }
  }
  const samples = []
  for (let iteration = 0; iteration < 30; iteration++) {
    await invoke(10 + iteration)
    if (iteration === 4 || iteration === 14 || iteration === 29) samples.push(await sample())
  }
  // 仅是当前图片与 JSON 的浏览器短测，不替代现场长期认证。
  expect(samples[2]!.heapBytes - samples[0]!.heapBytes).toBeLessThan(12 * 1024 * 1024)
  expect(samples[2]!.dom.nodes - samples[0]!.dom.nodes).toBeLessThan(100)
  console.log('Runtime preview renderer samples', JSON.stringify(samples))
  await cdp.detach()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(async () => (await page.locator('.app-sidebar').boundingBox())?.width).toBeLessThan(70)
  await expect(page.getByRole('button', { name: '刷新', exact: true })).toBeVisible()
  if (screenshotDir) await page.screenshot({ path: resolve(screenshotDir, 'runtime-preview-mobile.png') })
  expect(errors).toEqual([])
})
