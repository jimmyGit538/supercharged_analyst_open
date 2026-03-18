"""
example_agent.py

Shows how a Claude sub-agent loads its own definition from BigQuery
at startup and uses it as the system prompt.

Run:
    python example_agent.py
"""

import os
import anthropic
from dotenv import load_dotenv
from agent_registry import load_agent, load_skill

load_dotenv()


def run_agent(user_message: str) -> str:
    """
    Bootstrap a Claude agent whose system prompt comes entirely from BigQuery.
    No .md files on disk — the DB is the source of truth.
    """

    # 1. Load agent definition from BigQuery (live, no cache)
    system_prompt = load_agent("extraction-agent")

    # 2. Optionally compose in a skill
    skill_text = load_skill("python-data-extraction")
    system_prompt = f"{system_prompt}\n\n---\n\n{skill_text}"

    # 3. Call Claude with the dynamically loaded system prompt
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text


if __name__ == "__main__":
    response = run_agent("Extract all contacts updated since yesterday from Salesforce.")
    print(response)
