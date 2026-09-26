"""Jev-powered fast decisions for the browser loop (typed answers, ~150ms, no LLM tokens).

Every method returns None when Jev is unavailable or fails, so callers fall back to the LLM's own judgement.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

PROGRESS_CRITERIA = {
    "continue": "More browser actions are still needed to complete the sub-task.",
    "done": "The information or result the sub-task asks for is now present in the latest result.",
    "stuck": "The actions are failing, blocked (captcha/login wall), or repeating without progress.",
}


@dataclass
class StepReview:
    step_ok: float
    progress: str
    confidence: float
    latency_ms: int
    probabilities: dict[str, float] = field(default_factory=dict)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


class JevDecider:
    def __init__(self, jev: Any | None, threshold: float = 0.6, risky_threshold: float = 0.5) -> None:
        self.jev, self.threshold, self.risky_threshold = jev, threshold, risky_threshold

    @property
    def enabled(self) -> bool:
        return self.jev is not None

    async def _ask(self, state: Any, questions: dict[str, Any]) -> Any | None:
        if not self.jev:
            return None
        try:
            return await self.jev.ask(state, questions)
        except Exception as exc:
            log.warning("Jev decision failed: %s", exc)
            return None

    async def is_multi_step(self, goal: str) -> float | None:
        from typesafe_sdk import Noul

        result = await self._ask({"request": goal}, {"multi": Noul(
            instructions="Does this request require several distinct steps done in sequence "
                         "(e.g. find something, then open it, then summarize or act on it)?",
            criteria={"true": "Multiple dependent steps, or several separate things to do.",
                      "false": "One lookup or one action."})})
        return float(result.answers["multi"].noul) if result else None

    async def risky(self, goal: str, tool: str, arguments: dict[str, Any], page_hint: str = "") -> float | None:
        from typesafe_sdk import Noul

        result = await self._ask(
            {"user_request": goal, "tool": tool, "arguments": arguments, "page_context": _clip(page_hint, 1500)},
            {"risky": Noul(
                instructions="Would executing this browser action have an irreversible real-world effect?",
                criteria={"true": "Submits a purchase/payment, sends or posts a message, deletes data, confirms a "
                                  "booking, changes account settings, or clicks a button that submits a form.",
                          "false": "Only navigates, reads, searches, scrolls, opens menus, or types/fills text into "
                                   "fields without submitting (filling is reversible until submit)."})})
        return float(result.answers["risky"].noul) if result else None

    async def review_step(self, subtask: str, action: str, result_text: str) -> StepReview | None:
        from typesafe_sdk import Choice, Noul

        start = time.perf_counter()
        result = await self._ask(
            {"sub_task": subtask, "last_action": action, "latest_result": _clip(result_text, 2500)},
            {"step_ok": Noul(instructions="Did the last action succeed (no error, expected page/content)?"),
             "progress": Choice(instructions="What should happen next for this sub-task?", criteria=PROGRESS_CRITERIA)})
        if not result:
            return None
        progress = result.answers["progress"]
        probs = dict(progress.probabilities)
        return StepReview(step_ok=float(result.answers["step_ok"].noul), progress=progress.choice,
                          confidence=float(probs.get(progress.choice, progress.confidence)),
                          latency_ms=int((time.perf_counter() - start) * 1000), probabilities=probs)
