"""Prepare a reviewable seven-purpose candidate from current published versions."""
from sqlalchemy import func

from ...core.extensions import db
from ...core.http import ApiError
from ...entities import PromptTemplate, PromptVersion
from .composition import encode_sections
from .registry import NEW_KEYS, published_snapshot, version_data

PLAN_COMMON = """理解当前问题和同一会话历史，保留已知人数、条件、话题地点和未解决事项。历史回答不是事实证据。
使用 ConversationPlan 输出协议；旧规则中的输出字段仅为迁移参考，以本协议为准。
knowledge 必须给 knowledge_query；chat/general/clarification 仅给 direct_answer；其他意图 direct_answer 必须为空。
业务询价或个性化推荐确实缺必要条件时才追问；明确单价和价格清单直接检索，历史已给条件不重复问。
"""
PLAN_REALTIME = """实时信息直接规划，不反问。混合问题使用 realtime，同时填写业务 knowledge_query。
地点优先当前问题→当前话题→runtime.default_location；明确地点解析失败不得改用默认地点。
location_source 必须如实填写 question/history/default。日期结合 runtime.now 和时区解释，输出 YYYY-MM-DD；现在用 now，明天/后天用 daily。
仅选择 tool_capabilities.tools 中工具。时间工具指定 IANA 时区或沿用配置，不猜时区。
缺少参数、工具未启用、实时营业/余票/新闻不支持时填 unavailable；没有真实结果前不能写实时答案。
"""
ANSWER_COMMON = """仅使用本轮输入证据生成答案，使用 AnswerDraft 协议，引用输入中真实存在的段落编号。
保留数值、单位、条件和限制。历史仅用于理解问题。无证据部分说明无法确认，不猜测。
"""
REALTIME_RULES = """实时事实必须有本轮成功工具证据。核对地点、日期、时区、实况/预报、获取时间和有效期。
回复明确地点和日期；不把静态文档或过去聊天当作最新天气。失败、缺参数和过期数据不能当作成功。
混合问题分别处理天气和业务依据；不能根据晴雨推断实时营业或余票。实时查询不得反问。
"""


def prepare(user_id):
    db.session.scalars(db.select(PromptTemplate).order_by(PromptTemplate.key).with_for_update()).all()
    baseline = published_snapshot()
    if "conversation_plan" in baseline:
        raise ApiError("新流程已启用，请使用日常版本管理", 409)
    existing = db.session.get(PromptTemplate, "conversation_plan")
    if existing:
        return candidate_bundle()
    contents = {
        "conversation_plan": ("对话理解与调度", encode_sections({
            "common": PLAN_COMMON,
            "web": baseline["resolve_web"]["content"] + "\n网页仅允许 knowledge/clarification，不调用工具。",
            "robot": "以下为现行规则迁移参考，输出改用新协议，实时行为以实时分区为准：\n" + baseline["robot_interaction"]["content"] + "\n" + baseline["resolve_robot"]["content"],
            "realtime": PLAN_REALTIME,
        })),
        "answer_generate": ("答案生成", encode_sections({
            "common": ANSWER_COMMON, "web": baseline["answer_web"]["content"],
            "robot": baseline["answer_robot"]["content"], "realtime": REALTIME_RULES,
        })),
        "review_answer": ("答案证据核验", encode_sections({
            "common": baseline["review_answer"]["content"], "realtime": REALTIME_RULES,
        })),
    }
    for key, (name, content) in contents.items():
        template = db.session.get(PromptTemplate, key)
        if template is None:
            template = PromptTemplate(key=key, name=name, active_version=0)
            db.session.add(template)
            db.session.flush()
        latest = db.session.scalar(db.select(func.max(PromptVersion.version)).where(PromptVersion.prompt_key == key)) or 0
        db.session.add(PromptVersion(prompt_key=key, version=latest + 1, content=content,
                                    note="从当前发布版本提取的迁移候选；需检查分区冲突并完成迁移评测。来源：" + ",".join(f"{k}:v{v['version']}" for k, v in baseline.items()), created_by=user_id))
    db.session.flush()
    return candidate_bundle()


def candidate_bundle():
    current = published_snapshot()
    if "conversation_plan" in current:
        raise ApiError("新流程已启用", 409)
    result = {key: value for key, value in current.items() if key in NEW_KEYS}
    for key in ("conversation_plan", "answer_generate", "review_answer"):
        version = db.session.scalar(db.select(PromptVersion).where(PromptVersion.prompt_key == key).order_by(PromptVersion.version.desc()).limit(1))
        if version is None:
            raise ApiError("请先准备迁移候选", 409)
        result[key] = version_data(version)
    return result
