"""Bounded LangSmith v2 reads, including agent/environment destinations."""
from itertools import islice

from langsmith import Langsmith

FIELDS = ["ID", "NAME", "RUN_TYPE", "STATUS", "START_TIME", "END_TIME", "ERROR",
          "INPUTS", "OUTPUTS", "PARENT_RUN_IDS", "TRACE_ID", "DOTTED_ORDER",
          "TOTAL_TOKENS", "PROMPT_TOKENS", "COMPLETION_TOKENS"]


def destination(config):
    if config.get("LANGSMITH_AGENT_ID"):
        return {"kind": "AGENT", "id": config["LANGSMITH_AGENT_ID"],
                "environment": config["LANGSMITH_AGENT_ENVIRONMENT"].upper()}
    return {"project_name": config["LANGSMITH_PROJECT"]}


def read_run_tree(config, tracing_client, local, limit):
    address = local.get("destination") or destination(config)
    with Langsmith(api_key=config["LANGSMITH_API_KEY"], base_url=config["LANGSMITH_ENDPOINT"],
                   max_retries=0, timeout=5) as reader:
        if "project_name" in address:
            project_id = str(tracing_client.read_project(project_name=address["project_name"]).id)
        else:
            project_id = reader.sessions.resolve(**address).session_id
        # Query by persisted trace ID, with bounded pagination. v1 read_run cannot
        # find traces stored in newer agent/environment SmithDB destinations.
        records = reader.runs.query(project_ids=[project_id], trace_id=local["run_id"],
                                    page_size=100, selects=FIELDS)
        return list(islice(records, limit + 1))
