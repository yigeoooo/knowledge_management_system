from types import SimpleNamespace

from app.application.prompts.composition import encode_sections
from app.application.prompts.coverage import coverage_reasons


def test_weather_rules_cannot_be_released_from_a_greeting():
    run = SimpleNamespace(snapshot={'examples': [{'id': '1', 'inputs': {'robot': True}}],
         'baseline': {'answer_generate': {'content': encode_sections({'common': '事实', 'realtime': '旧时效'})}},
         'candidate': {'answer_generate': {'content': encode_sections({'common': '事实', 'realtime': '新时效'})}}},
         results=[{'id': '1', 'candidate': {'outputs': {'answer_kind': 'chat', 'used_prompt_keys': ['conversation_plan'], 'prompt_compositions': []}}}])
    assert any('realtime' in reason for reason in coverage_reasons(run, {'answer_generate'}))


def test_robot_only_expression_change_does_not_require_web_generation():
    run = SimpleNamespace(snapshot={'examples': [{'id': '1', 'inputs': {'robot': True}}],
         'baseline': {'answer_generate': {'content': encode_sections({'common': '事实', 'robot': '旧格式'})}},
         'candidate': {'answer_generate': {'content': encode_sections({'common': '事实', 'robot': '新格式'})}}},
         results=[{'id': '1', 'candidate': {'outputs': {'answer_kind': 'knowledge', 'prompt_compositions': [
             {'key': 'answer_generate', 'channel': 'robot', 'evidence': ['knowledge'], 'sections': ['common', 'robot']}]}}}])
    assert coverage_reasons(run, {'answer_generate'}) == []
