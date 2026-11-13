from copy import deepcopy

import pytest

from app.application.realtime import service
from app.integrations.ai.schemas import ToolRequest

CLOCK = {"now": "2026-11-12T00:00:00+00:00", "timezone": "Asia/Shanghai", "default_location": "宜宾市"}


def test_time_is_server_clock_and_timezone():
    result = service.execute([{"name": "get_local_time"}], CLOCK)[0]
    assert result["status"] == "success"
    assert result["data"]["time"] == "2026-11-12T08:00:00+08:00"
    assert result["source"] == "server_clock"


def test_missing_location_does_not_query_or_ask(app, monkeypatch):
    monkeypatch.setattr(service, "_weather", lambda *args: pytest.fail("no location"))
    result = service.execute([{"name": "get_weather"}], {**CLOCK, "default_location": None})[0]
    assert result["reason"] == "missing_location"


def test_fixture_mismatch_never_calls_network(monkeypatch):
    monkeypatch.setattr(service, "_weather", lambda *args: pytest.fail("fixture cannot call network"))
    with pytest.raises(ValueError, match="未唯一匹配"):
        service.execute([{"name": "get_weather", "location": "上海", "location_source": "question"}], CLOCK, fixtures=[])


def weather_fixture():
    request = ToolRequest(name="get_weather", location="宜宾市").model_dump()
    result = {"status": "success", "location": "宜宾市", "timezone": "Asia/Shanghai", "date": "2026-11-12", "mode": "now",
              "source": "fixture-qweather", "fetched_at": CLOCK["now"], "updated_at": CLOCK["now"],
              "expires_at": "2026-11-12T00:05:00+00:00", "data": {"temp": "18", "text": "晴"}}
    return {"request": request, "result": result}


def test_fixture_exact_normalized_parameters_and_expiry():
    fixture = weather_fixture()
    result = service.execute([{"name": "get_weather"}], CLOCK, fixtures=[fixture])[0]
    assert result["data"]["temp"] == "18" and result["request"]["location"] == "宜宾市"
    expired = deepcopy(fixture)
    expired["result"]["expires_at"] = CLOCK["now"]
    with pytest.raises(ValueError, match="过期"):
        service.execute([{"name": "get_weather"}], CLOCK, fixtures=[expired])


def test_explicit_place_never_becomes_default(app, monkeypatch):
    app.config.update(QWEATHER_HOST="test.qweatherapi.com", QWEATHER_API_KEY="test-only")
    seen = []
    def weather(request, *args):
        seen.append(request["location"])
        return {"status": "error", "reason": "ambiguous_location"}
    monkeypatch.setattr(service, "_weather", weather)
    with app.app_context():
        result = service.execute([{"name": "get_weather", "location": "同名城市", "location_source": "question"}], CLOCK)[0]
    assert seen == ["同名城市"] and result["reason"] == "ambiguous_location"


def test_provider_ambiguity_not_popularity(app, monkeypatch):
    monkeypatch.setattr(service, "_get", lambda *args: {"location": [{"id": "1"}, {"id": "2"}]})
    result = service._weather(ToolRequest(name="get_weather", location="同名城市").model_dump(), service._stamp(CLOCK["now"]), 100)
    assert result["reason"] == "ambiguous_location"


def test_provider_stale_data_rejected(monkeypatch):
    responses = iter([{"location": [{"id": "1", "name": "宜宾", "tz": "Asia/Shanghai"}]},
                      {"now": {"obsTime": "2026-11-11T00:00:00+00:00", "text": "晴", "temp": "18", "feelsLike": "18", "humidity": "50", "precip": "0"}}])
    monkeypatch.setattr(service, "_get", lambda *args: next(responses))
    result = service._weather(ToolRequest(name="get_weather", location="宜宾").model_dump(), service._stamp(CLOCK["now"]), 100)
    assert result["reason"] == "stale"


def test_provider_out_of_range_date_does_not_change_day(monkeypatch):
    calls = []
    def get(*args):
        calls.append(args)
        return {"location": [{"id": "1", "name": "宜宾", "tz": "Asia/Shanghai"}]}
    monkeypatch.setattr(service, "_get", get)
    result = service._weather(ToolRequest(name="get_weather", location="宜宾", date="2026-11-30", mode="daily").model_dump(), service._stamp(CLOCK["now"]), 100)
    assert result["reason"] == "unsupported_date" and len(calls) == 1


def test_tool_allowlist_and_limit():
    with pytest.raises(ValueError):
        service.execute([{"name": "fetch_url"}], CLOCK)
    with pytest.raises(ValueError):
        service.execute([{"name": "get_local_time"}] * 4, CLOCK)


def test_regional_host_and_gzip_response(app, monkeypatch):
    import gzip
    import io
    from time import monotonic
    response = io.BytesIO(gzip.compress(b'{"code":"200","location":[]}'))
    response.headers = {"Content-Encoding": "gzip"}
    class Opener:
        def open(self, request, timeout):
            assert request.full_url.startswith('https://example.re.qweatherapi.com/')
            return response
    monkeypatch.setattr(service, 'build_opener', lambda *a: Opener())
    app.config.update(QWEATHER_HOST='example.re.qweatherapi.com', QWEATHER_API_KEY='test')
    with app.app_context():
        assert service._get('/geo/v2/city/lookup', {}, monotonic() + 5)['code'] == '200'
