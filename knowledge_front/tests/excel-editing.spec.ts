import { expect, test } from '@playwright/test'

const baseId = '00000000-0000-4000-8000-000000000001'
const pageIdentity = { code: 'document_create', name: '创建文档', route_path: '/create-document', route_name: 'DocumentCreate', component_key: 'DocumentCreate', page_type: 'menu', sort_order: 45, is_visible: true }

test('Excel creation mounts Univer and submits a workbook snapshot', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  let submission: any = null
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    let data: any
    if (url.pathname.endsWith('/auth/refresh')) {
      data = { access_token: 'test-token', user: { id: 'writer', display_name: 'Writer', role: 'writer', role_name: '编辑者' }, pages: [pageIdentity] }
    } else if (url.pathname.endsWith('/knowledge-bases')) {
      data = { items: [{ id: baseId, name: '设备知识库', status: 'active' }] }
    } else if (url.pathname.endsWith('/documents/create')) {
      submission = route.request().postDataJSON()
      data = { document: { id: submission.request_id, title: submission.title, knowledge_base_id: baseId }, version: { filename: `${submission.title}.xlsx`, status: 'INDEXED', error_message: null, task: { status: 'SUCCESS', error_message: null } } }
    } else if (url.pathname.includes('/documents/created/')) {
      data = submission
    } else {
      throw new Error(`Unexpected API: ${url.pathname}`)
    }
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/create-document')
  await page.getByRole('textbox', { name: '文档标题', exact: true }).fill('Excel 设备参数')
  await page.getByRole('combobox', { name: '保存到知识库' }).click()
  await page.getByRole('option', { name: '设备知识库', exact: true }).click()
  await page.getByText('Excel 表格', { exact: true }).click()
  await expect(page.locator('.excel-editor')).toBeVisible()
  await expect.poll(async () => page.locator('.excel-editor canvas').evaluateAll(items => items.some(item => item.width > 500 && item.height > 100))).toBe(true)
  const canvas = page.locator('.excel-editor canvas').last()
  const box = await canvas.boundingBox()
  expect(box).toBeTruthy()
  await page.mouse.click((box?.x || 0) + 100, (box?.y || 0) + 45)
  await page.keyboard.type('设备名称')
  await page.keyboard.press('Enter')
  await page.keyboard.type('=1+2')
  await page.keyboard.press('Enter')
  await page.keyboard.press('ControlOrMeta+b')
  await page.keyboard.insertText('加粗内容')
  await page.keyboard.press('Enter')
  const addSheet = page.locator('[data-u-comp="sheet-bar-append-button"]').first()
  await expect(addSheet).toBeVisible()
  await addSheet.click()
  await expect(page.locator('[data-u-comp="slide-tab-item"]')).toHaveCount(2)
  await expect(page.getByRole('button', { name: '保存到知识库', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '保存到知识库', exact: true }).click()
  await expect(page.getByText('Excel 设备参数.xlsx 已保存，可用于知识问答')).toBeVisible()
  expect(submission?.format).toBe('xlsx')
  expect(JSON.stringify(submission?.content)).toContain('设备名称')
  expect(JSON.stringify(submission?.content)).toContain('=1+2')
  expect(JSON.stringify(submission?.content)).toContain('加粗内容')
  expect(JSON.stringify(submission?.content)).toContain('"bold":true')
  expect(submission?.content?.sheets).toHaveLength(2)
  expect(errors).toEqual([])
})

test('Excel upload, preview, online edit, new-version save and download work end to end', async ({ page }) => {
  const baseId = '00000000-0000-4000-8000-000000000001'
  const documentId = '00000000-0000-4000-8000-000000000010'
  const firstVersionId = '00000000-0000-4000-8000-000000000011'
  const secondVersionId = '00000000-0000-4000-8000-000000000012'
  const pageIdentity = { code: 'documents', name: '文档管理', route_path: '/documents', route_name: 'DocumentManagement', component_key: 'DocumentManagement', page_type: 'menu', sort_order: 50, is_visible: true }
  const workbook = {
    sheets: [{ id: 'sheet1', name: 'Sheet1', row_count: 20, column_count: 10, cells: {
      '0,0': { value: '原始值', formula: null, style: { font: { bold: true } } },
    } }],
    active_sheet: 'sheet1',
  }
  let currentWorkbook = JSON.parse(JSON.stringify(workbook))
  let currentVersionId = firstVersionId
  let versionNo = 1
  let uploadedBody: any = null
  let editedBody: any = null
  const version = (id: string, no: number, status = 'INDEXED') => ({ id, version_no: no, filename: '上传参数.xlsx', content_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', file_size: 2048, status, chunk_count: 1, error_message: null, created_at: '2026-10-29T01:00:00Z', task: { id: `task-${no}`, status: 'SUCCESS', task_type: 'INDEX', error_message: null } })
  const row = () => ({ id: documentId, knowledge_base_id: baseId, title: '上传参数', status: 'active', current_version_id: currentVersionId, updated_at: '2026-10-29T01:00:00Z', created_by_name: '创建人', updated_by_name: versionNo > 1 ? '修改人' : '创建人', current_version: version(currentVersionId, versionNo) })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/test-upload/**', async route => {
    await route.fulfill({ status: 200, body: '' })
  })
  await page.route('**/test-download/**', async route => {
    await route.fulfill({ status: 200, body: Buffer.from('PK\x03\x04excel-test'), headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'Content-Disposition': 'attachment; filename="上传参数.xlsx"' } })
  })
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    let data: any
    if (path.endsWith('/auth/refresh')) {
      data = { access_token: 'test-token', user: { id: 'writer', display_name: 'Writer', role: 'writer', role_name: '编辑者' }, pages: [pageIdentity] }
    } else if (path.endsWith('/knowledge-bases')) {
      data = { items: [{ id: baseId, name: '设备知识库', code: 'devices', status: 'active' }] }
    } else if (path.includes(`/knowledge-bases/${baseId}/documents`)) {
      data = { items: [row()], total: 1, max_file_size: 200 * 1024 * 1024 }
    } else if (path.endsWith(`/documents/${documentId}/excel-content`) && request.method() === 'GET') {
      data = { version: version(currentVersionId, versionNo), workbook: currentWorkbook }
    } else if (path.endsWith(`/documents/${documentId}/excel-content`) && request.method() === 'POST') {
      editedBody = request.postDataJSON()
      currentWorkbook = editedBody.workbook
      currentVersionId = secondVersionId
      versionNo = 2
      data = { document: row(), version: version(secondVersionId, 2) }
    } else if (path.endsWith(`/documents/${documentId}`)) {
      data = { ...row(), versions: versionNo > 1 ? [version(secondVersionId, 2), version(firstVersionId, 1)] : [version(firstVersionId, 1)] }
    } else if (path.endsWith('/documents/presign-upload')) {
      uploadedBody = request.postDataJSON()
      data = { version: version(firstVersionId, 1, 'PENDING_UPLOAD'), document: row(), upload_url: `/test-upload/${firstVersionId}`, required_headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' } }
    } else if (path.endsWith('/documents/complete')) {
      data = { document: row(), version: version(firstVersionId, 1), task: { id: 'task-1', status: 'SUCCESS', task_type: 'INDEX', error_message: null } }
    } else if (path.endsWith(`/documents/${documentId}/download-url`)) {
      data = { download_url: `/test-download/${currentVersionId}.xlsx`, version: version(currentVersionId, versionNo) }
    } else {
      throw new Error(`Unexpected API: ${request.method()} ${path}`)
    }
    await route.fulfill({ json: { code: 0, data } })
  })

  await page.goto('/documents')
  await page.getByRole('button', { name: '上传文件', exact: true }).click()
  const xlsx = Buffer.from('PK\x03\x04minimal-xlsx')
  await page.locator('input[type=file]').first().setInputFiles({ name: '上传参数.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: xlsx })
  await page.getByRole('button', { name: '开始上传', exact: true }).click()
  await expect(page.getByText('文档已上传，等待索引任务处理')).toBeVisible()
  expect(uploadedBody).toMatchObject({ filename: '上传参数.xlsx', file_size: xlsx.length, content_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const documentRow = page.getByRole('row').filter({ hasText: '上传参数' })
  await expect(documentRow).toBeVisible()
  await documentRow.getByRole('button', { name: '预览', exact: true }).click()
  await expect(page.locator('.excel-preview .excel-editor')).toBeVisible()
  await expect.poll(async () => page.locator('.excel-preview .excel-editor canvas').evaluateAll(items => items.some(item => item.width > 500 && item.height > 100))).toBe(true)
  await page.getByRole('button', { name: '在线编辑', exact: true }).click()
  await expect.poll(async () => page.locator('.excel-edit-panel .excel-editor canvas').evaluateAll(items => items.some(item => item.width > 500 && item.height > 100))).toBe(true)
  await page.getByRole('button', { name: '取消编辑', exact: true }).click()
  await expect(page.locator('.excel-edit-panel')).toHaveCount(0)
  await page.getByRole('button', { name: '在线编辑', exact: true }).click()
  const editCanvas = page.locator('.excel-edit-panel .excel-editor canvas').last()
  await expect(editCanvas).toBeVisible()
  const editBox = await editCanvas.boundingBox()
  expect(editBox).toBeTruthy()
  await page.mouse.click((editBox?.x || 0) + 100, (editBox?.y || 0) + 45)
  await page.keyboard.type('在线修改')
  await page.keyboard.press('Enter')
  const saveResponse = page.waitForResponse(response => response.url().endsWith(`/documents/${documentId}/excel-content`) && response.request().method() === 'POST')
  await page.getByRole('button', { name: '保存 Excel 新版本', exact: true }).click()
  await saveResponse
  await expect(page.getByText('新版本已提交，等待索引完成')).toBeVisible()
  expect(editedBody?.base_version_id).toBe(firstVersionId)
  expect(JSON.stringify(editedBody?.workbook)).toContain('在线修改')
  await expect(page.locator('.document-meta')).toContainText('修改人')
  const downloadEvent = page.waitForEvent('download')
  await page.locator('.document-actions').getByRole('button', { name: '下载', exact: true }).click()
  const download = await downloadEvent
  expect(download.suggestedFilename()).toBe('上传参数.xlsx')
  expect(errors).toEqual([])
})
