import { expect, test } from '@playwright/test'

const conversation = {
  id: 'conversation-1', title: '宜宾旅游咨询', knowledge_base_id: 'base', knowledge_base_name: '宜宾知识库',
  knowledge_base_status: 'active', turn_count: 1, last_turn_no: 1, last_message_at: '2026-11-09T00:00:00Z',
  deleted_at: null, closed_at: null,
}
const turn = {
  id: 'turn-1', conversation_id: conversation.id, turn_no: 1, question: '宜宾有哪些景点？',
  answer: '可以参观蜀南竹海。', status: 'SUCCESS', answer_status: 'answered', sources: [],
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path.endsWith('/auth/refresh')) data = {
      access_token: 'test-token', user: { id: 'reader', display_name: 'Reader', role_name: '管理员' },
      pages: [{ code: 'knowledge_qa', name: '知识问答', route_path: '/qa', route_name: 'KnowledgeQA',
        component_key: 'KnowledgeQA', page_type: 'menu', is_visible: true }],
    }
    else if (path.endsWith('/knowledge-bases')) data = { items: [{ id: 'base', name: '宜宾知识库' }], total: 1 }
    else if (path.endsWith('/web/suggested-questions')) data = { questions: [] }
    else if (path.endsWith('/web/conversations')) data = { items: [conversation], next_cursor: null }
    else if (path.endsWith(`/web/conversations/${conversation.id}/turns`)) data = { conversation, items: [turn], next_before: null }
    else throw new Error(`Unexpected request: ${path}`)
    await route.fulfill({ json: { code: 0, data } })
  })
})

for (const width of [1440, 1024, 820]) {
  test(`workspace navigation stays fixed beside clickable conversation history at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/qa')
    await expect(page.getByRole('button', { name: '新对话', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '打开菜单', exact: true })).toBeHidden()
    // Visibility alone does not detect a fixed menu covering the history panel.
    await expect.poll(async () => {
      const menu = await page.locator('.workspace-sidebar').boundingBox()
      const history = await page.locator('.chat-history').boundingBox()
      return !!menu && !!history && menu.x === 0 && history.x >= menu.x + menu.width - 1
    }).toBe(true)
    await page.locator('.history-open').click({ timeout: 3000 })
    await expect(page.locator('.conversation-answer')).toContainText('蜀南竹海')
    await expect(page.getByRole('textbox', { name: '你的问题' })).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    if (width === 1440) await page.screenshot({ path: '/tmp/kbs-conversation-menu-open.png' })
    await page.getByRole('button', { name: '收起历史侧栏' }).click()
    await expect(page.locator('.workspace-sidebar')).toBeInViewport()
    await page.getByRole('button', { name: '展开历史侧栏' }).click()
    if (width === 1440) await page.screenshot({ path: '/tmp/kbs-conversation-layout.png' })
  })
}

test('mobile menus can be dismissed and history remains reachable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/qa')
  await page.getByRole('button', { name: '打开菜单', exact: true }).click()
  await page.getByRole('button', { name: '关闭菜单', exact: true }).click({ position: { x: 350, y: 350 } })
  await page.getByRole('button', { name: '展开历史侧栏' }).click()
  await page.locator('.history-open').click()
  await expect(page.locator('.conversation-answer')).toContainText('蜀南竹海')
  await expect(page.getByRole('textbox', { name: '你的问题' })).toBeInViewport()
})

test('new questions, followups, refresh and soft deletion keep the selected conversation', async ({ page }) => {
  const conversations: typeof conversation[] = []
  const messages: Record<string, typeof turn[]> = {}
  const submissions: { path: string; body: Record<string, unknown> }[] = []
  await page.route('**/api/v1/web/conversations**', async route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    let data: unknown
    if (method === 'POST') {
      const body = route.request().postDataJSON()
      submissions.push({ path, body })
      const cid = path.split('/')[5]
      const selected = cid ? conversations.find(c => c.id === cid)! : {
        ...conversation, id: `conversation-${conversations.length + 1}`, title: body.question, turn_count: 0, last_turn_no: 0,
      }
      if (!cid) { conversations.unshift(selected); messages[selected.id] = [] }
      selected.turn_count++; selected.last_turn_no++
      const message = { ...turn, id: `turn-${submissions.length}`, conversation_id: selected.id,
        question: body.question, turn_no: selected.last_turn_no, answer: `回复：${body.question}` }
      messages[selected.id].push(message)
      data = { ...message, conversation: selected }
    } else if (method === 'DELETE') {
      const cid = path.split('/').at(-1)
      conversations.splice(conversations.findIndex(c => c.id === cid), 1)
      data = { deleted: true }
    } else if (path.endsWith('/turns')) {
      const cid = path.split('/')[5]
      data = { conversation: conversations.find(c => c.id === cid), items: messages[cid], next_before: null }
    } else data = { items: conversations, next_cursor: null }
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/qa')
  const input = page.getByRole('textbox', { name: '你的问题' })
  await input.fill('介绍蜀南竹海')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page).toHaveURL(/conversation_id=conversation-1/)
  await input.fill('门票呢？')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.conversation-turn')).toHaveCount(2)
  expect(submissions[1].path).toBe('/api/v1/web/conversations/conversation-1/turns')
  expect(submissions[1].body.expected_last_turn_no).toBe(1)
  expect(submissions[1].body.request_id).not.toBe(submissions[0].body.request_id)
  await page.reload()
  await expect(page.locator('.conversation-turn')).toHaveCount(2)
  await page.getByRole('button', { name: '新对话', exact: true }).click()
  await expect(page.locator('.conversation-turn')).toHaveCount(0)
  await input.fill('另一个话题')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page).toHaveURL(/conversation_id=conversation-2/)
  expect(submissions[2].path).toBe('/api/v1/web/conversations')
  expect(submissions[2].body).not.toHaveProperty('conversation_id')
  await page.getByRole('button', { name: '删除对话 另一个话题', exact: true }).click()
  await page.getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.locator('.history-open')).toHaveCount(1)
  await page.locator('.history-open').click()
  await expect(page.locator('.conversation-turn')).toHaveCount(2)
})

test('unavailable history cannot silently submit a question as a new conversation', async ({ page }) => {
  await page.route('**/api/v1/web/conversations/missing/turns', route => route.fulfill({ status: 404,
    json: { code: 40401, message: '会话不存在或已删除' } }))
  await page.goto('/qa?conversation_id=missing')
  await expect(page.getByText('会话不存在或已删除', { exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '你的问题' })).toBeDisabled()
  await page.getByRole('button', { name: '新对话', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '你的问题' })).toBeEnabled()
})

test('restored long web history shows a session suggestion and keeps the original history', async ({ page }) => {
  const longConversation = { ...conversation, turn_count: 201, last_turn_no: 201 }
  await page.route(`**/web/conversations/${conversation.id}/turns`, route => route.fulfill({
    json: { code: 0, data: { conversation: longConversation,
      items: [{ ...turn, turn_no: 201, context_notice: '较早对话摘要已缩短，如有遗漏请补充具体内容。' }], next_before: 201 } },
  }))
  await page.goto('/qa?conversation_id=conversation-1')
  const notice = page.getByRole('status', { name: '长对话提醒' })
  await expect(notice).toContainText('当前已聊 201 轮')
  await expect(page.locator('.conversation-turn')).toHaveCount(1)
  await expect(page.getByRole('button', { name: '加载更早消息' })).toBeVisible()
  await expect(page.getByText('较早对话摘要已缩短，如有遗漏请补充具体内容。')).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: '你的问题' })).toBeEnabled()
  await notice.getByRole('button', { name: '开启新对话' }).click()
  await expect(notice).toHaveCount(0)
  await expect(page.locator('.conversation-turn')).toHaveCount(0)
  await expect(page).toHaveURL(/\/qa$/)
  await page.locator('.history-open').click()
  await expect(notice).toContainText('201 轮')
  await expect(page.locator('.conversation-answer')).toContainText('蜀南竹海')
})

test('admin switches user and robot histories without retaining another owner’s messages', async ({ page }) => {
  const exported: string[] = []
  let expiredDownload = false
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname
    let data: unknown
    if (path.endsWith('/auth/refresh')) data = { access_token: 'test-token', user: { display_name: 'Admin' },
      pages: [{ code: 'qa_logs', name: '问答日志', route_path: '/qa-logs', route_name: 'QALogs',
        component_key: 'QALogs', page_type: 'menu', is_visible: true }] }
    else if (path.endsWith('/admin/qa-users') || path.endsWith('/admin/qa-robots')) {
      const ids = path.endsWith('/qa-users') ? ['甲用户', '乙用户'] : ['机器人']
      data = { items: ids.map(id => ({ id, name: id, identity: id, status: 'active', conversation_count: 1 })), total: ids.length }
    } else if (path.endsWith('/export')) {
      expect(route.request().headers().authorization).toBe('Bearer test-token')
      if (!expiredDownload) {
        expiredDownload = true
        return route.fulfill({ status: 401, json: { code: 40101, message: '登录已失效', data: null } })
      }
      exported.push(decodeURIComponent(path.split('/')[5]))
      return route.fulfill({ contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', body: Buffer.from('PK\x03\x04 download fixture') })
    } else if (path.endsWith('/admin/qa-conversations')) {
      const owner = url.searchParams.get('user_id') || url.searchParams.get('robot_id')!
      data = { items: [{ ...conversation, id: owner, title: `${owner}的咨询`, owner_name: owner, deleted_at: '2026-11-09T01:00:00Z' }], next_cursor: null }
    } else if (path.endsWith('/turns')) {
      const owner = decodeURIComponent(path.split('/')[5])
      data = { conversation: { ...conversation, id: owner, title: `${owner}的咨询`, owner_name: owner, deleted_at: '2026-11-09T01:00:00Z' },
        items: [{ ...turn, answer: `${owner}的历史回答` }], next_before: null }
    } else return route.fallback()
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/qa-logs')
  for (const owner of ['甲用户', '乙用户']) {
    await page.locator('.owner-item').filter({ hasText: owner }).click()
    await expect(page.locator('.conversation-answer')).toHaveCount(0)
    await page.locator('.audit-conversation').click()
    await expect(page.locator('.conversation-answer')).toHaveText(`${owner}的历史回答`)
    await expect(page.getByText('已软删除 · 审计保留')).toBeVisible()
    const downloading = page.waitForEvent('download')
    await page.getByRole('button', { name: '导出会话（Word）' }).click()
    const download = await downloading
    expect(download.suggestedFilename()).toBe(`会话记录_${owner}的咨询.docx`)
    expect(await download.failure()).toBeNull()
    expect(exported.at(-1)).toBe(owner)
  }
  await page.getByText('机器人对话', { exact: true }).click()
  await expect(page.locator('.conversation-answer')).toHaveCount(0)
  await page.locator('.owner-item').click()
  await page.locator('.audit-conversation').click()
  await expect(page.locator('.conversation-answer')).toHaveText('机器人的历史回答')
})
