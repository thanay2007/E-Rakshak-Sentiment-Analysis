"""SENTINEL's assistant — the voice channel's brain, kept out of the router.

The router does transport: authenticate, rate-limit, audit, serialise. This
package does everything else, in four layers that are meant to be read in this
order:

    guard      what the voice channel refuses outright, and how text written
               by monitored accounts is neutralised before a model sees it
    tools      every lookup the assistant can perform, each rank-gated, none
               of which writes
    sandbox    the read-only SQL window, for the questions no fixed tool has a
               parameter for
    knowledge  the product's own documentation, so "how does the threat score
               work" has a grounded answer
    rules      the deterministic fast path for the nine questions people
               actually ask, which works with no model available
    agent      the tool-calling loop for everything else

The security argument for letting a language model near a police dashboard is
simply that it never gets near it: the model's entire reach is `tools.TOOLS`
filtered by rank, and nothing in that list mutates.
"""
from app.services.assistant import (agent, guard, knowledge, rules, sandbox,  # noqa: F401
                                    tools)
from app.services.assistant.agent import AgentAnswer, answer  # noqa: F401
from app.services.assistant.tools import ToolContext  # noqa: F401

__all__ = ["agent", "guard", "knowledge", "rules", "sandbox", "tools",
           "AgentAnswer", "ToolContext", "answer"]
