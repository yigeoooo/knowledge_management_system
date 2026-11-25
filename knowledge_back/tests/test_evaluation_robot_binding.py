import pytest

from app.api.evaluations.controller import validate_example
from app.core.extensions import db
from app.core.http import ApiError
from app.entities import EvaluationDataset, KnowledgeBase, Robot


def test_annotation_records_robot_context_and_rejects_invalid_binding(app):
    with app.app_context():
        base = db.session.scalar(db.select(KnowledgeBase))
        dataset = EvaluationDataset(name='机器人标注', knowledge_base_id=base.id)
        robot = Robot(serial_no='eval-w1', name='W1导览机器人', knowledge_base_id=base.id,
                      default_location='101270101', default_location_name='成都市', timezone='Asia/Shanghai')
        db.session.add_all([dataset, robot]); db.session.commit()
        data = {'name': '当地时间', 'inputs': {'question': '现在几点', 'robot': True, 'robot_id': str(robot.id)},
                'reference': {}}
        _, inputs, _ = validate_example(data, dataset)
        assert inputs['robot_context']['name'] == 'W1导览机器人'
        assert inputs['robot_context']['default_location_name'] == '成都市'
        assert inputs['realtime']['runtime']['default_location'] == '101270101'
        assert inputs['realtime']['runtime']['timezone'] == 'Asia/Shanghai'
        robot.timezone = 'Asia/Tokyo'
        assert inputs['realtime']['runtime']['timezone'] == 'Asia/Shanghai'
        robot.status = 'disabled'
        with pytest.raises(ApiError):
            validate_example(data, dataset)
        data['inputs'].pop('robot_id')
        with pytest.raises(ApiError):
            validate_example(data, dataset)
