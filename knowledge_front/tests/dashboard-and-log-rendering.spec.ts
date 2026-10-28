import { expect, test } from '@playwright/test'

const routePage = (path: string, name: string, component: string, extra = {}) => ({
  code: component, name, route_path: path, route_name: component, component_key: component,
  page_type: 'menu', sort_order: 1, is_visible: true, ...extra,
})
const dashboard = routePage('/dashboard', '工作台', 'Dashboard')
const profile = routePage('/profile', '个人信息', 'Profile')
const knowledgeBase = routePage('/knowledge-bases', '知识库管理', 'KnowledgeBaseManagement')
const qa = routePage('/qa', '知识问答', 'KnowledgeQA')
const logs = routePage('/qa-logs', '问答日志', 'QALogs')

for (const allowed of [[], [profile], [knowledgeBase, qa, profile]]) {
  test(`dashboard only offers authorized routes: ${allowed.map(item => item.route_path).join(', ')}`, async ({ page }) => {
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      let data: unknown
      if (path === '/api/v1/auth/refresh') {
        data = { access_token: 'test-token', user: { id: 'reader', display_name: 'Reader', role: 'user' },
          pages: [dashboard, ...allowed,
            routePage('/robots', '隐藏机器人', 'RobotManagement', { is_visible: false }),
            routePage('/unsupported', '未知页面', 'MissingComponent'),
            routePage('/button', '操作按钮', 'UserManagement', { page_type: 'button' }),
          ] }
      } else if (path === '/api/v1/dashboard') {
        data = { knowledge_base_count: 2, document_count: 8, robot_count: 3, user_count: 7 }
      } else {
        throw new Error(`Unexpected request: ${path}`)
      }
      await route.fulfill({ json: { code: 0, data } })
    })
    await page.goto('/dashboard')
    await expect(page.getByRole('heading', { name: '工作台' })).toBeVisible()
    await expect(page.locator('.quick-links button')).toHaveText(allowed.map(item => new RegExp(item.name)))
    await expect(page.locator('.metric-card')).toHaveCount(allowed.includes(knowledgeBase) ? 1 : 0)
    await expect(page.getByRole('button', { name: '前往知识问答' })).toHaveCount(allowed.includes(qa) ? 1 : 0)
    await expect(page.getByText('平台建设进度')).toHaveCount(0)
    await page.goto('/users')
    await expect(page).toHaveURL(/\/403$/)
  })
}

const answer = '# 操作步骤\n\n请先**检查电源**。[1]\n\n| 项目 | 结果 |\n| --- | --- |\n| 电源 | 正常 |\n\n```bash\necho ready\n```\n\n<img src=x onerror="window.renderingUnsafe = true">'
const source = {
  source_id: '1', chunk_id: 'chunk', document_id: 'document', version_id: 'version', version_no: 1,
  filename: 'guide.md', document_title: '操作手册', modality: 'text', score: 0.9,
  content: '## 使用说明\n\n- **检查电源**\n- 启动设备\n\n```bash\necho ready\n```',
}
const pdfSource = { ...source, source_id: '2', chunk_id: 'pdf-chunk', filename: 'guide.PDF',
  content: '接口说明\n\n1. 检查电源\n2. 启动设备\n\nx² < 10' }

test('QA log details render Markdown answers and sources safely', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const detail = { id: 'log', question: '如何启动？', answer, sources: [source, pdfSource], status: 'SUCCESS',
      source_type: 'WEB', created_at: '2026-10-27T00:00:00Z', request_id: 'test-request' }
    const data = path.endsWith('/auth/refresh')
      ? { access_token: 'test-token', user: { id: 'admin', display_name: 'Admin', role: 'super_admin' }, pages: [logs] }
      : path.endsWith('/qa-logs') ? { items: [detail], total: 1 } : detail
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/qa-logs')
  await page.getByRole('button', { name: '查看详情' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: '操作步骤' })).toBeVisible()
  await expect(dialog.locator('.qa-answer table')).toContainText('电源')
  await expect(dialog.locator('.qa-answer pre code')).toHaveText('echo ready\n')
  await expect(dialog.locator('.qa-source-content h2')).toHaveText('使用说明')
  await expect(dialog.locator('.qa-source-content li')).toHaveCount(2)
  await expect(dialog.locator('[onerror]')).toHaveCount(0)
  await expect(dialog.locator('.source-plain-text')).toHaveText(pdfSource.content)
  await expect(dialog.locator('.source-plain-text')).toHaveCSS('white-space', 'pre-wrap')
})

test('knowledge QA renders Markdown and preserves PDF citation text and line breaks', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path.endsWith('/auth/refresh')) {
      data = { access_token: 'test-token', user: { id: 'reader', display_name: 'Reader', role: 'user' }, pages: [qa] }
    } else if (path.endsWith('/knowledge-bases')) {
      data = { items: [{ id: 'base', name: '设备资料', status: 'active' }] }
    } else if (path.endsWith('/web/suggested-questions')) {
      data = { questions: [], status: 'empty' }
    } else if (path.endsWith('/web/query')) {
      data = { answer, sources: [source, pdfSource], answer_status: 'answered' }
    } else {
      throw new Error(`Unexpected request: ${path}`)
    }
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/qa')
  await page.getByRole('textbox', { name: '你的问题' }).fill('如何启动？')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.answer-body h1')).toHaveText('操作步骤')
  await expect(page.locator('.answer-body table')).toContainText('电源')
  await expect(page.locator('.source-markdown h2')).toHaveText('使用说明')
  await expect(page.locator('.source-plain-text')).toHaveText(pdfSource.content)
  await expect(page.locator('.source-plain-text')).toHaveCSS('white-space', 'pre-wrap')
  await expect(page.locator('[onerror]')).toHaveCount(0)
})

test('audit log shows the operator name instead of their ID', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const data = path.endsWith('/auth/refresh')
      ? { access_token: 'test-token', user: { id: 'admin', display_name: 'Admin', role: 'super_admin' },
          pages: [routePage('/audit-logs', '审计日志', 'AuditLogs')] }
      : { items: [{ id: 'audit', action: 'user.update', resource_type: 'user', user_id: 'internal-user-uuid',
          user_name: '张三', ip_address: '127.0.0.1', created_at: '2026-10-27T00:00:00Z' }], total: 1 }
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/audit-logs')
  await expect(page.getByRole('columnheader', { name: '操作人', exact: true })).toBeVisible()
  await expect(page.locator('.el-table__body-wrapper')).toContainText('张三')
  await expect(page.locator('.el-table__body-wrapper')).not.toContainText('internal-user-uuid')
})

for (const path of ['/qa', '/qa-logs']) {
  test(`${path} preserves Word citation styles, lists and tables safely`, async ({ page }) => {
    const word = { ...source, filename: 'guide.docx', content: '红色斜体\n列表\n单元格', content_html:
      '<p style="text-align:center"><span style="font-weight:700;font-style:italic;color:#ff0000">红色斜体</span></p><ol start="3"><li>列表</li></ol><table><tr><td colspan="2">单元格</td></tr></table><script>window.wordUnsafe=true</script><img src=x onerror="window.wordUnsafe=true"><a href="javascript:alert(1)">危险链接</a>' }
    await page.route('**/api/v1/**', async route => {
      const url = new URL(route.request().url()).pathname
      const detail = { id: 'log', question: '格式测试', answer: '依据资料回答。[1]', sources: [word, pdfSource], status: 'SUCCESS', answer_status: 'answered', source_type: 'WEB', created_at: '2026-10-28T00:00:00Z', request_id: 'word-test' }
      let data: unknown = detail
      if (url.endsWith('/auth/refresh')) data = { access_token: 'test-token', user: { id: 'reader', display_name: 'Reader', role: 'user' }, pages: [qa, logs] }
      else if (url.endsWith('/knowledge-bases')) data = { items: [{ id: 'base', name: '设备资料', status: 'active' }] }
      else if (url.endsWith('/web/suggested-questions')) data = { questions: [], status: 'empty' }
      else if (url.endsWith('/qa-logs')) data = { items: [detail], total: 1 }
      await route.fulfill({ json: { code: 0, data } })
    })
    await page.goto(path)
    if (path === '/qa') {
      await page.getByRole('textbox', { name: '你的问题' }).fill('格式测试')
      await page.getByRole('button', { name: '发送问题' }).click()
    } else {
      await page.getByRole('button', { name: '查看详情' }).click()
    }
    const rich = page.locator('.word-content')
    await expect(rich.locator('p')).toHaveCSS('text-align', 'center')
    await expect(rich.locator('span')).toHaveCSS('font-weight', '700')
    await expect(rich.locator('span')).toHaveCSS('font-style', 'italic')
    await expect(rich.locator('span')).toHaveCSS('color', 'rgb(255, 0, 0)')
    await expect(rich.locator('ol')).toHaveAttribute('start', '3')
    await expect(rich.locator('td')).toHaveAttribute('colspan', '2')
    await expect(rich.locator('script, img, [onerror], [href^="javascript:"]')).toHaveCount(0)
    expect(await page.evaluate(() => (window as unknown as { wordUnsafe?: boolean }).wordUnsafe)).toBeUndefined()
    await expect(page.locator('.source-plain-text')).toHaveText(pdfSource.content)
  })
}
