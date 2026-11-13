"""Release coverage comes from executed branches and compiled sections, not model claims."""
import json


def coverage_reasons(run, keys, *, migration=False):
    examples = {e["id"]: e for e in run.snapshot.get("examples", [])}
    records, scenes = [], set()
    for row in run.results:
        output = row.get("candidate", {}).get("outputs", {})
        if row.get("candidate", {}).get("error"):
            continue
        inputs = examples.get(row["id"], {}).get("inputs", {})
        channel = "robot" if inputs.get("robot") else "web"
        kind = output.get("answer_kind")
        compositions = output.get("prompt_compositions", [])
        records.extend(compositions)
        scenes.add(f"{channel}:{kind}")
        if inputs.get("context", {}).get("turns") and "conversation_plan" in (output.get("used_prompt_keys") or []):
            scenes.add("history")
        tools = output.get("tools", [])
        if kind == "realtime":
            if set(output.get("unavailable", [])) & {"missing_location", "missing_timezone"}:
                scenes.add("missing_parameters")
            if any(t.get("status") == "error" for t in tools):
                scenes.add("tool_failure")
            if any(t.get("reason") in {"missing_location", "missing_timezone"} for t in tools):
                scenes.add("missing_parameters")
            if any(r.get("key") == "answer_generate" and set(r.get("evidence", [])) == {"knowledge", "realtime"} for r in compositions):
                scenes.add("mixed")
    reasons = []
    if migration or "conversation_plan" in keys:
        required = {"web:knowledge", "robot:knowledge", "robot:chat", "robot:general", "robot:clarification", "robot:realtime", "history", "mixed", "tool_failure", "missing_parameters"}
        if required - scenes:
            reasons.append("调度验收缺少场景：" + "、".join(sorted(required - scenes)))
    for key in keys:
        candidate = run.snapshot["candidate"].get(key, {})
        baseline = run.snapshot["baseline"].get(key, {})
        try:
            new = json.loads(candidate.get("content", ""))
            old = json.loads(baseline.get("content", ""))
        except ValueError:
            old = {}
            try:
                new = json.loads(candidate.get("content", ""))
            except ValueError:
                continue
        if not isinstance(new, dict) or "sections" not in new:
            continue
        old_sections = old.get("sections", {}) if isinstance(old, dict) else {}
        changed = {s for s in set(new["sections"]) | set(old_sections) if new["sections"].get(s, "") != old_sections.get(s, "")}
        used = [r for r in records if r.get("key") == key]
        # Deleted sections still affect their previous contexts; check context rather than presence.
        for section in changed:
            matches = [r for r in used if section == "common" or section == r.get("channel") or section in r.get("evidence", [])]
            if not matches:
                reasons.append(f"{key} 缺少 {section} 分区实际执行测试")
        if key in {"answer_generate", "review_answer"} and "common" in changed:
            required = {("web", "knowledge"), ("robot", "knowledge"), ("robot", "realtime")}
            actual = {(r.get("channel"), evidence) for r in used for evidence in r.get("evidence", [])}
            if required - actual:
                reasons.append(f"{key} 公共规则需覆盖网页知识、机器人知识和实时回答")
    return reasons
