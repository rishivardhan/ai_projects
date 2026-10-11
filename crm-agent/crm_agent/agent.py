"""Step 6 - The agentic layer.

``CRMAgent`` runs Claude in a tool-use loop over the registry from step 5:

    user message
      -> Claude decides: answer directly, call CRM tools, and/or retrieve (RAG)
      -> tools run locally against the NoSQL DB / retriever (writes need approval)
      -> results go back to Claude -> repeat until Claude ends its turn

The loop is written out by hand (rather than using the SDK's beta tool runner) so
every step can be streamed to the UI as an ``AgentEvent`` and so writes can be
gated. RAG is "as needed": retrieval is just another tool (``search_knowledge``),
so Claude only retrieves when the question calls for documents or notes. Deal
judgments come from the decision model tools (``score_deal``, ``prioritize_deals``,
``request_discount``), which the system prompt makes authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator

import anthropic

from .config import settings as default_settings
from .tools.crm_tools import registry as default_registry
from .tools.registry import ToolContext, ToolRegistry

SYSTEM_PROMPT = """\
You are CRM Copilot, an assistant embedded in Northwind Cloud's CRM. Northwind Cloud sells a cloud data
platform (Core Platform, Analytics Add-on, AI Assist, Data Connectors Pack, Premium Support) to businesses.
Your users are sales reps, sales managers and customer success managers.

How to work:
- Ground every factual statement about accounts, contacts, deals, leads, tasks or interactions in tool
  results. Never invent records, numbers, names or dates; if the data isn't there, say so.
- Use the structured tools for records and numbers (search_accounts, get_account_360, list_opportunities,
  pipeline_summary, search_leads, get_interactions, list_tasks ...). Use search_knowledge for company
  policy, pricing, product and playbook questions, and to find interaction notes by topic. Combine both
  when giving advice (e.g. look up the deal, then the discount policy that applies to it).
- Call several independent tools in parallel when you can.
- Refer to records by name and ID (e.g. "Globex Financial (ACC-002)", "OPP-014"). When you rely on the
  knowledge base, name the document section you used.
- A trained decision model is the deciding factor for deal judgments. For a deal's likelihood to
  close, risk, prioritization or what to focus on, call score_deal or prioritize_deals and present the
  model's win probability, action and factors - never estimate probabilities yourself, and don't
  contradict its decision (you may add context from notes or policy). Discounts can only be granted via
  request_discount, whose APPROVE / ESCALATE / REJECT outcome is final; relay it with its reason and any
  counter-offer. The CRM "probability" field is just the stage default, not the model's estimate.
- Write actions (logging interactions, updating deals or leads, creating/completing tasks, converting
  leads) change shared data. Only perform them when the user asked for that change or clearly agreed to
  your proposal. The application asks the user to approve each write; if one is declined, don't retry it.
- Money is in USD. Format amounts like $125,000. Keep answers concise and skimmable: short paragraphs,
  bullet lists or small tables, and end with concrete next steps when giving advice."""


@dataclass
class AgentEvent:
    type: str  # thinking | text | tool_call | tool_result | notice | error | done
    data: dict = field(default_factory=dict)


class CRMAgent:
    def __init__(self, ctx: ToolContext, client: Any | None = None, registry: ToolRegistry | None = None,
                 settings=default_settings):
        self.ctx = ctx
        self.registry = registry or default_registry
        self.settings = settings
        self._client = client  # created lazily so tools/RAG work without an API key
        self.messages: list[dict] = []
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    # -- request construction ------------------------------------------------------------
    def _system(self) -> list[dict]:
        today = datetime.now().strftime("%A %Y-%m-%d")
        return [
            # Stable prefix (tools + this block) is cached across turns and sessions.
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"Today is {today}. The current user is {self.ctx.user}."},
        ]

    def _request(self) -> dict:
        req = dict(
            model=self.settings.model,
            max_tokens=self.settings.max_tokens,
            system=self._system(),
            tools=self.registry.schemas(),
            messages=self.messages,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": self.settings.effort},
        )
        if self.settings.fallbacks:
            # Server-side refusal fallback: if a safety classifier declines, the API re-runs the
            # request on an appropriate fallback model instead of returning a refusal.
            req.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        return req

    def _call_model(self):
        response = self.client.beta.messages.create(**self._request())
        usage = getattr(response, "usage", None)
        for key in self.usage:
            self.usage[key] += getattr(usage, key, 0) or 0
        return response

    # -- the loop ------------------------------------------------------------------------
    def chat(self, user_text: str) -> Iterator[AgentEvent]:
        """Run one user turn, yielding events as the agent thinks, calls tools and answers."""
        turn_start = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        final_text: list[str] = []
        tool_calls = 0

        for _step in range(self.settings.max_agent_steps):
            try:
                response = self._call_model()
            except TypeError:  # raised by the SDK when no credentials are configured
                yield from self._abort(turn_start, "No Claude API credentials found. Set ANTHROPIC_API_KEY "
                                                  "(see .env.example) and restart.")
                return
            except anthropic.AuthenticationError:
                yield from self._abort(turn_start, "Authentication failed - set ANTHROPIC_API_KEY.")
                return
            except anthropic.RateLimitError:
                yield from self._abort(turn_start, "Rate limited by the API - wait a moment and retry.")
                return
            except anthropic.BadRequestError as e:
                yield from self._abort(turn_start, f"Bad request: {e.message}")
                return
            except anthropic.APIStatusError as e:
                yield from self._abort(turn_start, f"API error {e.status_code}: {e.message}")
                return
            except anthropic.APIConnectionError:
                yield from self._abort(turn_start, "Could not reach the Claude API (network error).")
                return

            if response.stop_reason == "refusal":
                details = getattr(response, "stop_details", None)
                reason = getattr(details, "explanation", None) or "the request was declined"
                yield from self._abort(turn_start, f"Claude declined this request: {reason}")
                return

            # Append the full content (thinking + tool_use blocks included) - required for tool use.
            self.messages.append({"role": "assistant", "content": response.content})

            tool_uses = []
            for block in response.content:
                btype = getattr(block, "type", None)
                if btype == "thinking" and getattr(block, "thinking", ""):
                    yield AgentEvent("thinking", {"text": block.thinking})
                elif btype == "text" and block.text:
                    final_text.append(block.text)
                    yield AgentEvent("text", {"text": block.text})
                elif btype == "tool_use":
                    tool_uses.append(block)
                elif btype == "fallback":
                    yield AgentEvent("notice", {"text": "Request was re-routed to a fallback model."})

            if response.stop_reason == "tool_use" and tool_uses:
                results = []
                for block in tool_uses:
                    tool_calls += 1
                    args = dict(block.input) if isinstance(block.input, dict) else {}
                    yield AgentEvent("tool_call", {"id": block.id, "name": block.name, "input": args,
                                                   "mutating": block.name in self.registry
                                                   and self.registry.get(block.name).mutating})
                    result = self.registry.execute(self.ctx, block.id, block.name, args)
                    yield AgentEvent("tool_result", {"id": block.id, "name": block.name,
                                                     "is_error": result.is_error, "output": result.output,
                                                     "duration_ms": result.duration_ms})
                    results.append(result.to_block())
                # All results for one assistant turn go back in a single user message.
                self.messages.append({"role": "user", "content": results})
                continue

            if response.stop_reason == "pause_turn":
                continue  # server paused a long turn; re-send to let it continue
            if response.stop_reason == "max_tokens":
                yield AgentEvent("notice", {"text": "Response was cut off at the token limit."})
            break
        else:
            self.messages.append({"role": "assistant", "content": "(Stopped: reached the tool-step limit.)"})
            yield AgentEvent("notice", {"text": f"Stopped after {self.settings.max_agent_steps} steps."})

        yield AgentEvent("done", {"text": "\n\n".join(final_text), "tool_calls": tool_calls,
                                  "usage": dict(self.usage)})

    def _abort(self, turn_start: int, message: str) -> Iterator[AgentEvent]:
        # Roll back the partial turn so the conversation history stays valid for the next turn.
        del self.messages[turn_start:]
        yield AgentEvent("error", {"text": message})
        yield AgentEvent("done", {"text": "", "tool_calls": 0, "usage": dict(self.usage)})

    def ask(self, user_text: str) -> str:
        """Convenience: run a turn and return only the final answer text."""
        answer = ""
        for event in self.chat(user_text):
            if event.type == "done":
                answer = event.data["text"]
            elif event.type == "error":
                answer = event.data["text"]
        return answer

    def reset(self) -> None:
        self.messages.clear()


# ---------------------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------------------
_retriever = None


def get_retriever(db):
    global _retriever
    if _retriever is None or _retriever.db is not db:
        from .rag.index import Retriever

        _retriever = Retriever(db)
    return _retriever


def build_context(user: str = "CRM User", approve=None, db=None) -> ToolContext:
    from . import db as dbmod

    db = db if db is not None else dbmod.get_db()
    return ToolContext(
        db=db,
        retriever=get_retriever(db),
        user=user,
        approve=approve or (lambda name, args: True),
        on_write=lambda: dbmod.save_snapshot(db),
    )


def build_agent(user: str = "CRM User", approve=None, client=None) -> CRMAgent:
    return CRMAgent(build_context(user=user, approve=approve), client=client)
