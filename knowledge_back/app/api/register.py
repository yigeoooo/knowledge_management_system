"""Register all HTTP interface modules on a Flask application."""

from flask import Flask

from .auth.controller import auth
from .documents.controller import documents
from .qa.controller import qa
from .retrieval.controller import retrieval
from .robots.controller import robots
from .roles.controller import roles
from .users.controller import users
from .workspace.controller import workspace


def register_blueprints(app: Flask) -> None:
    """Attach the public route modules in one explicit place."""

    for blueprint in (auth, documents, qa, roles, retrieval, robots, workspace, users):
        app.register_blueprint(blueprint)


__all__ = ["register_blueprints"]
