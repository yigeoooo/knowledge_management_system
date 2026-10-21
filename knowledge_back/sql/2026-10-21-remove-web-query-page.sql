-- 删除重复的“网页提问测试”页面（/ask），统一使用“知识问答”（/qa）。
-- 适用于已初始化的数据库，可重复执行；新环境的 init.sql 已移除此页面。
-- 仅调整页面和授权数据，不改变表结构或 Alembic 结构版本。
-- 在项目根目录运行：
-- docker exec -i kbs-postgres psql -U root -d knowledge_db -v ON_ERROR_STOP=1 < knowledge_back/sql/2026-10-21-remove-web-query-page.sql
BEGIN;

-- 先删除所有角色对该页面的权限绑定，避免 pages 外键约束阻止删除。
DELETE FROM role_page_permissions
WHERE page_id IN (SELECT id FROM pages WHERE code = 'web_query');

-- 移除动态路由和菜单使用的页面记录。
DELETE FROM pages WHERE code = 'web_query';

-- 同步旧版初始化的普通用户角色说明，保留管理员自行修改的其他描述。
UPDATE roles
SET description = '访问知识问答与个人信息', updated_at = CURRENT_TIMESTAMP
WHERE code = 'user' AND description = '访问知识问答、网页提问测试与个人信息';

COMMIT;
