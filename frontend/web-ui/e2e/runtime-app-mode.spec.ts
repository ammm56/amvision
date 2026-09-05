import { expect, test } from 'playwright/test'
import { resolve } from 'node:path'

const runtimeId = process.env.AMVISION_RUNTIME_APP_MODE_ID
test.skip(!runtimeId, 'Requires an explicitly selected development App Mode Runtime')

test('App Mode submits real public inputs and displays the matching Runtime result', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  const errors: string[] = []
  const invokeUrls: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/invoke')) {
      invokeUrls.push(request.url())
    }
  })

  await page.goto(`/workflows/runtime/${runtimeId}/app-mode`)
  await expect(page.getByRole('status').first()).toHaveText('等待下次执行', { timeout: 30_000 })
  await expect(page.locator('.app-mode-inputs__label strong')).toHaveText([
    'request_image_ref',
    'request_image_base64',
    'request_json',
    'request_text',
    'request_file',
    'request_files',
  ])
  expect(invokeUrls).toEqual([])

  const imagePath = resolve('../../sdks/dotnet/apps/AMVision.Console/Resources/Img/Image_20260721103308382.bmp')
  const imageReferenceField = page.locator('.app-mode-inputs__field').filter({
    has: page.getByText('request_image_ref', { exact: true }).first(),
  })
  await imageReferenceField.locator('input[type="file"]').setInputFiles(imagePath)
  await page.getByPlaceholder('输入 JSON 值').fill('{"barqrcode":"app-mode-e2e"}')

  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && response.url().includes(`/workflows/app-runtimes/${runtimeId}/invoke/upload`)
  ))
  await page.getByRole('button', { name: '运行', exact: true }).click()
  const response = await responsePromise
  expect(response.ok()).toBe(true)
  const run = await response.json() as { workflow_run_id: string; state: string }
  expect(run.state).toBe('succeeded')

  await expect(page.getByText(run.workflow_run_id, { exact: true }).first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('status').first()).toHaveText('已显示执行结果')
  await expect(page.locator('.runtime-app-mode__manual')).toContainText('succeeded')
  const image = page.locator('.app-mode-displays img').first()
  await expect(image).toBeVisible()
  await expect.poll(() => image.evaluate((element) => (element as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  await expect(page.locator('.app-mode-displays')).toContainText('"count": 24')
  expect(invokeUrls).toEqual([
    `http://127.0.0.1:5600/api/v1/workflows/app-runtimes/${runtimeId}/invoke/upload?response_mode=run`,
  ])
  expect(await page.locator('vite-error-overlay').count()).toBe(0)
  expect(errors).toEqual([])

  const screenshotDir = process.env.AMVISION_QA_SCREENSHOT_DIR
  if (screenshotDir) {
    await page.screenshot({ path: resolve(screenshotDir, 'runtime-app-mode-desktop.png'), fullPage: true })
  }
})
