import { expect, test, type Page } from '@playwright/test'

const robots = [
  { id: 'robot-1', name: '宜宾机器人', serial_no: 'serial-one', status: 'active', knowledge_base_id: 'base-1', knowledge_base_name: '宜宾知识库', knowledge_base_status: 'active' },
  { id: 'robot-2', name: '设备机器人', serial_no: 'serial-two', status: 'active', knowledge_base_id: 'base-2', knowledge_base_name: '设备知识库', knowledge_base_status: 'active' },
  { id: 'robot-disabled', name: '停用机器人', serial_no: 'serial-disabled', status: 'disabled', knowledge_base_id: 'base-2', knowledge_base_name: '设备知识库', knowledge_base_status: 'active' },
]
const pages = [
  { code: 'knowledge_qa', name: '知识问答', route_path: '/qa', route_name: 'KnowledgeQA', component_key: 'KnowledgeQA', page_type: 'menu', is_visible: true },
  { code: 'robot_qa', name: '机器人问答', route_path: '/robot-qa', route_name: 'RobotQA', component_key: 'RobotQA', page_type: 'menu', is_visible: true },
]

async function mockRobot(page: Page, options: { timeout?: boolean; fail?: boolean; regular?: boolean } = {}) {
  const sessions: any[] = [], messages = new Map<string, any[]>(), receipts = new Map<string, any>()
  const posts: { path: string; body: Record<string, any>; headers: Record<string, string> }[] = []
  const unexpected: string[] = []
  let timeout = options.timeout, fail = options.fail
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
    let data: unknown
    if (path.endsWith('/auth/refresh')) data = { access_token: 'test-token', user: { id: 'admin', display_name: '管理员', role_name: '管理员' }, pages: options.regular ? pages.slice(0, 1) : pages }
    else if (path.endsWith('/admin/robot-chat/robots')) data = { items: robots, total: robots.length }
    else if (path.startsWith('/api/v1/admin/robot-chat/robots/')) {
      const parts = path.split('/'), rid = parts[6], cid = parts[8]
      data = cid ? { conversation: sessions.find(c => c.id === cid && c.robot_id === rid), items: messages.get(cid) || [], next_before: null }
        : { items: sessions.filter(c => c.robot_id === rid), next_cursor: null }
      if (cid && !sessions.some(c => c.id === cid && c.robot_id === rid)) return route.fulfill({ status: 404, json: { code: 40401, message: '会话不存在或已删除' } })
    } else if (method === 'POST' && path.startsWith('/api/v1/robot/')) {
      const body = request.postDataJSON(), headers = request.headers()
      posts.push({ path, body, headers })
      if (path.endsWith('/retry')) {
        const cid = path.split('/')[5], tid = path.split('/')[7]
        const turn = messages.get(cid)!.find(t => t.id === tid)
        Object.assign(turn, { status: 'SUCCESS', answer: '重试后的简洁回答。', error_message: null })
        data = { ...turn, conversation: sessions.find(c => c.id === cid) }
      } else {
        const robot = robots.find(r => r.serial_no === body.serial_no)!
        let result = receipts.get(body.request_id)
        if (!result) {
          const conversation = body.conversation_id ? sessions.find(c => c.id === body.conversation_id)! : {
            id: `conversation-${sessions.length + 1}`, title: body.question, robot_id: robot.id, source_type: 'ROBOT',
            knowledge_base_id: robot.knowledge_base_id, knowledge_base_name: robot.knowledge_base_name, knowledge_base_status: 'active',
            turn_count: 0, last_turn_no: 0, closed_at: null, deleted_at: null, last_message_at: '2026-11-09T00:00:00Z',
          }
          if (!body.conversation_id) { sessions.push(conversation); messages.set(conversation.id, []) }
          conversation.last_turn_no++; conversation.turn_count++
          const turn = { id: `turn-${receipts.size + 1}`, turn_id: `turn-${receipts.size + 1}`, conversation_id: conversation.id, turn_no: conversation.last_turn_no,
            question: body.question, request_id: body.request_id, answer: fail ? null : `简洁回答：${body.question}`, status: fail ? 'FAILED' : 'SUCCESS',
            sources: [], error_message: fail ? '服务暂不可用' : null, created_at: '2026-11-09T00:00:00Z' }
          fail = false
          messages.get(conversation.id)!.push(turn)
          result = { ...turn, conversation }; receipts.set(body.request_id, result)
        }
        data = result
        if (timeout) { timeout = false; return route.fulfill({ status: 504, json: { code: 50401, message: '等待回答超时，请重试' } }) }
      }
    } else if (method === 'DELETE' && path.startsWith('/api/v1/robot/conversations/')) {
      const index = sessions.findIndex(c => c.id === path.split('/')[5])
      sessions.splice(index, 1); data = { deleted: true }
    } else {
      unexpected.push(`${method} ${path}`)
      return route.fulfill({ status: 404, json: { code: 40400, message: 'Unexpected request' } })
    }
    await route.fulfill({ json: { code: 0, message: 'ok', data } })
  })
  return { posts, sessions, messages, unexpected }
}

test('simulator uses robot first/followup APIs, restores history and isolates new conversations', async ({ page }) => {
  const state = await mockRobot(page)
  await page.goto('/robot-qa')
  await expect(page.getByRole('menuitem', { name: '机器人问答' })).toBeVisible()
  const input = page.getByRole('textbox', { name: '你的问题' })
  await expect(input).toBeEnabled()
  await expect(page.locator('.chat-title')).toContainText('宜宾知识库')
  await input.fill('介绍宜宾')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.conversation-answer')).toHaveText('简洁回答：介绍宜宾')
  expect(state.posts[0].path).toBe('/api/v1/robot/query')
  expect(state.posts[0].body).toMatchObject({ serial_no: 'serial-one', question: '介绍宜宾' })
  expect(state.posts[0].body).not.toHaveProperty('knowledge_base_id')
  expect(state.posts[0].body).not.toHaveProperty('conversation_id')
  await input.fill('还有呢？')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.conversation-answer')).toHaveCount(2)
  expect(state.posts[1].path).toBe('/api/v1/robot/conversations/query')
  expect(state.posts[1].body).toMatchObject({ conversation_id: 'conversation-1', expected_last_turn_no: 1 })
  await page.reload()
  await expect(page.locator('.conversation-answer')).toHaveCount(2)
  await page.getByRole('button', { name: '新对话', exact: true }).click()
  await input.fill('新话题')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page).toHaveURL(/conversation_id=conversation-2/)
  expect(state.posts[2].path).toBe('/api/v1/robot/query')
  await page.getByRole('button', { name: '删除对话 新话题', exact: true }).click()
  await page.getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.locator('.history-open')).toHaveCount(1)
  await page.locator('.history-open').click()
  await expect(page.locator('.conversation-answer')).toHaveCount(2)
  await page.getByRole('combobox', { name: '选择机器人' }).click()
  await page.getByRole('option', { name: '设备机器人', exact: true }).click()
  await expect(page.locator('.conversation-answer')).toHaveCount(0)
  await expect(page.locator('.history-open')).toHaveCount(0)
  await expect(page.locator('.chat-title')).toContainText('设备知识库')
  await input.fill('如何开机？')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.conversation-answer')).toHaveCount(1)
  expect(state.posts[3].body.serial_no).toBe('serial-two')
  expect(state.posts[3].body).not.toHaveProperty('conversation_id')
  expect(state.unexpected).toEqual([])
})

test('timeout resumes the exact request without creating another conversation', async ({ page }) => {
  const state = await mockRobot(page, { timeout: true })
  await page.goto('/robot-qa')
  await page.getByRole('textbox', { name: '你的问题' }).fill('介绍宜宾')
  await page.getByRole('button', { name: '发送问题' }).click()
  await page.getByRole('button', { name: '继续等待回答' }).click()
  await expect(page.locator('.conversation-answer')).toHaveText('简洁回答：介绍宜宾')
  expect(state.posts).toHaveLength(2)
  expect(state.posts[1].body).toEqual(state.posts[0].body)
  expect(state.sessions).toHaveLength(1)
  expect(state.unexpected).toEqual([])
})

test('long robot conversations recommend a fresh session after 200 turns without interrupting followups', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await mockRobot(page)
  await page.goto('/robot-qa')
  const input = page.getByRole('textbox', { name: '你的问题' })
  await input.fill('第一条问题')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page).toHaveURL(/conversation_id=conversation-1/)
  Object.assign(state.sessions[0], { turn_count: 200, last_turn_no: 200 })
  Object.assign(state.messages.get('conversation-1')![0], {
    turn_no: 200, context_notice: '较早对话摘要已缩短，如有遗漏请补充具体内容。',
  })
  await page.reload()
  // Only one history item is loaded, but the conversation total is 200.
  await expect(page.locator('.chat-title')).toContainText('200 轮对话')
  await expect(page.getByRole('status', { name: '长对话提醒' })).toHaveCount(0)
  await expect(page.getByText('较早对话摘要已缩短，如有遗漏请补充具体内容。')).toHaveCount(0)
  await input.fill('继续当前话题')
  await page.getByRole('button', { name: '发送问题' }).click()
  const notice = page.getByRole('status', { name: '长对话提醒' })
  await expect(notice).toContainText('当前已聊 201 轮')
  await expect(input).toBeEnabled()
  await expect(input).toBeInViewport()
  expect(state.posts[1].body).toMatchObject({ conversation_id: 'conversation-1', expected_last_turn_no: 200 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '/tmp/kbs-long-conversation-mobile.png' })
  await notice.getByRole('button', { name: '开启新对话' }).click()
  await expect(notice).toHaveCount(0)
  await expect(page.locator('.conversation-turn')).toHaveCount(0)
  await input.fill('新的话题')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page).toHaveURL(/conversation_id=conversation-2/)
  expect(state.posts[2].path).toBe('/api/v1/robot/query')
  expect(state.posts[2].body).not.toHaveProperty('conversation_id')
  expect(state.sessions).toHaveLength(2)
  expect(state.unexpected).toEqual([])
})

test('failed answer retries synchronously with robot serial header', async ({ page }) => {
  const state = await mockRobot(page, { fail: true })
  await page.goto('/robot-qa')
  await page.getByRole('textbox', { name: '你的问题' }).fill('介绍宜宾')
  await page.getByRole('button', { name: '发送问题' }).click()
  await page.getByRole('button', { name: '重试回答', exact: true }).click()
  await expect(page.locator('.conversation-answer')).toHaveText('重试后的简洁回答。')
  expect(state.posts[1].path).toBe('/api/v1/robot/conversations/conversation-1/turns/turn-1/retry')
  expect(state.posts[1].headers['x-robot-serial']).toBe('serial-one')
  expect(state.posts[1].body).toEqual({})
  await expect(page.locator('.conversation-turn')).toHaveCount(1)
})

test('an unfinished turn restored from history resumes with its original request ID', async ({ page }) => {
  const state = await mockRobot(page)
  await page.goto('/robot-qa')
  await page.getByRole('textbox', { name: '你的问题' }).fill('介绍宜宾')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.conversation-answer')).toHaveCount(1)
  Object.assign(state.messages.get('conversation-1')![0], { status: 'PROCESSING', answer: null })
  await page.reload()
  await expect(page.getByRole('textbox', { name: '你的问题' })).toBeDisabled()
  await page.getByRole('button', { name: '继续等待回答' }).click()
  await expect(page.locator('.conversation-answer')).toHaveText('简洁回答：介绍宜宾')
  expect(state.posts[1].body.request_id).toBe(state.posts[0].body.request_id)
  expect(state.posts[1].body.conversation_id).toBe('conversation-1')
  expect(state.sessions).toHaveLength(1)
  expect(state.unexpected).toEqual([])
})

test('switching robots while waiting cannot attach the old answer to the new robot', async ({ page }) => {
  await mockRobot(page)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/v1/robot/query', async route => {
    await gate
    await route.fallback()
  })
  await page.goto('/robot-qa')
  await page.getByRole('textbox', { name: '你的问题' }).fill('介绍宜宾')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.conversation-turn')).toHaveCount(1)
  await page.getByRole('combobox', { name: '选择机器人' }).click()
  await page.getByRole('option', { name: '设备机器人', exact: true }).click()
  release()
  await expect(page.locator('.chat-title')).toContainText('设备知识库')
  await expect(page.locator('.conversation-turn')).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: '你的问题' })).toBeEnabled()
  await expect(page).toHaveURL(/robot_id=robot-2/)
})

test('disabled robots and unavailable history cannot silently create new conversations', async ({ page }) => {
  const state = await mockRobot(page)
  await page.goto('/robot-qa?robot_id=robot-1&conversation_id=missing')
  await expect(page.getByText('会话不存在或已删除', { exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '你的问题' })).toBeDisabled()
  await page.getByRole('button', { name: '新对话', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '你的问题' })).toBeEnabled()
  await page.getByRole('combobox', { name: '选择机器人' }).click()
  await page.getByRole('option', { name: '停用机器人（已停用）', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '你的问题' })).toBeDisabled()
  expect(state.posts).toEqual([])
})

test('regular users cannot open the simulator page', async ({ page }) => {
  const state = await mockRobot(page, { regular: true })
  await page.goto('/robot-qa')
  await expect(page).toHaveURL(/\/403$/)
  await expect(page.getByRole('menuitem', { name: '机器人问答' })).toHaveCount(0)
  expect(state.unexpected).toEqual([])
})

test('robot chat keeps the desktop menu fixed and the mobile composer visible', async ({ page }) => {
  await mockRobot(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/robot-qa')
  await expect(page.getByRole('textbox', { name: '你的问题' })).toBeEnabled()
  const menu = await page.locator('.workspace-sidebar').boundingBox(), history = await page.locator('.chat-history').boundingBox()
  expect(history!.x).toBeGreaterThanOrEqual(menu!.x + menu!.width - 1)
  await page.screenshot({ path: '/tmp/kbs-robot-chat-desktop.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(page.getByRole('textbox', { name: '你的问题' })).toBeInViewport()
  await page.getByRole('button', { name: '展开历史侧栏' }).click()
  await page.getByRole('button', { name: '关闭历史侧栏' }).click({ position: { x: 350, y: 350 } })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '/tmp/kbs-robot-chat-mobile.png' })
})
