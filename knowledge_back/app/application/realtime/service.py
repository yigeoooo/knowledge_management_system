"""Bounded tools with exact fixtures and server-owned provenance, never arbitrary URLs."""
import gzip
import io
import json
import re
from datetime import UTC, datetime, timedelta
from time import monotonic
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from flask import current_app

from ...integrations.ai.schemas import ToolRequest

VERSION = "weather-time-v1"
MESSAGES = {
    "unsupported": "暂不支持查询这类实时信息。",
    "missing_location": "尚未配置可用地点，暂时无法查询天气。",
    "missing_timezone": "尚未配置可用时区，暂时无法确认当地时间。",
    "ambiguous_location": "地点存在歧义，暂时无法确认天气。",
    "unsupported_date": "暂时查不到所选日期的天气。",
    "unavailable": "实时服务暂不可用，暂时无法确认查询结果。",
    "stale": "查询结果已过期，暂时无法确认最新情况。",
}


def runtime(default_location=None, timezone=None):
    return {"now": datetime.now(UTC).isoformat(), "default_location": default_location,
            "timezone": timezone, "tool_version": VERSION}


def capabilities(fixture=False):
    return {"version": VERSION, "tools": ["get_local_time"] + (
        ["get_weather"] if fixture or (current_app.config.get("QWEATHER_HOST") and
                                      current_app.config.get("QWEATHER_API_KEY")) else []),
            "max_requests": 3, "weather_days": 3, "weather_modes": ["now", "daily"]}


def _stamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("timezone required")
    return stamp


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(path, params, deadline):
    host = current_app.config.get("QWEATHER_HOST", "")
    if not re.fullmatch(r"[a-zA-Z0-9-]+(?:\.re)?\.qweatherapi\.com", host):
        raise ValueError("weather host not configured")
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError()
    req = Request(f"https://{host}{path}?{urlencode(params)}", headers={
        "X-QW-Api-Key": current_app.config["QWEATHER_API_KEY"], "Accept": "application/json"})
    with build_opener(_NoRedirect()).open(req, timeout=min(4, remaining)) as response:
        payload = response.read(262145)
        if len(payload) > 262144:
            raise ValueError("response too large")
        if response.headers.get("Content-Encoding", "").lower() == "gzip" or payload[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
                payload = compressed.read(262145)
            if len(payload) > 262144:
                raise ValueError("response too large")
        result = json.loads(payload)
    if result.get("code") != "200":
        raise ValueError("provider unavailable")
    return result


def _weather(request, clock, deadline):
    locations = _get("/geo/v2/city/lookup", {"location": request["location"], "number": 10}, deadline).get("location", [])
    # Never pick the first popular result when the provider returns several places.
    if len(locations) != 1:
        return {"status": "error", "reason": "ambiguous_location"}
    place = locations[0]
    zone = ZoneInfo(place["tz"])
    today = clock.astimezone(zone).date()
    day = datetime.fromisoformat(request["date"]).date() if request.get("date") else today
    if (request["mode"] == "now" and day != today) or not 0 <= (day - today).days < 3:
        return {"status": "error", "reason": "unsupported_date"}
    payload = _get("/v7/weather/now" if request["mode"] == "now" else "/v7/weather/3d",
                   {"location": place["id"], "unit": "m", "lang": "zh"}, deadline)
    if request["mode"] == "now":
        raw = payload["now"]
        updated = _stamp(raw["obsTime"])
        data = {key: raw[key] for key in ("text", "temp", "feelsLike", "humidity", "precip")}
    else:
        raw = next((d for d in payload["daily"] if d["fxDate"] == day.isoformat()), None)
        if raw is None:
            return {"status": "error", "reason": "unsupported_date"}
        updated = _stamp(payload["updateTime"])
        data = {key: raw[key] for key in ("textDay", "textNight", "tempMax", "tempMin", "precip")}
    lifetime = timedelta(minutes=30) if request["mode"] == "now" else timedelta(hours=12)
    if updated > clock + timedelta(minutes=5) or clock - updated > lifetime:
        return {"status": "error", "reason": "stale"}
    return {"status": "success", "location": place["name"], "location_id": place["id"],
            "timezone": place["tz"], "date": day.isoformat(), "mode": request["mode"],
            "updated_at": updated.isoformat(), "expires_at": min(updated + lifetime, clock + timedelta(minutes=5)).isoformat(),
            "units": {"temperature": "°C", "precipitation": "mm", "humidity": "%"},
            "source": "qweather", "data": data}


def _execute(requests, context, *, fixtures=None, deadline=None):
    """Fixtures are exact request/result pairs. A miss is a test failure, never a live fallback."""
    if len(requests) > 3:
        raise ValueError("too many tool requests")
    clock = _stamp(context["now"])
    deadline = deadline or monotonic() + 15
    results = []
    for value in requests:
        request = ToolRequest.model_validate(value).model_dump()
        if request["location_source"] == "default":
            request["location"] = context.get("default_location")
        start = monotonic()
        result = None
        if request["name"] == "get_weather" and not request["location"]:
            result = {"status": "error", "reason": "missing_location"}
        elif request["name"] == "get_local_time" and not (request["timezone"] or context.get("timezone")):
            result = {"status": "error", "reason": "missing_timezone"}
        elif fixtures is not None:
            matches = [f["result"] for f in fixtures if f["request"] == request]
            if len(matches) != 1:
                raise ValueError("实时样本参数未唯一匹配")
            result = dict(matches[0])
            if result.get("status") == "success":
                if _stamp(result["expires_at"]) <= clock or _stamp(result["fetched_at"]) > clock:
                    raise ValueError("实时样本已过期或来自未来")
                if not all(result.get(k) for k in ("source", "data", "timezone", "date")):
                    raise ValueError("实时样本缺少证据元数据")
        elif request["name"] == "get_local_time":
            zone = request["timezone"] or context.get("timezone")
            if not zone:
                result = {"status": "error", "reason": "missing_timezone"}
            else:
                try:
                    local = clock.astimezone(ZoneInfo(zone))
                    result = {"status": "success", "timezone": zone, "date": local.date().isoformat(),
                              "source": "server_clock", "data": {"time": local.isoformat()},
                              "updated_at": clock.isoformat(), "expires_at": (clock + timedelta(seconds=60)).isoformat()}
                except (ValueError, KeyError):
                    result = {"status": "error", "reason": "missing_timezone"}
        elif "get_weather" not in capabilities()["tools"]:
            result = {"status": "error", "reason": "unavailable"}
        else:
            try:
                result = _weather(request, clock, deadline)
            except (OSError, ValueError, KeyError, TypeError):
                # Provider bodies/URLs/headers never enter model input or ordinary logs.
                result = {"status": "error", "reason": "unavailable"}
        results.append({**result, "tool": request["name"], "request": request,
                        "fetched_at": result.get("fetched_at", clock.isoformat()),
                        "duration_ms": round((monotonic() - start) * 1000), "cache_hit": False})
    return results


def execute(requests, context, *, fixtures=None):
    from langchain_core.tools import StructuredTool
    if len(requests) > 3:
        raise ValueError("too many tool requests")
    deadline = monotonic() + 15
    results = []
    for value in requests:
        request = ToolRequest.model_validate(value)
        def run(**arguments):
            return _execute([arguments], context, fixtures=fixtures, deadline=deadline)[0]
        tool = StructuredTool.from_function(run, name=request.name, args_schema=ToolRequest,
                                            description="执行服务端允许的天气或时间查询。")
        results.append(tool.invoke(request.model_dump()))
    return results
