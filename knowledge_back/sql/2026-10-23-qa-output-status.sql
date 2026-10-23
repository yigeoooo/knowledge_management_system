-- Optional comment update only; no schema/data migration is needed for the QA fixes.
BEGIN;
COMMENT ON COLUMN qa_logs.status IS '问答状态：PROCESSING 处理中、SUCCESS 成功、PARTIAL 部分有依据、NO_EVIDENCE 依据不足、SOURCES_ONLY 仅返回资料、FAILED 服务失败。';
COMMIT;
