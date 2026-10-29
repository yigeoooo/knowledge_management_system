import { expect, test } from '@playwright/test'

test('home navigation underline follows the section in view', async ({ page }) => {
  await page.goto('/')
  const capabilities = page.getByRole('link', { name: '平台能力', exact: true }).first()
  const workflow = page.getByRole('link', { name: '工作流程', exact: true }).first()
  const scenarios = page.getByRole('link', { name: '应用场景', exact: true }).first()
  const home = page.getByRole('link', { name: '首页', exact: true })

  await expect(home).toHaveClass(/(?:^|\s)active(?:\s|$)/)
  await capabilities.click()
  await expect(capabilities).toHaveClass(/(?:^|\s)active(?:\s|$)/)
  await page.waitForTimeout(120)
  await expect(capabilities).toHaveClass(/(?:^|\s)active(?:\s|$)/)
  await expect(home).not.toHaveClass(/(?:^|\s)active(?:\s|$)/)
  await workflow.click()
  await expect(workflow).toHaveClass(/(?:^|\s)active(?:\s|$)/)
  await page.waitForTimeout(120)
  await expect(workflow).toHaveClass(/(?:^|\s)active(?:\s|$)/)
  await expect(capabilities).not.toHaveClass(/(?:^|\s)active(?:\s|$)/)
  await scenarios.click()
  await expect(scenarios).toHaveClass(/(?:^|\s)active(?:\s|$)/)
  await expect(workflow).not.toHaveClass(/(?:^|\s)active(?:\s|$)/)

  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'auto' }))
  await expect(home).toHaveClass(/(?:^|\s)active(?:\s|$)/)
})

test('document download uses the selected version id', async ({ page }) => {
  const baseId = '00000000-0000-4000-8000-000000000001'
  const documentId = '00000000-0000-4000-8000-000000000002'
  const versionId = '00000000-0000-4000-8000-000000000003'
  const version = {
    id: versionId,
    document_id: documentId,
    version_no: 1,
    filename: 'guide.pdf',
    content_type: 'application/pdf',
    file_size: 128,
    status: 'INDEXED',
    chunk_count: 0,
    error_message: null,
    created_at: '2026-10-23T00:00:00Z',
    task: null,
  }
  const detail = {
    id: documentId,
    knowledge_base_id: baseId,
    title: '使用指南',
    status: 'active',
    current_version_id: versionId,
    updated_at: '2026-10-23T00:00:00Z',
    versions: [version],
  }
  const downloadUrls: URL[] = []
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    let data: unknown
    if (url.pathname === '/api/v1/auth/refresh') {
      data = {
        access_token: 'test-token',
        user: { id: 'admin', username: 'admin', display_name: 'Admin', role: 'super_admin' },
        pages: [{
          code: 'documents', name: '文档管理', route_path: '/documents', route_name: 'DocumentManagement',
          component_key: 'DocumentManagement', page_type: 'menu', sort_order: 1, is_visible: true,
        }],
      }
    } else if (url.pathname === '/api/v1/knowledge-bases') {
      data = { items: [{ id: baseId, name: '通用知识库', code: 'general', status: 'active' }] }
    } else if (url.pathname === `/api/v1/knowledge-bases/${baseId}/documents`) {
      data = { items: [{ ...detail, current_version: version }], total: 1, page: 1, page_size: 20 }
    } else if (url.pathname === `/api/v1/documents/${documentId}`) {
      data = detail
    } else if (url.pathname === `/api/v1/documents/${documentId}/preview-url`) {
      data = { preview_url: 'https://storage.test/preview' }
    } else if (url.pathname === `/api/v1/documents/${documentId}/download-url`) {
      downloadUrls.push(url)
      data = { download_url: 'https://storage.test/download', version }
    } else {
      throw new Error(`Unexpected API request: ${url.pathname}`)
    }
    await route.fulfill({ json: { code: 0, message: 'ok', data } })
  })

  await page.goto('/documents')
  await page.getByRole('button', { name: '预览', exact: true }).click()
  await expect(page.getByRole('heading', { name: '使用指南' })).toBeVisible()
  await page.getByRole('button', { name: '下载', exact: true }).first().click()
  await expect.poll(() => downloadUrls.at(-1)?.searchParams.get('version_id')).toBe(versionId)
  expect(downloadUrls.at(-1)?.searchParams.get('version_id')).not.toBe('undefined')

  await page.getByRole('button', { name: '下载', exact: true }).last().click()
  await expect.poll(() => downloadUrls.length).toBe(2)
  expect(downloadUrls.at(-1)?.searchParams.get('version_id')).toBe(versionId)
})

test('DOCX detail preview renders returned rich HTML instead of plain text', async ({ page }) => {
  const baseId = '00000000-0000-4000-8000-000000000101'
  const documentId = '00000000-0000-4000-8000-000000000102'
  const versionId = '00000000-0000-4000-8000-000000000103'
  const version = {
    id: versionId, document_id: documentId, version_no: 1, filename: 'formatted.docx',
    content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    file_size: 256, status: 'INDEXED', chunk_count: 2, error_message: null,
    created_at: '2026-10-23T00:00:00Z', task: null,
  }
  const detail = {
    id: documentId, knowledge_base_id: baseId, title: '格式文档', status: 'active',
    current_version_id: versionId, updated_at: '2026-10-23T00:00:00Z', versions: [version],
  }
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    let data: unknown
    if (url.pathname === '/api/v1/auth/refresh') {
      data = { access_token: 'test-token', user: { id: 'admin', display_name: 'Admin', role: 'super_admin' }, pages: [{ code: 'documents', name: '文档管理', route_path: '/documents', route_name: 'DocumentManagement', component_key: 'DocumentManagement', page_type: 'menu', sort_order: 1, is_visible: true }] }
    } else if (url.pathname === '/api/v1/knowledge-bases') {
      data = { items: [{ id: baseId, name: '格式知识库', code: 'formatted', status: 'active' }] }
    } else if (url.pathname === `/api/v1/knowledge-bases/${baseId}/documents`) {
      data = { items: [{ ...detail, current_version: version }], total: 1, page: 1, page_size: 20 }
    } else if (url.pathname === `/api/v1/documents/${documentId}`) {
      data = detail
    } else if (url.pathname === `/api/v1/documents/${documentId}/text-preview`) {
      data = { document: detail, version, content: '标题\n\n正文', html: '<h1>标题</h1><p><strong>加粗正文</strong></p><table class="docx-preview-table"><tbody><tr><td>表格</td></tr></tbody></table>' }
    } else {
      throw new Error(`Unexpected API request: ${url.pathname}`)
    }
    await route.fulfill({ json: { code: 0, message: 'ok', data } })
  })
  await page.goto('/documents')
  await page.getByRole('button', { name: '预览', exact: true }).click()
  await expect(page.getByRole('heading', { name: '格式文档' })).toBeVisible()
  await expect(page.locator('.document-preview h1')).toHaveText('标题')
  await expect(page.locator('.document-preview strong')).toHaveText('加粗正文')
  await expect(page.locator('.document-preview .docx-preview-table')).toBeVisible()
})

test('robot management supports create, detail, edit, and disable', async ({ page }) => {
  const robotId = '00000000-0000-4000-8000-000000000010'
  let robot = {
    id: robotId,
    serial_no: 'ROBOT-001',
    name: '一号机器人',
    description: '初始设备',
    status: 'active',
    last_request_at: null,
    created_by: 'admin',
    created_at: '2026-10-23T00:00:00Z',
    updated_at: '2026-10-23T00:00:00Z',
  }
  let created = false
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    let data: unknown
    if (url.pathname === '/api/v1/auth/refresh') {
      data = {
        access_token: 'test-token',
        user: { id: 'admin', username: 'admin', display_name: 'Admin', role: 'super_admin' },
        pages: [{
          code: 'robots', name: '机器人管理', route_path: '/robots', route_name: 'RobotManagement',
          component_key: 'RobotManagement', page_type: 'menu', sort_order: 1, is_visible: true,
        }],
      }
    } else if (url.pathname === '/api/v1/robots' && request.method() === 'GET') {
      const status = url.searchParams.get('status')
      const q = (url.searchParams.get('q') || '').toLowerCase()
      const items = created && (!status || robot.status === status) &&
        (!q || `${robot.serial_no} ${robot.name}`.toLowerCase().includes(q)) ? [robot] : []
      data = { items, total: items.length, page: 1, page_size: 20 }
    } else if (url.pathname === `/api/v1/robots/${robotId}` && request.method() === 'GET') {
      data = robot
    } else if (url.pathname === '/api/v1/robots' && request.method() === 'POST') {
      const body = request.postDataJSON()
      robot = { ...robot, ...body }
      created = true
      data = robot
    } else if (url.pathname === `/api/v1/robots/${robotId}` && request.method() === 'PUT') {
      robot = { ...robot, ...request.postDataJSON() }
      data = robot
    } else if (url.pathname === `/api/v1/robots/${robotId}` && request.method() === 'DELETE') {
      robot = { ...robot, status: 'disabled' }
      data = { id: robotId, status: robot.status }
    } else {
      throw new Error(`Unexpected API request: ${request.method()} ${url.pathname}`)
    }
    await route.fulfill({ json: { code: 0, message: 'ok', data } })
  })

  await page.goto('/robots')
  await expect(page.getByText('暂无机器人，请先注册一台设备')).toBeVisible()
  await page.getByRole('button', { name: '注册机器人', exact: true }).click()
  await page.getByPlaceholder('例如：ROBOT-001').fill('ROBOT-001')
  await page.getByPlaceholder('例如：一号巡检机器人').fill('一号机器人')
  await page.getByPlaceholder('说明设备用途或所在场景').fill('初始设备')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('一号机器人')).toBeVisible()

  await page.getByRole('button', { name: '详情', exact: true }).click()
  await expect(page.locator('.robot-detail-dialog').getByText('ROBOT-001', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('.robot-detail-dialog')).toBeHidden()

  await page.getByRole('button', { name: '编辑', exact: true }).click()
  const nameInput = page.getByPlaceholder('例如：一号巡检机器人')
  await expect(nameInput).toBeEnabled()
  await nameInput.fill('更新后的机器人')
  await expect(page.locator('.el-dialog').getByRole('button', { name: '保存', exact: true })).toBeEnabled()
  const updateRequest = page.waitForRequest(request => request.method() === 'PUT' && request.url().endsWith(`/api/v1/robots/${robotId}`))
  await page.locator('.el-dialog').getByRole('button', { name: '保存', exact: true }).click()
  await updateRequest
  await expect(page.getByText('更新后的机器人')).toBeVisible()

  await page.getByRole('button', { name: '停用', exact: true }).click()
  await page.getByRole('button', { name: '确认停用', exact: true }).click()
  await expect(page.locator('.el-table__body-wrapper .el-tag', { hasText: '停用' })).toBeVisible()
})
