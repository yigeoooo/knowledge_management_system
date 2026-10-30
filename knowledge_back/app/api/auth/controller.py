import secrets
from datetime import timedelta
from functools import wraps
from uuid import UUID

import jwt
from argon2.exceptions import VerificationError
from flask import Blueprint, current_app, g, request

from ...core.extensions import db, limiter
from ...core.http import ApiError, success
from ...entities import AuditLog, User, UserSession, now
from ...security.password import dummy_hash as _dummy_hash
from ...security.password import password_hasher
from ...security.permissions import ensure_active, identity, require_page_access
from ...security.token import token_hash

auth = Blueprint("auth", __name__, url_prefix="/api/v1/auth")
COOKIE_NAME = "kbs_refresh"
COOKIE_PATH = "/api/v1/auth"





def page_required(*paths):
    def decorate(view):
        @authenticated
        @wraps(view)
        def wrapped(*args, **kwargs):
            require_page_access(*paths)
            return view(*args, **kwargs)

        return wrapped

    return decorate




def issue_response(user, session, refresh_token):
    seconds = current_app.config["ACCESS_TOKEN_SECONDS"]
    token = jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(session.id),
            "type": "access",
            "iat": now(),
            "exp": now() + timedelta(seconds=seconds),
            "iss": "dexforce-knowledge",
            "aud": "knowledge-web",
        },
        current_app.config["JWT_SECRET_KEY"],
        algorithm="HS256",
    )
    response = success({**identity(user), "access_token": token, "expires_in": seconds})
    response.set_cookie(
        COOKIE_NAME,
        refresh_token,
        httponly=True,
        secure=current_app.config["SESSION_COOKIE_SECURE"],
        samesite="Strict",
        max_age=current_app.config["REFRESH_TOKEN_DAYS"] * 86400,
        path=COOKIE_PATH,
    )
    return response


def authenticated(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        try:
            if not header.startswith("Bearer "):
                raise ValueError()
            payload = jwt.decode(
                header[7:],
                current_app.config["JWT_SECRET_KEY"],
                algorithms=["HS256"],
                issuer="dexforce-knowledge",
                audience="knowledge-web",
                options={"require": ["exp", "iat", "sub", "sid", "type"]},
            )
            if payload["type"] != "access":
                raise ValueError()
            session = db.session.scalar(
                db.select(UserSession).where(
                    UserSession.id == UUID(payload["sid"]),
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now(),
                    UserSession.user_id == UUID(payload["sub"]),
                )
            )
            if not session:
                raise ValueError()
        except (jwt.InvalidTokenError, ValueError, TypeError):
            raise ApiError("登录已失效，请重新登录", 401, 40101) from None
        g.user = db.session.get(User, session.user_id)
        ensure_active(g.user)
        g.auth_session = session
        return view(*args, **kwargs)

    return wrapped


@auth.post("/login")
@limiter.limit("10 per minute")
def login():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError("请输入用户名和密码", 422)
    username, password = body.get("username"), body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ApiError("请输入用户名和密码", 422)
    if not 1 <= len(username.strip()) <= 100 or not 1 <= len(password) <= 1024:
        raise ApiError("用户名或密码格式不正确", 422)
    user = db.session.scalar(
        db.select(User).where(User.username == username.strip(), User.status != "deleted")
    )
    try:
        password_hasher.verify(user.password_hash if user else _dummy_hash, password)
    except VerificationError:
        raise ApiError("用户名或密码错误", 401, 40101) from None
    ensure_active(user)
    refresh_token = secrets.token_urlsafe(48)
    session = UserSession(
        user_id=user.id,
        refresh_token_hash=token_hash(refresh_token),
        expires_at=now() + timedelta(days=current_app.config["REFRESH_TOKEN_DAYS"]),
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string[:500],
    )
    db.session.add(session)
    db.session.add(
        AuditLog(
            user_id=user.id,
            action="auth.login",
            resource_type="user",
            resource_id=user.id,
            ip_address=request.remote_addr,
        )
    )
    db.session.commit()
    return issue_response(user, session, refresh_token)


@auth.get("/me")
@authenticated
def me():
    return success(identity(g.user))


@auth.post("/refresh")
@limiter.limit("60 per minute")
def refresh():
    # JSON requests require CORS preflight; no cross-origin CORS is enabled.
    if not request.is_json or request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise ApiError("不允许跨站刷新会话", 403, 40301)
    token = request.cookies.get(COOKIE_NAME, "")
    session = db.session.scalar(
        db.select(UserSession)
        .where(
            UserSession.refresh_token_hash == token_hash(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now(),
        )
        .with_for_update()
    )
    if not session:
        raise ApiError("登录已失效，请重新登录", 401, 40101)
    user = db.session.get(User, session.user_id)
    ensure_active(user)
    refresh_token = secrets.token_urlsafe(48)
    session.refresh_token_hash = token_hash(refresh_token)
    db.session.commit()
    return issue_response(user, session, refresh_token)


@auth.post("/logout")
@authenticated
def logout():
    g.auth_session.revoked_at = now()
    db.session.add(
        AuditLog(
            user_id=g.user.id,
            action="auth.logout",
            resource_type="user",
            resource_id=g.user.id,
            ip_address=request.remote_addr,
        )
    )
    db.session.commit()
    response = success()
    response.delete_cookie(
        COOKIE_NAME,
        path=COOKIE_PATH,
        secure=current_app.config["SESSION_COOKIE_SECURE"],
        httponly=True,
        samesite="Strict",
    )
    return response
