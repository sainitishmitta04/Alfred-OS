"""Multi-chain support: split a request into ordered sub-tasks, then merge sub-task results into one answer."""

from __future__ import annotations

import json
import logging
import re

from browser_agent import prompts
from browser_agent.decisions import JevDecider
from browser_agent.llm import DailyQuotaExceeded

log = logging.getLogger(__name__)

MAX_SUBTASKS = 4
# Cheap pre-filter so obvious one-liners never pay for a Jev/LLM planning call.
_CHAIN_WORDS = re.compile(r"\b(then|and then|after that|afterwards|next|finally|also|and (?:open|click|summari[sz]e|tell|save|send|compare|find|read))\b", re.I)
_JSON = re.compile(r"\{.*\}", re.S)


def parse_subtasks(text: str) -> list[str]:
    match = _JSON.search(text or "")
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    items = data.get("subtasks") if isinstance(data, dict) else None
    return [s.strip() for s in items or [] if isinstance(s, str) and s.strip()][:MAX_SUBTASKS]


class Planner:
    def __init__(self, llm, decider: JevDecider, model: str | None = None) -> None:
        self.llm, self.decider, self.model = llm, decider, model

    async def needs_plan(self, goal: str) -> tuple[bool, str]:
        score = await self.decider.is_multi_step(goal)
        if score is not None:
            return score >= 0.5, f"jev multi_step={score:.2f}"
        chained = bool(_CHAIN_WORDS.search(goal))
        return chained, f"keyword multi_step={chained}"

    async def plan(self, goal: str) -> tuple[list[str], str]:
        multi, why = await self.needs_plan(goal)
        if not multi:
            return [goal], why
        try:
            result = await self.llm.chat([{"role": "user", "content": prompts.PLANNER.format(goal=goal, max_subtasks=MAX_SUBTASKS)}],
                                         model=self.model, temperature=0, max_tokens=1000)
            subtasks = parse_subtasks(result.content)
            if subtasks:
                return subtasks, f"{why}; planned by {result.model}"
        except DailyQuotaExceeded:
            raise
        except Exception as exc:
            log.warning("planning failed, running as one task: %s", exc)
        return [goal], f"{why}; planner fallback"

    async def synthesize(self, goal: str, results: list[tuple[str, str]]) -> str:
        if len(results) == 1:
            return results[0][1]
        joined = "\n".join(f"{i}. {task}\n   -> {answer}" for i, (task, answer) in enumerate(results, 1))
        try:
            result = await self.llm.chat([{"role": "user", "content": prompts.SYNTHESIZE.format(goal=goal, results=joined)}],
                                         model=self.model, temperature=0.2, max_tokens=600)
            if result.content:
                return result.content
        except Exception as exc:  # includes quota errors: fall back to joining sub-answers
            log.warning("synthesis failed: %s", exc)
        return " ".join(answer for _, answer in results)
