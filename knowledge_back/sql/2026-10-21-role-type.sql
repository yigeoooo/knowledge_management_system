-- 角色类型字段备注同步：is_system 可由管理员在角色管理中切换。
BEGIN;

COMMENT ON COLUMN roles.is_system IS '角色类型：true 系统角色、false 自定义角色；管理员可创建或切换类型。';

COMMIT;
