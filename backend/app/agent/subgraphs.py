"""Modular specialist sub-graphs for AgriSense agents.

Isolates domain specialist workflows into compiled StateGraphs with explicit
state passing, preventing global prompt/state leakage.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from .state import OrchestratorState

log = logging.getLogger("agrisense.agent.subgraphs")


def _make_specialist_node(name: str, model: Any, directive_text: str, forced_sequence: list[str] | None = None):
    async def node(state: OrchestratorState):
        messages = state["messages"]
        directive = SystemMessage(content=directive_text)
        
        # Check tool rounds used in this request turn
        used = 0
        for m in messages:
            if isinstance(m, AIMessage) and m.tool_calls:
                if any(not str(tc.get("id") or "").startswith("hist_") for tc in m.tool_calls):
                    used += 1

        active = model
        if forced_sequence and used < len(forced_sequence):
            try:
                active = model.bind_tools(
                    getattr(model, "tools", []),
                    tool_choice=forced_sequence[used]
                )
            except Exception:
                active = model

        response = await active.ainvoke([directive] + list(messages))
        return {"messages": [response], "active_agent": name}

    node.__name__ = f"{name}_subgraph_node"
    return node


def build_specialist_subgraph(
    name: str,
    model: Any,
    tools: list[Any],
    directive_text: str,
    forced_sequence: list[str] | None = None,
):
    """Compile a modular specialist sub-graph with dedicated tool loop."""
    builder = StateGraph(OrchestratorState)
    
    bound_model = model.bind_tools(tools) if tools else model
    agent_node = _make_specialist_node(name, bound_model, directive_text, forced_sequence)
    
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools) if tools else lambda s: s)
    
    builder.add_edge(START, "agent")
    
    def should_continue(state: OrchestratorState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls and tools:
            return "tools"
        return END

    builder.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    if tools:
        builder.add_edge("tools", "agent")
        
    return builder.compile()
