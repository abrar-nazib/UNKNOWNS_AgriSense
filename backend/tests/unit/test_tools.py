"""Unit tests for the agent's static tools."""
from __future__ import annotations

from datetime import datetime
import inspect

import pytest

from app.agent import tools as tools_mod
from app.agent import runner as runner_mod
from app.agent.tools import build_market_research_tools, build_pest_risk_tool, build_research_tools, calculator, get_current_time

pytestmark = pytest.mark.unit


def _call(tool, **kwargs):
    """Invoke a LangChain @tool with plain kwargs, returning the raw result."""
    return tool.invoke(kwargs)


def test_calculator_basic_arithmetic():
    assert _call(calculator, expression="2+2") == "4"
    assert _call(calculator, expression="10 / 4") == "2.5"
    assert _call(calculator, expression="2 ** 10") == "1024"
    assert _call(calculator, expression="(1 + 2) * 3 - 4") == "5"
    assert _call(calculator, expression="17 % 5") == "2"
    assert _call(calculator, expression="-7 + 2") == "-5"


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('ls')",  # import / call
        "os.system('rm -rf /')",          # attribute/name access
        "open('/etc/passwd').read()",     # builtin call
        "abs(-1)",                         # any function call
        "x + 1",                           # bare name
        "[1,2,3]",                         # list literal (unsupported node)
        "lambda: 1",                       # lambda
    ],
)
def test_calculator_rejects_unsafe_expressions(expr):
    result = _call(calculator, expression=expr)
    # Rejected safely: returns an error string, never executes.
    assert result.startswith("Error:")


def test_get_current_time_returns_iso8601():
    result = _call(get_current_time)
    # Must be parseable as ISO 8601.
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None  # UTC-aware


@pytest.mark.asyncio
async def test_research_tool_factory_returns_untrusted_web_results(monkeypatch):
    async def fake_search_web(query, max_results):
        assert query == "mustard disease"
        assert max_results == 2
        return {
            "source": "DuckDuckGo search",
            "content_trust": "untrusted_external_reference",
            "results": [{"title": "Example", "url": "https://example.test", "snippet": "x"}],
        }

    monkeypatch.setattr(tools_mod.research_mod, "search_web", fake_search_web)
    web_search, _wikipedia = build_research_tools()

    result = await web_search.ainvoke({"query": "mustard disease", "max_results": 2})

    assert '"status": "ok"' in result
    assert '"content_trust": "untrusted_external_reference"' in result


@pytest.mark.asyncio
async def test_research_tool_returns_honest_unavailable_status(monkeypatch):
    async def unavailable(*_args, **_kwargs):
        raise tools_mod.research_mod.ResearchError("Wikipedia is unavailable")

    monkeypatch.setattr(tools_mod.research_mod, "search_wikipedia", unavailable)
    _web_search, wikipedia = build_research_tools()

    result = await wikipedia.ainvoke({"query": "mustard"})

    assert '"status": "RESEARCH_UNAVAILABLE"' in result
    assert "Wikipedia is unavailable" in result


def test_research_tools_are_exposed_to_the_advisor_only():
    """External references are available to advice turns, not planning tools."""
    runner_source = inspect.getsource(runner_mod)

    assert "research_tools = build_research_tools()" in runner_source
    assert '"advisor": static_tools' in runner_source
    assert "+ research_tools" in runner_source


def test_pest_risk_tool_is_exposed_to_advisor_and_planner():
    """Crop-stage risk is traceable in advisory turns and season plans."""
    runner_source = inspect.getsource(runner_mod)

    assert "pest_risk_tool = build_pest_risk_tool(user)" in runner_source
    assert "+ [pest_risk_tool]" in runner_source
    assert "+ [soil_tool, season_plan_tool, pest_risk_tool, financial_tool]" in runner_source
    assert "assess_pest_disease_risk" in inspect.getsource(build_pest_risk_tool)


def test_market_tools_are_exposed_only_to_market_researcher():
    runner_source = inspect.getsource(runner_mod)
    assert "market_tools = build_market_research_tools(user)" in runner_source
    assert '"market_researcher": static_tools + farm_tools + market_tools' in runner_source
    assert {tool.name for tool in build_market_research_tools(None)} == {
        "find_input_suppliers", "analyze_crop_market"
    }
