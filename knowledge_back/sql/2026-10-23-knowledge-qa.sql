-- Optional metadata update only. Existing columns already support knowledge Q&A.
BEGIN;
COMMENT ON COLUMN qa_logs.status IS '问答状态：PROCESSING 处理中、SUCCESS 成功、NO_EVIDENCE 依据不足、FAILED 失败。';
COMMIT;
