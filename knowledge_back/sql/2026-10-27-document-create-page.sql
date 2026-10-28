-- Existing databases: register the authoring page without changing other roles.
BEGIN;
INSERT INTO pages (id, code, name, route_path, route_name, component_key, parent_id, page_type, sort_order, is_visible, status, created_at, updated_at)
VALUES (gen_random_uuid(), 'document_create', '创建文档', '/create-document', 'DocumentCreate', 'DocumentCreate', NULL, 'menu', 45, true, 'active', now(), now())
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_page_permissions (role_id, page_id, can_view, created_at)
SELECT r.id, p.id, true, now() FROM roles r CROSS JOIN pages p
WHERE r.code = 'super_admin' AND p.code = 'document_create'
ON CONFLICT (role_id, page_id) DO UPDATE SET can_view = true;
COMMIT;
