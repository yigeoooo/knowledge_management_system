"""SQLAlchemy queries for users, roles, and authorization records."""

from ..core.extensions import db
from ..entities import Role, User


class UserRepository:
    """Persistence seam for user lookup used by authentication and management."""

    @staticmethod
    def find(user_id, *, lock=False):
        query = db.select(User).where(User.id == user_id, User.status != "deleted")
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return db.session.scalar(query)

    @staticmethod
    def find_by_username(username):
        return db.session.scalar(
            db.select(User).where(User.username == username, User.status != "deleted")
        )

    @staticmethod
    def find_any_by_username(username):
        return db.session.scalar(db.select(User).where(User.username == username))


class RoleRepository:
    """Persistence seam for role lookup."""

    @staticmethod
    def find(role_id, *, lock=False):
        query = db.select(Role).where(Role.id == role_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return db.session.scalar(query)

    @staticmethod
    def find_by_code(code):
        return db.session.scalar(db.select(Role).where(Role.code == code))
