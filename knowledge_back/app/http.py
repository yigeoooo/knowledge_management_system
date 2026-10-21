from flask import g, jsonify


class ApiError(Exception):
    def __init__(self, message, status=400, code=42201):
        self.message, self.status, self.code = message, status, code


def success(data=None):
    return jsonify(code=0, message="ok", data=data or {}, request_id=g.request_id)
