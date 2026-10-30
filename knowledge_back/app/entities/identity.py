"""Identity and authorization entities."""

from ..core.extensions import db
from .base import Record, now


class Role(Record, db.Model):
    __tablename__ = "roles"
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(30), nullable=False, default="active")
    description = db.Column(db.Text)


class User(Record, db.Model):
    __tablename__ = "users"
    username = db.Column(db.String(100), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    password_plaintext = db.Column(db.String(1024))
    role_id = db.Column(db.Uuid, db.ForeignKey("roles.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="active")
    role = db.relationship(Role)


class Page(Record, db.Model):
    __tablename__ = "pages"
    code = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    route_path = db.Column(db.String(255), unique=True, nullable=False)
    route_name = db.Column(db.String(100), nullable=False)
    component_key = db.Column(db.String(255), nullable=False)
    parent_id = db.Column(db.Uuid, db.ForeignKey("pages.id"))
    page_type = db.Column(db.String(30), nullable=False, default="menu")
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_visible = db.Column(db.Boolean, nullable=False, default=True)
    status = db.Column(db.String(30), nullable=False, default="active")


class RolePagePermission(db.Model):
    __tablename__ = "role_page_permissions"
    role_id = db.Column(db.Uuid, db.ForeignKey("roles.id"), primary_key=True)
    page_id = db.Column(db.Uuid, db.ForeignKey("pages.id"), primary_key=True)
    can_view = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)


class UserSession(Record, db.Model):
    __tablename__ = "user_sessions"
    user_id = db.Column(db.Uuid, db.ForeignKey("users.id"), nullable=False, index=True)
    refresh_token_hash = db.Column(db.String(64), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True))
    user_agent = db.Column(db.Text)
    ip_address = db.Column(db.String(64))


__all__ = ["Page", "Role", "RolePagePermission", "User", "UserSession"]
