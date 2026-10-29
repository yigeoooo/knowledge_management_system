import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { resolve } from 'node:path'

let server: ChildProcess
let origin: string

test.beforeAll(async () => {
  server = spawn(resolve('../knowledge_back/.venv/bin/python'), ['tests/excel_browser_server.py'], {
    cwd: resolve('../knowledge_back'), env: { ...process.env, PYTHONPATH: '.' }, stdio: ['ignore', 'pipe', 'pipe'],
  })
  origin = await new Promise<string>((resolve, reject) => {
    let output = '', errors = ''
    const timer = setTimeout(() => reject(new Error(`Excel test API did not start: ${errors}`)), 15000)
    server.stderr?.on('data', data => { errors += data })
    server.stdout?.on('data', data => {
      output += data
      for (const line of output.split('\n')) {
        if (line.startsWith('{"origin"')) { clearTimeout(timer); resolve(JSON.parse(line).origin) }
      }
    })
    server.once('exit', () => { clearTimeout(timer); reject(new Error(errors)) })
  })
})
test.afterAll(() => server?.kill())

async function connect(page: Page, request: APIRequestContext) {
  const login = await request.post(`${origin}/api/v1/auth/login`, { data: { username: 'admin', password: 'Test-Password-2026!' } })
  const identity = await login.json()
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/auth/refresh')) { await route.fulfill({ json: identity }); return }
    await route.fulfill({ response: await route.fetch({ url: `${origin}${url.pathname}${url.search}` }) })
  })
  return identity.data
}

async function selectFirstCell(page: Page, selector = '.excel-editor') {
  await expect.poll(async () => page.locator(`${selector} canvas`).evaluateAll(items => items.some(item => item.width > 500 && item.height > 100))).toBe(true)
  const box = await page.locator(`${selector} canvas`).last().boundingBox()
  expect(box).toBeTruthy()
  await page.mouse.click(box!.x + 56, box!.y + 30)
}

test('Excel pasted cells and toolbar styles save through the real API and reopen as XLSX', async ({ page, context, request }) => {
  await connect(page, request)
  await page.goto('/create-document')
  await page.getByRole('textbox', { name: '文档标题', exact: true }).fill('真实保存回归')
  await page.getByRole('combobox', { name: '保存到知识库' }).click()
  await page.getByRole('option', { name: '通用知识库', exact: true }).click()
  await page.getByText('Excel 表格', { exact: true }).click()
  await selectFirstCell(page)
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.evaluate(() => navigator.clipboard.writeText('部门\t1\t2\t合计\n开发部门\t123\t456\t=SUM(B2:C2)'))
  await page.keyboard.press('ControlOrMeta+v')
  await expect.poll(() => page.evaluate(() => Object.values(sessionStorage).join(''))).toContain('开发部门')
  await page.keyboard.press('ControlOrMeta+b')
  await page.keyboard.press('ControlOrMeta+u')
  const saving = page.waitForResponse(response => response.url().endsWith('/documents/create') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '保存到知识库', exact: true }).click()
  const saved = await saving
  expect(saved.status(), await saved.text()).toBe(201)
  const { data } = await saved.json()
  await expect(page.getByText('真实保存回归.xlsx 已保存，可用于知识问答')).toBeVisible()
  await page.goto('/documents')
  await page.getByRole('row').filter({ hasText: '真实保存回归' }).getByRole('button', { name: '预览', exact: true }).click()
  await expect.poll(async () => page.locator('.excel-preview canvas').evaluateAll(items => items.some(item => item.width > 500 && item.height > 100))).toBe(true)
  const previewResponse = page.waitForResponse(response => response.url().includes('/excel-content'))
  await page.getByRole('button', { name: '在线编辑', exact: true }).click()
  const workbook = (await (await previewResponse).json()).data.workbook
  const cells = Object.values(workbook.sheets[0].cells) as any[]
  expect(cells.some(cell => cell.value === '开发部门')).toBe(true)
  expect(cells.some(cell => cell.formula === '=SUM(B2:C2)')).toBe(true)
  expect(cells.some(cell => cell.style.font.bold && cell.style.font.underline === 'single')).toBe(true)
  expect(data.version.filename).toBe('真实保存回归.xlsx')
})

test('real XLSX upload, edit and download preserve Excel styles and original bytes', async ({ page, request }) => {
  await connect(page, request)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/documents')
  await page.getByRole('button', { name: '上传文件', exact: true }).click()
  const original = await (await request.get(`${origin}/fixture/styled.xlsx`)).body()
  await page.locator('input[type=file]').first().setInputFiles({ name: '格式回读.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: original })
  await page.getByRole('button', { name: '开始上传', exact: true }).click()
  await page.getByRole('row').filter({ hasText: '格式回读' }).getByRole('button', { name: '预览', exact: true }).click()
  await page.getByRole('button', { name: '在线编辑', exact: true }).click()
  await selectFirstCell(page, '.excel-edit-panel')
  await page.keyboard.insertText('修改名称')
  await page.keyboard.press('Enter')
  const saving = page.waitForResponse(response => response.url().endsWith('/excel-content') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '保存 Excel 新版本', exact: true }).click()
  const saved = await saving
  expect(saved.status(), await saved.text()).toBe(201)
  await expect(page.locator('.excel-preview')).toBeVisible()
  const downloadResponse = page.waitForResponse(response => response.url().includes('/download-url'))
  await page.locator('.document-actions').getByRole('button', { name: '下载', exact: true }).click()
  const url = (await (await downloadResponse).json()).data.download_url
  const bytes = await (await request.get(url)).body()
  const workbook = await (await request.post(`${origin}/fixture/inspect`, { data: bytes })).json()
  const sheet = workbook.sheets[0]
  expect(sheet.cells['0,0'].value).toBe('修改名称')
  expect(sheet.cells['0,3'].style).toMatchObject({
    font: { bold: true, underline: 'double', strike: true, color: 'FFFF0000' },
    fill: { type: 'solid', color: 'FFFFFF00' },
    alignment: { horizontal: 'center', vertical: 'center', wrap_text: true, text_rotation: 135 },
    border: { bottom: { style: 'thin', color: 'FF0000FF' } },
  })
  expect(sheet.cells['1,2'].formula).toBe('=SUM(B2, 40)')
  const originalResponse = page.waitForResponse(response => response.url().includes('/download-url'))
  await page.getByRole('button', { name: '下载', exact: true }).last().click()
  const originalUrl = (await (await originalResponse).json()).data.download_url
  expect(await (await request.get(originalUrl)).body()).toEqual(original)
  expect(errors).toEqual([])
})

test('existing Excel drafts with numeric style enums can still be saved', async ({ page, request }) => {
  const identity = await connect(page, request)
  const bases = await (await request.get(`${origin}/api/v1/knowledge-bases`, {
    headers: { Authorization: `Bearer ${identity.access_token}` },
  })).json()
  const draft = {
    format: 'xlsx', title: '恢复旧版草稿', selectedBase: bases.data.items[0].id,
    excelWorkbook: { sheets: [{ id: 'sheet1', name: 'Sheet1', row_count: 10, column_count: 10, cells: {
      '0,0': { value: '草稿内容', style: { alignment: { horizontal: 2, vertical: 2 }, font: { underline: 1 }, border: { bottom: { style: 1 } } } },
    } }] },
  }
  await page.addInitScript(({ key, draft }) => sessionStorage.setItem(key, JSON.stringify(draft)), {
    key: `kbs-document-draft:${identity.user.id}`, draft,
  })
  await page.goto('/create-document')
  await selectFirstCell(page)
  const saving = page.waitForResponse(response => response.url().endsWith('/documents/create'))
  await page.getByRole('button', { name: '保存到知识库', exact: true }).click()
  const response = await saving
  expect(response.status(), await response.text()).toBe(201)
  const payload = response.request().postDataJSON()
  expect(payload.content.sheets[0].cells['0,0'].style).toMatchObject({
    alignment: { horizontal: 'center', vertical: 'center' }, font: { underline: 'single' }, border: { bottom: { style: 'thin' } },
  })
})

test('uploading text renamed to XLSX explains how to save a real workbook', async ({ page, request }) => {
  await connect(page, request)
  await page.goto('/documents')
  await page.getByRole('button', { name: '上传文件', exact: true }).click()
  await page.locator('input[type=file]').first().setInputFiles({
    name: '文本收支表.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('部门\t月份\n开发部门\t100\n'),
  })
  await page.getByRole('button', { name: '开始上传', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '文件实际是文本文件' })).toContainText('另存为')
})
