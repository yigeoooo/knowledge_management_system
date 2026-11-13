"""Administrator CRUD for registered robots."""

from uuid import uuid4

from flask import Blueprint, g, request
from sqlalchemy import or_

from ...application.conversations.service import rebind_robot, uuid_value
from ...application.robots.service import (
    ROBOT_STATUSES,
    commit_robot_change,
    ensure_unique_serial,
    find_robot,
    record_action,
    robot_data,
    validated_input,
)
from ...core.extensions import db
from ...core.http import ApiError, status_filter, success
from ...entities import KnowledgeBase, Robot
from ..auth.controller import page_required

robots = Blueprint("robots", __name__, url_prefix="/api/v1/robots")

@robots.get("")
@page_required("/robots")
def list_robots():
    try:
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("page_size", "20"))
    except ValueError:
        raise ApiError("分页参数必须是整数", 422) from None
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError("页码需大于 0，每页条数需在 1–100 之间", 422)
    keyword = request.args.get("q", "").strip()
    status = status_filter()
    if len(keyword) > 200 or "\x00" in keyword:
        raise ApiError("机器人关键词不能超过 200 个字符或包含空字符", 422)
    if status not in {"", *ROBOT_STATUSES}:
        raise ApiError("机器人状态只能为启用或停用", 422)
    query = db.select(Robot)
    if keyword:
        query = query.where(
            or_(
                Robot.serial_no.icontains(keyword, autoescape=True),
                Robot.name.icontains(keyword, autoescape=True),
            )
        )
    if status:
        query = query.where(Robot.status == status)
    if request.args.get("knowledge_base_id"):
        query = query.where(Robot.knowledge_base_id == uuid_value(request.args["knowledge_base_id"]))
    result = db.paginate(
        query.order_by(Robot.created_at.desc(), Robot.id),
        page=page,
        per_page=page_size,
        error_out=False,
    )
    return success(
        {
            "items": [robot_data(robot) for robot in result.items],
            "total": result.total,
            "page": page,
            "page_size": page_size,
        }
    )


@robots.get("/<uuid:robot_id>")
@page_required("/robots")
def robot_detail(robot_id):
    return success(robot_data(find_robot(robot_id)))


@robots.get("/knowledge-base-options")
@page_required("/robots")
def knowledge_base_options():
    bases = db.session.scalars(db.select(KnowledgeBase).where(KnowledgeBase.status == "active")
                              .order_by(KnowledgeBase.name, KnowledgeBase.id)).all()
    return success({"items": [{"id": str(base.id), "name": base.name, "code": base.code} for base in bases]})


@robots.post("")
@page_required("/robots")
def create_robot():
    values = validated_input(creating=True)
    ensure_unique_serial(values["serial_no"])
    robot = Robot(id=uuid4(), created_by=g.user.id, **values)
    db.session.add(robot)
    record_action(
        "robot.create",
        robot,
        {"serial_no": robot.serial_no, "name": robot.name, "status": robot.status,
         "knowledge_base_id": str(robot.knowledge_base_id)},
    )
    commit_robot_change()
    return success(robot_data(robot)), 201


@robots.put("/<uuid:robot_id>")
@page_required("/robots")
def update_robot(robot_id):
    robot = find_robot(robot_id, lock=True)
    values = validated_input()
    if "serial_no" in values:
        ensure_unique_serial(values["serial_no"], robot.id)
    changes = {
        field: {"before": str(getattr(robot, field)) if field == "knowledge_base_id" else getattr(robot, field),
                "after": str(value) if field == "knowledge_base_id" else value}
        for field, value in values.items()
        if getattr(robot, field) != value
    }
    if "knowledge_base_id" in values:
        base_id = values.pop("knowledge_base_id")
        expected = request.get_json().get("expected_binding_version")
        if base_id != robot.knowledge_base_id and expected is None:
            raise ApiError("换绑时请提供 expected_binding_version", 422)
        rebind_robot(robot, base_id, expected)
    for field, value in values.items():
        setattr(robot, field, value)
    if changes:
        record_action("robot.update", robot, {"changes": changes})
    commit_robot_change()
    return success(robot_data(robot))


@robots.delete("/<uuid:robot_id>")
@page_required("/robots")
def disable_robot(robot_id):
    robot = find_robot(robot_id, lock=True)
    if robot.status != "disabled":
        previous_status = robot.status
        robot.status = "disabled"
        record_action("robot.delete", robot, {"previous_status": previous_status})
        commit_robot_change()
    return success({"id": str(robot.id), "status": robot.status})


@robots.get("/location-options")
@page_required("/robots")
def location_options():
    from time import monotonic

    from ...application.realtime.service import _get
    query = request.args.get("q", "").strip()
    if not 2 <= len(query) <= 100:
        return success({"items": []})
    try:
        result = _get("/geo/v2/city/lookup", {"location": query, "number": 20, "lang": "zh"}, monotonic() + 5)
        items = [{"value": p["id"], "label": " / ".join(dict.fromkeys(filter(None, [p.get("country"), p.get("adm1"), p.get("adm2"), p.get("name")]))), "timezone": p["tz"]} for p in result.get("location", [])]
    except (OSError, ValueError, KeyError, TypeError):
        raise ApiError("地区查询暂不可用，请稍后重试", 503) from None
    return success({"items": items})


@robots.get("/timezone-options")
@page_required("/robots")
def timezone_options():
    from zoneinfo import available_timezones
    zones = sorted(available_timezones())
    return success({"items": ["Asia/Shanghai", *[z for z in zones if z != "Asia/Shanghai"]]})
