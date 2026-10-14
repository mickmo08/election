"""Scope policy for the research assistant (docs/policies/assistant-scope.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass

RULES: list[tuple[str, re.Pattern, str]] = [
    (
        "individual_profiling",
        re.compile(
            r"\b(how did|who did|did)\s+(my|our|the)?\s*(neighbou?r|coworker|co-worker|boss|friend|wife|husband|"
            r"partner|mother|father|parent|son|daughter|employee|tenant|landlord|voter)\b.*\b(vote|support|lean)|"
            r"\b(is|was)\s+[A-Z][a-z]+\s+[A-Z][a-z]+\s+(a\s+)?(democrat|republican|liberal|conservative|gay|muslim|"
            r"christian|jewish|hispanic|latino|black|immigrant)|"
            r"\b(religion|ethnicity|race|sexual orientation|political (views|beliefs|affiliation)|party affiliation)\s+"
            r"of\s+[A-Z][a-z]+|\bwho (did|will) [A-Z][a-z]+ [A-Z][a-z]+ vote for\b|"
            r"\b(infer|predict|guess|determine)\b.{0,40}\b(how|whether)\b.{0,30}\b(person|individual|someone|he|she|they)\b"
            r".{0,30}\bvote",
            re.I,
        ),
        "I can't infer or look up how a specific person votes or what their political views, religion or ethnicity "
        "are. I can help with aggregate results, surveys and trends.",
    ),
    (
        "persuasion_targeting",
        re.compile(
            r"\b(micro-?target|target(ed|ing)? (ads?|messages?|voters)|persuade|persuasion (script|message)|"
            r"(write|draft|create).{0,30}(campaign ad|attack ad|political ad|get.out.the.vote|gotv|fundraising email)|"
            r"(which|what) voters (should|to) (we )?(target|contact|persuade)|voter (file|list) (for|to) (contact|"
            r"outreach)|(text|call|email)\s+(voters|these voters))",
            re.I,
        ),
        "I can't help with political persuasion, ad targeting or voter outreach. I can explain aggregate patterns "
        "and published research.",
    ),
    (
        "turnout_as_choice",
        re.compile(r"\b(turnout|voter) (record|file|history)\b.{0,60}\b(voted for|ballot choice|" r"chose)\b", re.I),
        "Turnout records show whether someone voted, never how they voted. I can't infer ballot choices from them.",
    ),
    (
        "race_call_request",
        re.compile(r"\b(call|declare|project)\b.{0,20}\b(the )?(race|winner|election)\b", re.I),
        "I don't call races. I can show the reported count, its status, and any race call recorded from a source "
        "authorized by the editorial policy.",
    ),
]
MAX_QUESTION_CHARS = 2000


@dataclass
class PolicyDecision:
    allowed: bool
    rule: str | None = None
    message: str | None = None


def check(question: str) -> PolicyDecision:
    if len(question) > MAX_QUESTION_CHARS:
        return PolicyDecision(False, "too_long", f"Questions are limited to {MAX_QUESTION_CHARS} characters.")
    for name, pattern, message in RULES:
        if pattern.search(question):
            return PolicyDecision(False, name, message)
    return PolicyDecision(True)
