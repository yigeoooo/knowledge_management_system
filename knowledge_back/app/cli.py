import click

from .auth import password_hasher
from .extensions import db
from .models import AuditLog, Role, User


def register_cli(app):
    @app.cli.command("set-password")
    @click.option("--username", required=True)
    @click.password_option(confirmation_prompt=True)
    def set_password(username, password):
        from .models import UserSession, now

        user = db.session.scalar(
            db.select(User).where(User.username == username, User.status != "deleted")
        )
        if user is None or not 12 <= len(password) <= 1024:
            raise click.ClickException("用户不存在或密码长度不在 12–1024 字符范围内。")
        user.password_hash = password_hasher.hash(password)
        user.password_plaintext = password
        db.session.execute(
            db.update(UserSession).where(UserSession.user_id == user.id).values(revoked_at=now())
        )
        db.session.add(
            AuditLog(
                user_id=user.id,
                action="user.password_changed",
                resource_type="user",
                resource_id=user.id,
                detail={"source": "cli"},
            )
        )
        db.session.commit()
        click.echo("密码已更新，现有会话已撤销。")

    @app.cli.command("create-user")
    @click.option("--username", prompt=True)
    @click.option("--role", type=click.Choice(["user", "super_admin"]), default="user")
    @click.password_option(confirmation_prompt=True)
    def create_user(username, role, password):
        """Create an account without a default or command-line password."""
        username = username.strip()
        if not 1 <= len(username) <= 100 or not 12 <= len(password) <= 1024:
            raise click.ClickException("用户名需为 1–100 字符，密码需为 12–1024 字符。")
        role_record = db.session.scalar(db.select(Role).where(Role.code == role))
        if role_record is None:
            raise click.ClickException("请先通过项目根目录 init.sql 初始化数据库。")
        if db.session.scalar(db.select(User).where(User.username == username)):
            raise click.ClickException("用户名已存在。")
        user = User(
            username=username,
            display_name=username,
            role_id=role_record.id,
            password_hash=password_hasher.hash(password),
            password_plaintext=password,
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(
            AuditLog(
                user_id=user.id,
                action="user.create",
                resource_type="user",
                resource_id=user.id,
                detail={"source": "cli", "role": role},
            )
        )
        db.session.commit()
        click.echo(f"用户 {username} 已创建。")
