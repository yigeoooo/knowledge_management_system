from io import BytesIO
from uuid import UUID, uuid4

import test_conversations as conversation_tests
import test_page_authorization as authorization_tests
from docx import Document
from docx.oxml.ns import qn
from test_conversations import first
from test_page_authorization import grant

from app.entities import QAConversation, QALog
from app.extensions import db
from app.workers import qa_worker

setup = conversation_tests.setup
reader = authorization_tests.reader


def test_export_contains_all_turns_and_formats_answers_and_sources(app, client, setup):
    created = first(client, setup, question="启动/教程：设备操作")
    qa_worker.process_one(app)
    with app.app_context():
        conversation = db.session.get(QAConversation, UUID(created["conversation_id"]))
        log = db.session.get(QALog, UUID(created["turn_id"]))
        log.answer = "## 启动步骤\n\n先**检查电源**。[1]\n\n1. 接通电源\n2. 开机\n\n| 项目 | 状态 |\n|---|---|\n| 电源 | 正常 |\n\n```python\nprint('启动')\n```"
        log.sources = [
            {
                "source_id": "1",
                "document_title": "操作手册",
                "filename": "guide.pdf",
                "version_no": 2,
                "content": "原始引用\n启动前检查接地。",
                "preview_url": "https://private.invalid/never-export-this-url",
            }
        ]
        for number in range(2, 36):
            db.session.add(
                QALog(
                    conversation_id=conversation.id,
                    turn_no=number,
                    source_type="WEB",
                    user_id=conversation.user_id,
                    knowledge_base_id=conversation.knowledge_base_id,
                    question=f"第 {number} 个问题",
                    answer=f"第 {number} 个答案" if number < 34 else None,
                    status="SUCCESS" if number < 34 else ("FAILED" if number == 34 else "PENDING"),
                    error_message="示例失败原因" if number == 34 else None,
                    request_id=str(uuid4()),
                    sources=[],
                )
            )
        conversation.next_turn_no = 36
        db.session.commit()
    response = client.get(
        f"/api/v1/admin/qa-conversations/{created['conversation_id']}/export",
        headers=setup["headers"],
    )
    assert response.status_code == 200
    assert (
        response.mimetype
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment;" in response.headers["Content-Disposition"]
    assert "filename*=UTF-8''" in response.headers["Content-Disposition"]
    document = Document(BytesIO(response.data))
    text = "\n".join(p.text for p in document.paragraphs)
    assert "第 1 轮" in text and "第 35 轮" in text
    assert text.index("第 1 轮") < text.index("第 35 轮")
    assert "示例失败原因" in text and "本轮回答尚未完成" in text
    assert "[1] 操作手册" in text and "启动前检查接地" in text
    assert "never-export-this-url" not in text
    assert "1. 接通电源" in text and "2. 开机" in text
    assert "print('启动')" in text
    assert any(r.text == "检查电源" and r.bold for p in document.paragraphs for r in p.runs)
    assert document.tables[1].cell(1, 1).text == "正常"
    assert document.styles["Normal"].element.rPr.rFonts.get(qn("w:eastAsia")) == "宋体"
    assert "NUMPAGES" in document.sections[0].footer._element.xml
    assert not [r for r in document.part.rels.values() if r.is_external]
    # Only citations start collapsed, and their outline section ends before the
    # next turn. Neither the answer nor its request identifier belongs to it.
    paragraphs = document.paragraphs
    heading = next(p for p in paragraphs if p.text == "引用资料")
    collapsed_tag = "{http://schemas.microsoft.com/office/word/2012/wordml}collapsed"
    assert heading.style.name == "Heading 2"
    assert heading._p.pPr.find(qn("w:outlineLvl")).get(qn("w:val")) == "1"
    assert heading._p.pPr.find(collapsed_tag) is not None
    assert [
        p.text
        for p in paragraphs
        if p._p.pPr is not None and p._p.pPr.find(collapsed_tag) is not None
    ] == ["引用资料"]
    assert text.index(f"请求编号：{created['request_id']}") < text.index("引用资料")
    assert next(p for p in paragraphs if p.text == "第 2 轮").style.name == "Heading 1"
    ignorable = document.element.get(
        "{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable"
    ).split()
    assert "w15" in ignorable
    assert all(prefix in document.element.nsmap for prefix in ignorable)
    mode = next(
        item
        for item in document.settings.element.find(qn("w:compat"))
        if item.get(qn("w:name")) == "compatibilityMode"
    )
    assert mode.get(qn("w:val")) == "15"


def test_export_requires_history_permission_and_preserves_deleted_history(
    app, client, setup, reader
):
    created = first(client, setup)
    cid = created["conversation_id"]
    url = f"/api/v1/admin/qa-conversations/{cid}/export"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=reader).status_code == 403
    client.delete(f"/api/v1/web/conversations/{cid}", headers=setup["headers"])
    grant(app, "/qa-logs")
    response = client.get(url, headers=reader)
    assert response.status_code == 200
    document = Document(BytesIO(response.data))
    assert "已软删除" in document.tables[0].cell(3, 1).text
    assert "已取消" in "\n".join(p.text for p in document.paragraphs)
    assert (
        client.get(f"/api/v1/admin/qa-conversations/{uuid4()}/export", headers=reader).status_code
        == 404
    )
