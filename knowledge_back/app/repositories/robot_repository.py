"""SQLAlchemy queries for registered robots."""

from ..core.extensions import db
from ..entities import Robot


class RobotRepository:
    """Persistence seam for robot lookup."""

    @staticmethod
    def find(robot_id, *, lock=False):
        query = db.select(Robot).where(Robot.id == robot_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return db.session.scalar(query)

    @staticmethod
    def find_by_serial(serial_no):
        return db.session.scalar(db.select(Robot).where(Robot.serial_no == serial_no))
