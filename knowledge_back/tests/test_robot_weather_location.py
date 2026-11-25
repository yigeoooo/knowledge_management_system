from app.application.qa import workflow
from app.application.realtime import service


def test_robot_weather_prefers_explicit_city_otherwise_binding(monkeypatch):
    captured = []
    def execute(requests, runtime, **kwargs):
        captured.extend(requests)
        assert runtime["default_location"] == "101270101"
        return []
    monkeypatch.setattr(service, "execute", execute)
    for source in ("question", "history", "default"):
        workflow.execute_tools({"robot": True, "runtime": {"default_location": "101270101"},
            "interaction": {"tool_requests": [{"name": "get_weather", "location": "成都", "location_source": source}]}})
    assert captured[0]["location"] == "成都"
    assert captured[0]["location_source"] == "question"
    assert all(r["location"] is None and r["location_source"] == "default" for r in captured[1:])


def test_explicit_other_city_is_not_replaced_by_bound_city(monkeypatch):
    def execute(requests, runtime, **kwargs):
        assert requests[0]["location"] == "北京"
        assert requests[0]["location_source"] == "question"
        assert runtime["default_location"] == "101270101"
        return [{"status": "error", "reason": "ambiguous_location"}]
    monkeypatch.setattr(service, "execute", execute)
    result = workflow.execute_tools({"robot": True, "runtime": {"default_location": "101270101"},
        "interaction": {"tool_requests": [{"name": "get_weather", "location": "北京", "location_source": "question"}]}})
    assert result["tools"][0]["reason"] == "ambiguous_location"
