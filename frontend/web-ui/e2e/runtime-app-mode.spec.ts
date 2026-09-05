import { expect, test } from 'playwright/test'
import type { Page } from 'playwright/test'
import { resolve } from 'node:path'

const runtimeId = process.env.AMVISION_RUNTIME_APP_MODE_ID
test.skip(!runtimeId, 'Requires an explicitly selected development App Mode Runtime')

const localeExpectations = [
  { locale: 'zh-CN', inputs: '输入', monitor: '运行时监视', labels: ['图像', 'Base64 图像', 'JSON', '文本', '文件', '多个文件'], displays: ['图像预览', '值预览'] },
  { locale: 'en-US', inputs: 'Inputs', monitor: 'Runtime monitor', labels: ['Image', 'Base64 image', 'JSON', 'Text', 'File', 'Files'], displays: ['Image preview', 'Value preview'] },
  { locale: 'ja-JP', inputs: '入力', monitor: 'ランタイム監視', labels: ['画像', 'Base64 画像', 'JSON', 'テキスト', 'ファイル', '複数ファイル'], displays: ['画像プレビュー', '値プレビュー'] },
  { locale: 'ko-KR', inputs: '입력', monitor: '런타임 모니터링', labels: ['이미지', 'Base64 이미지', 'JSON', '텍스트', '파일', '여러 파일'], displays: ['이미지 미리보기', '값 미리보기'] },
] as const

async function selectLocale(page: Page, locale: string): Promise<void> {
  await page.evaluate((value: string) => localStorage.setItem('amvision.web-ui.locale', value), locale)
  await page.reload()
}

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
  for (const expectation of localeExpectations) {
    await selectLocale(page, expectation.locale)
    await expect(page.locator('.app-mode-inputs')).toHaveAttribute('aria-label', expectation.inputs, { timeout: 30_000 })
    await expect(page.getByText(expectation.inputs, { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: expectation.monitor, exact: true })).toBeVisible()
    await expect(page.locator('.app-mode-inputs__label strong')).toHaveText([...expectation.labels])
    await expect(page.locator('.app-mode-displays__slot > header strong')).toHaveText([...expectation.displays])
    await expect(page.getByText('body', { exact: true })).toHaveCount(0)
  }
  await selectLocale(page, 'zh-CN')
  await expect(page.locator('.app-mode-inputs')).toHaveAttribute('aria-label', '输入', { timeout: 30_000 })
  await expect(page.getByText('输入', { exact: true })).toHaveCount(0)
  await expect(page.locator('.app-mode-inputs__label strong')).toHaveText([
    '图像',
    'Base64 图像',
    'JSON',
    '文本',
    '文件',
    '多个文件',
  ])
  for (const bindingId of ['request_image_ref', 'request_image_base64', 'request_json', 'request_text', 'request_file', 'request_files']) {
    await expect(page.getByText(bindingId, { exact: true })).toHaveCount(0)
  }
  await expect(page.getByText(runtimeId!, { exact: true })).toHaveCount(0)
  await expect(page.getByText('空输入不会发送', { exact: true })).toHaveCount(0)
  await expect(page.getByText('等待下次执行', { exact: true })).toHaveCount(0)
  for (const payloadType of ['image-ref.v1', 'image-base64.v1', 'value.v1', 'text.v1', 'file-ref.v1', 'file-refs.v1']) {
    await expect(page.getByText(payloadType, { exact: true })).toHaveCount(0)
  }
  expect(invokeUrls).toEqual([])

  const imagePath = resolve('../../sdks/dotnet/apps/AMVision.Console/Resources/Img/Image_20260721103308382.bmp')
  const imageReferenceField = page.locator('.app-mode-inputs__field').first()
  await imageReferenceField.locator('input[type="file"]').setInputFiles(imagePath)
  await expect(imageReferenceField.getByText('点击选择或拖拽文件到这里', { exact: true })).toHaveCount(0)
  await expect(imageReferenceField.locator('.file-picker__file-name')).toHaveText('Image_20260721103308382.bmp')
  expect(await imageReferenceField.locator('.file-picker__dropzone').evaluate((dropzone) => {
    const elements = [dropzone, ...dropzone.querySelectorAll('.file-picker__content, .file-picker__files, .file-picker__files li')]
    return elements.every((element) => element.scrollWidth <= element.clientWidth + 1)
  })).toBe(true)
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

  await expect(page.locator('.runtime-app-mode__result')).toContainText('运行结果', { timeout: 30_000 })
  await expect(page.locator('.runtime-app-mode__result')).toContainText('已完成')
  await expect(page.locator('.runtime-app-mode__result time')).toHaveText(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)
  await expect(page.getByText(run.workflow_run_id, { exact: true })).toHaveCount(0)
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
  for (const theme of ['light', 'dark']) {
    await page.evaluate((nextTheme) => {
      document.documentElement.dataset.theme = nextTheme
      document.documentElement.style.colorScheme = nextTheme
    }, theme)
    await expect(page.locator('.runtime-app-mode')).toHaveCSS(
      'background-color',
      theme === 'light' ? 'rgb(246, 247, 249)' : 'rgb(16, 16, 16)',
    )
    await expect(page.locator('.app-mode-inputs')).toHaveCSS(
      'background-color',
      theme === 'light' ? 'rgb(255, 255, 255)' : 'rgb(23, 25, 24)',
    )
    if (screenshotDir) {
      await page.screenshot({ path: resolve(screenshotDir, `runtime-app-mode-desktop-${theme}.png`), fullPage: true })
    }
  }

  if (screenshotDir) {
    await page.setViewportSize({ width: 900, height: 1000 })
    expect(await page.locator('.runtime-app-mode__body').evaluate((element) => (
      getComputedStyle(element).gridTemplateColumns.split(' ').length
    ))).toBe(1)
    await page.screenshot({ path: resolve(screenshotDir, 'runtime-app-mode-compact-dark.png'), fullPage: true })
  }

  await page.getByRole('button', { name: '应用详情', exact: true }).click()
  await expect(page).toHaveURL(/\/workflows\/apps\/workflow-app-/)
  await expect(page.getByRole('button', { name: '运行时监视', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '应用模式', exact: true })).toBeVisible()
})
