-- 已初始化数据库的用户管理增量说明；不重建表，不修改已有用户数据。
-- 用户状态本来就是 VARCHAR(30)，可直接存储 deleted，本次只补充字段备注。
-- 在项目根目录运行：
-- docker exec -i kbs-postgres psql -U root -d knowledge_db -v ON_ERROR_STOP=1 < knowledge_back/sql/2026-10-21-user-management.sql
BEGIN;

COMMENT ON COLUMN users.status IS '用户状态：active 启用、disabled 停用、deleted 已逻辑删除；已删除用户不展示、不能登录，保留历史关联且用户名不复用。';

UPDATE alembic_version SET version_num = '52c7a3d910e6'
WHERE version_num = '16bb29ab4421';

COMMIT;
