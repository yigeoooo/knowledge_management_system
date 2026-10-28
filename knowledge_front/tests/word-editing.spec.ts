import { expect, test } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { resolve } from 'node:path'

let server: ChildProcess
let origin: string

test.beforeAll(async () => {
  server = spawn(resolve('../knowledge_back/.venv/bin/python'), ['tests/word_browser_server.py'], {
    cwd: resolve('../knowledge_back'), env: { ...process.env, PYTHONPATH: '.' }, stdio: ['ignore', 'pipe', 'pipe'],
  })
  origin = await new Promise<string>((resolve, reject) => {
    let output = '', errors = ''
    const timer = setTimeout(() => reject(new Error(`Word test API did not start: ${errors}`)), 15000)
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

test('uploaded DOCX can be edited, retried, previewed, downloaded and reopened with formatting', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  const login = await request.post(`${origin}/api/v1/auth/login`, { data: { username: 'admin', password: 'Test-Password-2026!' } })
  const identity = await login.json()
  const attempts: string[] = []
  let failSave = true
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), url = new URL(req.url())
    if (url.pathname.endsWith('/auth/refresh')) {
      await route.fulfill({ json: identity }); return
    }
    if (url.pathname.endsWith('/word-content') && req.method() === 'POST') {
      attempts.push(req.postDataJSON().request_id)
      if (failSave) { failSave = false; await route.fulfill({ status: 503, json: { code: 50301, message: '测试存储暂不可用' } }); return }
    }
    const response = await route.fetch({ url: `${origin}${url.pathname}${url.search}` })
    await route.fulfill({ response })
  })
  await page.goto('/documents')
  await expect(page.getByRole('heading', { name: '文档管理', exact: true })).toBeVisible()
  expect(errors).toEqual([])
  await page.getByRole('button', { name: '上传文件', exact: true }).click()
  const original = await (await request.get(`${origin}/fixture/external.docx`)).body()
  await page.locator('input[type=file]').first().setInputFiles({ name: '格式维护.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: original })
  await page.getByRole('button', { name: '开始上传', exact: true }).click()
  await expect(page.getByRole('button', { name: '预览', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '预览', exact: true }).click()
  await page.getByRole('button', { name: '在线编辑', exact: true }).click()
  const editor = page.getByRole('textbox', { name: 'Word 文档正文' })
  await expect(editor).toContainText('红色加粗斜体')
  const p = editor.locator('p').filter({ hasText: '红色加粗斜体' })
  await expect(p).toHaveCSS('text-align', 'center')
  await expect(p.locator('span').first()).toHaveCSS('color', 'rgb(255, 0, 0)')
  await expect(editor.locator('td[rowspan="2"]')).toBeVisible()
  await p.click()
  await page.keyboard.press('End')
  await page.keyboard.insertText('在线修改')
  const save = page.getByRole('button', { name: '保存为新版本', exact: true })
  await save.click()
  await expect(page.getByText('测试存储暂不可用', { exact: true })).toBeVisible()
  await expect(editor).toContainText('在线修改')
  const savedResponse = page.waitForResponse(r => r.url().endsWith('/word-content') && r.request().method() === 'POST')
  await save.click()
  const savedBody = await (await savedResponse).json()
  expect(savedBody.code, savedBody.message).toBe(0)
  expect(errors).toEqual([])
  await expect(page.locator('.document-preview')).toContainText('在线修改')
  expect(attempts).toHaveLength(2)
  expect(attempts[0]).toBe(attempts[1])
  const downloadResponse = page.waitForResponse(r => r.url().includes('/download-url'))
  await page.getByRole('button', { name: '下载', exact: true }).first().click()
  const download = (await (await downloadResponse).json()).data.download_url
  const bytes = await (await request.get(download)).body()
  const inspected = await (await request.post(`${origin}/fixture/inspect`, { data: bytes, headers: { 'Content-Type': 'application/octet-stream' } })).json()
  expect(inspected.text).toContain('在线修改')
  expect(inspected).toMatchObject({ bold: true, italic: true, color: 'FF0000', tables: 1, header: '保留原文件页眉' })
  const originalResponse = page.waitForResponse(r => r.url().includes('/download-url'))
  await page.getByRole('button', { name: '下载', exact: true }).last().click()
  const originalUrl = (await (await originalResponse).json()).data.download_url
  expect(await (await request.get(originalUrl)).body()).toEqual(original)
  await page.getByRole('button', { name: '在线编辑', exact: true }).click()
  await expect(editor).toContainText('在线修改')
  await editor.press('ControlOrMeta+End')
  await page.keyboard.insertText('未保存')
  await page.getByRole('button', { name: '取消编辑', exact: true }).click()
  await page.getByRole('button', { name: '继续编辑', exact: true }).click()
  await expect(editor).toContainText('未保存')
  await page.getByRole('button', { name: '取消编辑', exact: true }).click()
  await page.getByRole('button', { name: '放弃修改', exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect(errors).toEqual([])
})

test('a Word created inside the system can be reopened and saved from document management', async ({ page, request }) => {
  const login = await request.post(`${origin}/api/v1/auth/login`, { data: { username: 'admin', password: 'Test-Password-2026!' } })
  const identity = await login.json()
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/auth/refresh')) { await route.fulfill({ json: identity }); return }
    await route.fulfill({ response: await route.fetch({ url: `${origin}${url.pathname}${url.search}` }) })
  })
  await page.goto('/create-document')
  await page.getByRole('textbox', { name: '文档标题', exact: true }).fill('系统创建再编辑')
  await page.getByRole('combobox', { name: '保存到知识库' }).click()
  await page.getByRole('option', { name: '通用知识库', exact: true }).click()
  await page.getByText('Word', { exact: true }).click()
  const editor = page.getByRole('textbox', { name: 'Word 文档正文' })
  await editor.fill('待维护正文')
  await editor.press('ControlOrMeta+a')
  await page.locator('.umo-toolbar button:has(use[*|href="#umo-icon-bold"])').click()
  await page.getByRole('button', { name: '保存到知识库', exact: true }).click()
  await expect(page.getByText('系统创建再编辑.docx 已保存，可用于知识问答')).toBeVisible()
  await page.goto('/documents')
  await page.getByRole('row').filter({ hasText: '系统创建再编辑' }).getByRole('button', { name: '预览', exact: true }).click()
  await page.getByRole('button', { name: '在线编辑', exact: true }).click()
  await expect(editor.locator('b')).toHaveText('待维护正文')
  await editor.press('ControlOrMeta+End')
  await page.keyboard.insertText('更新内容')
  await page.getByRole('button', { name: '保存为新版本', exact: true }).click()
  await expect(page.locator('.document-preview')).toContainText('更新内容')
  await expect(page.locator('.document-preview span').first()).toHaveCSS('font-weight', '700')
})
