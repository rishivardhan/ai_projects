"""Step 7a - Terminal interface.

    python -m crm_agent.cli                     # interactive chat
    python -m crm_agent.cli --ask "question"    # one-shot
    python -m crm_agent.cli --auto-approve      # don't prompt before write actions

Commands inside the chat:
    /tools                 list available tools
    /tool NAME {json}      call a tool directly (works without an API key)
    /reset                 start a new conversation
    /usage                 token usage so far
    /quit
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap

from .agent import build_agent
from .db import backend_name
from .tools.registry import to_json

DIM, BOLD, CYAN, YELLOW, RED, GREEN, RESET = ("\033[2m", "\033[1m", "\033[36m", "\033[33m", "\033[31m",
                                              "\033[32m", "\033[0m")
if not sys.stdout.isatty():
    DIM = BOLD = CYAN = YELLOW = RED = GREEN = RESET = ""


def _short(obj, width=160) -> str:
    text = obj if isinstance(obj, str) else to_json(obj)
    return text if len(text) <= width else text[: width - 3] + "..."


def _prompt_approval(name: str, args: dict) -> bool:
    print(f"\n{YELLOW}⚠ Write action requested: {BOLD}{name}{RESET}")
    print(textwrap.indent(json.dumps(args, indent=2, default=str), "    "))
    try:
        return input(f"{YELLOW}  Approve? [y/N] {RESET}").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def run_turn(agent, text: str, verbose: bool = True) -> None:
    for ev in agent.chat(text):
        if ev.type == "thinking" and verbose:
            print(f"{DIM}💭 {_short(ev.data['text'].strip(), 300)}{RESET}")
        elif ev.type == "tool_call":
            print(f"{CYAN}🔧 {ev.data['name']}({_short(ev.data['input'], 140)}){RESET}")
        elif ev.type == "tool_result" and verbose:
            colour = RED if ev.data["is_error"] else DIM
            print(f"{colour}   ↳ {_short(ev.data['output'])} [{ev.data['duration_ms']} ms]{RESET}")
        elif ev.type == "text":
            print(f"\n{ev.data['text']}\n")
        elif ev.type == "notice":
            print(f"{YELLOW}ℹ {ev.data['text']}{RESET}")
        elif ev.type == "error":
            print(f"{RED}✖ {ev.data['text']}{RESET}")


def direct_tool_call(agent, line: str) -> None:
    parts = line.split(maxsplit=2)
    if len(parts) < 2:
        print("usage: /tool NAME {json args}")
        return
    name = parts[1]
    try:
        args = json.loads(parts[2]) if len(parts) > 2 else {}
    except json.JSONDecodeError as e:
        print(f"{RED}invalid JSON: {e}{RESET}")
        return
    result = agent.registry.execute(agent.ctx, "manual", name, args)
    out = result.output if isinstance(result.output, str) else json.dumps(json.loads(to_json(result.output)), indent=2)
    print((RED if result.is_error else "") + out + RESET)


def main() -> None:
    parser = argparse.ArgumentParser(description="CRM Copilot - terminal chat")
    parser.add_argument("--ask", help="ask a single question and exit")
    parser.add_argument("--user", default="Priya Shah", help="who you are (default: Priya Shah, a sales rep)")
    parser.add_argument("--auto-approve", action="store_true", help="approve write actions without asking")
    parser.add_argument("--quiet", action="store_true", help="hide thinking and tool results")
    args = parser.parse_args()

    approve = (lambda n, a: True) if args.auto_approve else _prompt_approval
    agent = build_agent(user=args.user, approve=approve)
    verbose = not args.quiet

    if args.ask:
        run_turn(agent, args.ask, verbose)
        return

    print(f"{BOLD}CRM Copilot{RESET} - database: {backend_name(agent.ctx.db)}, "
          f"model: {agent.settings.model}, user: {args.user}")
    print(f"{DIM}Try: \"Which deals are closing in the next 30 days?\"  |  /tools  /tool  /reset  /quit{RESET}\n")
    while True:
        try:
            line = input(f"{GREEN}you ›{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/quit", "/exit"):
            break
        if line == "/reset":
            agent.reset()
            print("Conversation cleared.")
        elif line == "/usage":
            print(agent.usage)
        elif line == "/tools":
            for tool in agent.registry:
                flag = f" {YELLOW}[write]{RESET}" if tool.mutating else ""
                print(f"  {CYAN}{tool.name}{RESET}{flag} - {tool.description.splitlines()[0]}")
        elif line.startswith("/tool"):
            direct_tool_call(agent, line)
        else:
            run_turn(agent, line, verbose)


if __name__ == "__main__":
    main()
