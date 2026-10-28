import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

async function setup(page: Page) {
  const base = { id: 'base', name: '人员测试库', code: 'staff', status: 'active', created_by: 'creator-uuid', created_by_name: '张三', updated_by_name: '李四', updated_at: '2026-10-28T00:00:00Z' }
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path.endsWith('/auth/refresh')) {
      data = { access_token: 'test-token', user: { id: 'admin', role: 'super_admin', display_name: '管理员' }, pages: [
        { code: 'bases', name: '知识库管理', route_path: '/knowledge-bases', component_key: 'KnowledgeBaseManagement', is_visible: true },
        { code: 'documents', name: '文档管理', route_path: '/documents', component_key: 'DocumentManagement', is_visible: true },
      ] }
    } else if (path.endsWith('/knowledge-bases')) data = { items: [base], total: 1 }
    else if (path.endsWith('/documents')) data = { items: [{ ...base, id: 'document', knowledge_base_id: 'base', title: '维护说明', current_version: null }], total: 1, max_file_size: 200 * 1024 * 1024 }
    else throw new Error(`Unexpected request: ${path}`)
    await route.fulfill({ json: { code: 0, data } })
  })
}

for (const path of ['/knowledge-bases', '/documents']) {
  test(`${path} shows creator and last editor display names`, async ({ page }) => {
    await setup(page)
    await page.goto(path)
    await expect(page.getByRole('columnheader', { name: '创建人', exact: true })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '最后修改人', exact: true })).toBeVisible()
    const body = page.locator('.el-table__body-wrapper')
    await expect(body).toContainText('张三')
    await expect(body).toContainText('李四')
    await expect(body).not.toContainText('creator-uuid')
  })
}

test('upload picker accepts up to 200 MB and rejects files larger than the server limit', async ({ page }) => {
  await setup(page)
  await page.goto('/documents')
  await page.getByRole('button', { name: '上传文件', exact: true }).click()
  const picker = page.locator('input[type=file]').first()
  for (const size of [21 * 1024 * 1024, 200 * 1024 * 1024, 200 * 1024 * 1024 + 1]) {
    await picker.evaluate((input: HTMLInputElement, size) => {
      const file = new File(['x'], 'large.docx')
      Object.defineProperty(file, 'size', { value: size })
      const transfer = new DataTransfer()
      transfer.items.add(file)
      input.files = transfer.files
      input.dispatchEvent(new Event('change', { bubbles: true }))
    }, size)
    const save = page.getByRole('button', { name: '开始上传', exact: true })
    if (size <= 200 * 1024 * 1024) await expect(save).toBeEnabled()
    else {
      await expect(save).toBeDisabled()
      await expect(page.getByText('文件需非空，且不超过 200.0 MB', { exact: true })).toBeVisible()
    }
  }
})
