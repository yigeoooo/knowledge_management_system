"""Robot management use-case helpers."""

from flask import g, request
from sqlalchemy.exc import IntegrityError

from ...core.errors import ApiError
from ...core.extensions import db
from ...entities import AuditLog
from ...repositories.robot_repository import RobotRepository

ROBOT_STATUSES = {"active", "disabled"}
ROBOT_FIELDS = {"serial_no", "name", "description", "status"}
robot_repository = RobotRepository()

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
    robot = robot_repository.find(robot_id, lock=lock)
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
    existing = robot_repository.find_by_serial(serial_no)
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

