"""Tests for the configurable TL;DR prompt and token budget.

Kept in its own file (rather than added to test_protocol.py) so that pulling
from upstream never conflicts with it.
"""

import re
from types import SimpleNamespace

import pytest
import tiktoken

from zotero_arxiv_daily.construct_email import format_tldr
from zotero_arxiv_daily.protocol import (
    DEFAULT_MAX_PROMPT_TOKENS,
    DEFAULT_TLDR_INSTRUCTION,
    DEFAULT_TLDR_SYSTEM_PROMPT,
)
from tests.canned_responses import make_sample_paper


def make_capturing_client(captured: dict):
    """Stub OpenAI client that records the kwargs it was called with."""

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="stub tldr"))]
        )

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )


def bold_labels(text: str):
    """The '**Label:**' markers a prompt asks the model to emit."""
    return re.findall(r"\*\*([^*]+:)\*\*", text)


def messages_of(captured: dict):
    by_role = {m["role"]: m["content"] for m in captured["messages"]}
    return by_role["system"], by_role["user"]


# ---------------------------------------------------------------------------
# prompt overrides
# ---------------------------------------------------------------------------


def test_custom_prompts_are_used_and_lang_substituted():
    captured = {}
    paper = make_sample_paper()
    paper.generate_tldr(
        make_capturing_client(captured),
        {
            "language": "French",
            "tldr_system_prompt": "You are a researcher. Write in {lang}.",
            "tldr_instruction": "Generate a quick read in {lang}.",
            "generation_kwargs": {},
        },
    )
    system, user = messages_of(captured)
    assert system == "You are a researcher. Write in French."
    assert user.startswith("Generate a quick read in French.")
    # the paper fields are still appended after the instruction
    assert paper.title in user


def test_falls_back_to_builtin_prompts_when_unset():
    captured = {}
    make_sample_paper().generate_tldr(
        make_capturing_client(captured),
        {"language": "English", "generation_kwargs": {}},
    )
    system, user = messages_of(captured)
    assert system == DEFAULT_TLDR_SYSTEM_PROMPT.replace("{lang}", "English")
    assert user.startswith(DEFAULT_TLDR_INSTRUCTION.replace("{lang}", "English"))


def test_null_prompt_values_fall_back_to_builtin():
    """A key present but null (as base.yaml declares it) must not blank the prompt."""
    captured = {}
    make_sample_paper().generate_tldr(
        make_capturing_client(captured),
        {"tldr_system_prompt": None, "tldr_instruction": None, "generation_kwargs": {}},
    )
    system, user = messages_of(captured)
    assert system == DEFAULT_TLDR_SYSTEM_PROMPT.replace("{lang}", "English")
    assert user.startswith(DEFAULT_TLDR_INSTRUCTION.replace("{lang}", "English"))


def test_braces_in_prompt_do_not_break_substitution():
    """LaTeX-ish braces must survive; we use replace(), not str.format()."""
    captured = {}
    make_sample_paper().generate_tldr(
        make_capturing_client(captured),
        {"language": "English", "tldr_instruction": "Summarize {lang}, ignore \\cite{foo}.", "generation_kwargs": {}},
    )
    _, user = messages_of(captured)
    assert user.startswith("Summarize English, ignore \\cite{foo}.")


# ---------------------------------------------------------------------------
# token budget
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("budget", [200, 4000, 8000])
def test_prompt_truncated_to_configured_budget(budget):
    captured = {}
    paper = make_sample_paper(full_text="word " * 20000)
    paper.generate_tldr(
        make_capturing_client(captured),
        {"max_prompt_tokens": budget, "generation_kwargs": {}},
    )
    _, user = messages_of(captured)
    enc = tiktoken.encoding_for_model("gpt-4o")
    assert len(enc.encode(user)) <= budget


def test_budget_defaults_to_4000_when_unset():
    captured = {}
    paper = make_sample_paper(full_text="word " * 20000)
    paper.generate_tldr(make_capturing_client(captured), {"generation_kwargs": {}})
    _, user = messages_of(captured)
    enc = tiktoken.encoding_for_model("gpt-4o")
    n = len(enc.encode(user))
    assert n <= DEFAULT_MAX_PROMPT_TOKENS
    assert n > DEFAULT_MAX_PROMPT_TOKENS - 50  # actually filled the budget


def test_larger_budget_lets_more_of_the_paper_through():
    small, large = {}, {}
    paper = make_sample_paper(full_text="word " * 20000)
    paper.generate_tldr(make_capturing_client(small), {"max_prompt_tokens": 4000, "generation_kwargs": {}})
    paper.generate_tldr(make_capturing_client(large), {"max_prompt_tokens": 8000, "generation_kwargs": {}})
    assert len(messages_of(large)[1]) > len(messages_of(small)[1])


# ---------------------------------------------------------------------------
# config wiring
# ---------------------------------------------------------------------------


def test_config_exposes_personal_overrides(config):
    assert config.llm.max_prompt_tokens == 8000
    assert "machine learning researcher" in config.llm.tldr_system_prompt
    assert "{lang}" in config.llm.tldr_system_prompt
    # assert the shape (three bold labels), not their exact wording, so that
    # renaming a label in personal.yaml doesn't break the test
    labels = bold_labels(config.llm.tldr_instruction)
    assert len(labels) == 3, f"expected 3 bold labels, got {labels}"
    assert "Motivation:" in labels
    assert "Method:" in labels


def test_config_values_drive_the_request(config):
    captured = {}
    make_sample_paper().generate_tldr(make_capturing_client(captured), config.llm)
    system, user = messages_of(captured)
    assert "machine learning researcher" in system
    assert "{lang}" not in system
    # every label configured in personal.yaml reaches the model
    for label in bold_labels(config.llm.tldr_instruction):
        assert label in user


# ---------------------------------------------------------------------------
# email rendering of a multi-line TLDR
# ---------------------------------------------------------------------------


def test_format_tldr_preserves_line_structure():
    html = format_tldr("Core idea: X.\n\nMotivation: Y.\n\nMethod:\n1. A\n2. B")
    assert "<br>" in html
    assert "\n" not in html
    assert html.count("<br>") == 6


def test_format_tldr_converts_markdown_bold():
    assert format_tldr("**Core idea:** X") == "<strong>Core idea:</strong> X"


def test_format_tldr_handles_empty():
    assert format_tldr(None) is None
    assert format_tldr("") == ""
