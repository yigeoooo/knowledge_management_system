from flask import g, jsonify, request


class ApiError(Exception):
    def __init__(self, message, status=400, code=42201):
        self.message, self.status, self.code = message, status, code


def success(data=None):
    return jsonify(code=0, message="ok", data=data or {}, request_id=g.request_id)


def status_filter():
    """Treat cleared status selectors (including legacy serialized nulls) as no filter."""
    value = request.args.get("status", "").strip()
    return "" if value in {"undefined", "null"} else value
