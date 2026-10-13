"""
대화별 상태가 필요한 MCP tool — 입력 스키마에 session_id 가 있는 tool 은 Coris 가 그 값을 채운다.

LLM 에게 session_id 를 넘기게 하면 틀리거나 지어낼 수 있으므로, LLM 이 보는 스키마에서는 빼고
실행할 때 RunnableConfig 의 configurable.session_id(= 대화 id, agent.stream 이 넣는다)로 채운다.
예: code interpreter 의 run_python — 같은 대화에서 커널(변수)을 이어 쓴다.
"""
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool

SESSION_ARG = "session_id"


def _schema(tool: BaseTool) -> dict:
    s = tool.args_schema
    if s is None:
        return {}
    return s if isinstance(s, dict) else s.model_json_schema()


def wrap(tool: BaseTool) -> BaseTool:
    schema = _schema(tool)
    props = schema.get("properties") or {}
    if SESSION_ARG not in props:
        return tool
    visible = {
        **schema,
        "properties": {k: v for k, v in props.items() if k != SESSION_ARG},
        "required": [r for r in schema.get("required") or [] if r != SESSION_ARG],
    }

    async def _arun(config: RunnableConfig, **kwargs):
        sid = (config.get("configurable") or {}).get(SESSION_ARG) or "default"
        return await tool.ainvoke({**kwargs, SESSION_ARG: sid})

    return StructuredTool(name=tool.name, description=tool.description, args_schema=visible, coroutine=_arun)


def wrap_all(tools: dict[str, BaseTool]) -> dict[str, BaseTool]:
    return {name: wrap(t) for name, t in tools.items()}
