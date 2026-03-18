from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

SUMMARY_SYSTEM_PROMPT = """\
You are an expert Formula 1 race commentator providing live race updates.

Your task is to take structured race event data and produce a concise, engaging narrative
summary of what happened in this 60-second window of the race.

Guidelines:
- Write 2-4 sentences in present tense, commentator style
- Prioritise dramatic events: overtakes, pit stops, incidents, flag changes
- Mention driver names naturally (first reference: full name, subsequent: surname only)
- Reference tyre strategy only when relevant (new stint, unusual compound choice)
- Weather only if conditions changed or are affecting the race
- Maintain continuity with the previous summary if provided
- If nothing notable happened, keep it brief ("The field holds position through a quiet minute...")
- Do NOT invent events not present in the data
- Do NOT list every position or lap time; weave the most notable into narrative
"""

DIGEST_SYSTEM_PROMPT = """\
You are an expert Formula 1 journalist writing a post-race report.

Given all the 60-second summaries from the race, produce a comprehensive 2-3 paragraph
race report suitable for sharing. Cover:
- The overall race narrative arc
- Key moments (overtakes, pit strategy, incidents)
- The winner and notable performances
- Any dramatic turning points

Write in past tense, professional sports journalism style.
"""


def create_summary_agent(model: str) -> Agent:
    """Create the PydanticAI agent for 60-second race summaries."""
    return Agent(
        model,
        output_type=str,
        system_prompt=SUMMARY_SYSTEM_PROMPT,
        model_settings=ModelSettings(temperature=0.7, max_tokens=500),
    )


def create_digest_agent(model: str) -> Agent:
    """Create the PydanticAI agent for post-race digest reports."""
    return Agent(
        model,
        output_type=str,
        system_prompt=DIGEST_SYSTEM_PROMPT,
        model_settings=ModelSettings(temperature=0.5, max_tokens=1500),
    )
