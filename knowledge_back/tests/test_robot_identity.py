from app.application.prompts.registry import robot_prompt
from app.application.robots.identity import fallback_text, identity_scope


def test_device_name_is_scoped_and_does_not_mutate_published_prompt():
    original = robot_prompt('robot_interaction')
    with identity_scope('W1导览机器人'):
        prompt = robot_prompt('robot_interaction')
        assert '"robot_name": "W1导览机器人"' in prompt
        assert fallback_text('小维暂时无法确认。') == 'W1导览机器人暂时无法确认。'
        with identity_scope('W2导览机器人'):
            assert '"robot_name": "W2导览机器人"' in robot_prompt('robot_interaction')
        assert '"robot_name": "W1导览机器人"' in robot_prompt('robot_interaction')
    assert robot_prompt('robot_interaction') == original
