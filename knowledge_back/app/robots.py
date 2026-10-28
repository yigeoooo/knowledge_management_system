"""Administrator CRUD for registered robots."""

from uuid import uuid4

from flask import Blueprint, g, request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .auth import page_required
from .extensions import db
from .http import ApiError, status_filter, success
from .models import AuditLog, Robot

robots = Blueprint("robots", __name__, url_prefix="/api/v1/robots")
ROBOT_STATUSES = {"active", "disabled"}
ROBOT_FIELDS = {"serial_no", "name", "description", "status"}


def robot_data(robot):
    return {
        "id": str(robot.id),
        "serial_no": robot.serial_no,
        "name": robot.name,
        "description": robot.description,
        "status": robot.status,
        "last_request_at": robot.last_request_at.isoformat() if robot.last_request_at else None,
        "created_by": str(robot.created_by) if robot.created_by else None,
        "created_at": robot.created_at.isoformat(),
        "updated_at": robot.updated_at.isoformat(),
    }


def find_robot(robot_id, *, lock=False):
    query = db.select(Robot).where(Robot.id == robot_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    robot = db.session.scalar(query)
    if robot is None:
        raise ApiError("机器人不存在", 404, 40401)
    return robot


def valid_text(value, label, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ApiError(f"{label}需为 1–{maximum} 个字符", 422)
    value = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ApiError(f"{label}不能包含控制字符", 422)
    return value


def valid_optional_text(value, label, maximum):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise ApiError(f"{label}不能超过 {maximum} 个字符", 422)
    value = value.strip()
    if any(ord(character) < 32 and character not in "\r\n\t" for character in value):
        raise ApiError(f"{label}不能包含控制字符", 422)
    return value or None


def validated_input(*, creating=False):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not body:
        raise ApiError("请提交机器人信息", 422)
    if set(body) - ROBOT_FIELDS:
        raise ApiError("请求包含不支持的机器人字段", 422)
    if creating and "serial_no" not in body:
        raise ApiError("请填写机器人序列号", 422)

    values = {}
    if "serial_no" in body:
        values["serial_no"] = valid_text(body["serial_no"], "机器人序列号", 100)
    if "name" in body:
        values["name"] = valid_optional_text(body["name"], "机器人名称", 200)
    if "description" in body:
        values["description"] = valid_optional_text(body["description"], "机器人描述", 2000)
    if "status" in body or creating:
        status = body.get("status", "active")
        if status not in ROBOT_STATUSES:
            raise ApiError("机器人状态只能为启用或停用", 422)
        values["status"] = status
    return values


def ensure_unique_serial(serial_no, robot_id=None):
    existing = db.session.scalar(db.select(Robot).where(Robot.serial_no == serial_no))
    if existing is not None and existing.id != robot_id:
        raise ApiError("机器人序列号已被使用，请更换序列号", 409, 40901)


def record_action(action, robot, detail):
    db.session.add(
        AuditLog(
            user_id=g.user.id,
            action=action,
            resource_type="robot",
            resource_id=robot.id,
            ip_address=request.remote_addr,
            detail=detail,
        )
    )


def commit_robot_change():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("机器人信息存在冲突，请刷新后重试或更换序列号", 409, 40901) from None


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
        {"serial_no": robot.serial_no, "name": robot.name, "status": robot.status},
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
        field: {"before": getattr(robot, field), "after": value}
        for field, value in values.items()
        if getattr(robot, field) != value
    }
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
