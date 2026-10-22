-- Document storage and multi-format upload support for existing databases.
-- This script changes comments and indexes only; document data is preserved.
BEGIN;

COMMENT ON COLUMN documents.knowledge_base_id IS '所属知识库 ID，关联 knowledge_bases.id；文档只能在所属知识库下管理。';
COMMENT ON COLUMN documents.status IS '文档状态：active 有效、archived 已归档；归档后保留历史版本。';
COMMENT ON COLUMN document_versions.minio_bucket IS '存放原始文件的私有 MinIO 存储桶名称。';
COMMENT ON COLUMN document_versions.minio_object_key IS '唯一 MinIO 对象键；按知识库、文档和版本组织，不保存本地路径。';
COMMENT ON COLUMN document_versions.filename IS '原始文件名；支持 Markdown、TXT、PDF、Word、图片和视频。';
COMMENT ON COLUMN document_versions.content_type IS '文件媒体类型，用于预览和下载响应。';
COMMENT ON COLUMN document_versions.status IS '处理状态：PENDING_UPLOAD 待上传、UPLOADED 已上传、PROCESSING 处理中、EMBEDDING 向量化中、INDEXED 文本/图片/视频可检索或其他文件已就绪、FAILED 失败、ARCHIVED 已归档。';
COMMENT ON COLUMN document_versions.error_message IS '处理失败或非文本文件说明；不得写入密钥或密码。';
COMMENT ON COLUMN document_chunks.content IS '文本切片或媒体文件标识，供检索和回答引用使用。';
COMMENT ON COLUMN document_chunks.metadata IS '切片附加信息，JSON 对象，可记录行号、代码块、表格位置和 image/video 模态。';
COMMENT ON COLUMN index_tasks.task_type IS '任务类型：INDEX 首次索引、REINDEX 重新索引、DELETE 删除对象与切片。';
COMMENT ON COLUMN index_tasks.status IS '执行状态：PENDING 待处理、RUNNING 执行中、SUCCESS 成功、FAILED 失败。';

CREATE INDEX IF NOT EXISTS idx_index_tasks_pending ON index_tasks (status, created_at);
CREATE INDEX IF NOT EXISTS idx_document_versions_document_status
    ON document_versions (document_id, status, version_no);

COMMIT;
