"""Test fixtures and canned responses for philosophy prompt testing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

FIXTURES_DIR = Path(__file__).parent


def load_json_fixture(filename: str) -> Dict[str, Any]:
    """Load a JSON fixture file from the fixtures directory."""

    filepath = FIXTURES_DIR / filename
    with open(filepath, "r", encoding="utf-8") as file:
        return json.load(file)


def get_canned_response(prompt_id: str) -> Dict[str, Any]:
    """Get canned response for a specific prompt ID."""

    responses = load_json_fixture("canned_responses.json")
    if prompt_id not in responses:
        raise KeyError(f"No canned response found for prompt_id: {prompt_id}")
    return responses[prompt_id]


def get_prompt_catalog() -> Dict[str, Any]:
    """Load the complete prompt catalog."""

    return load_json_fixture("prompt_catalog.json")


def get_prompts_by_category(category: str) -> List[Dict[str, Any]]:
    """Get all prompts in a specific category."""

    catalog = get_prompt_catalog()
    category_data = catalog["categories"].get(category, {})
    prompt_ids = category_data.get("prompt_ids", [])

    prompts: List[Dict[str, Any]] = []
    for prompt in catalog["prompts"]:
        if prompt["id"] in prompt_ids:
            prompts.append(prompt)
    return prompts


def get_test_suite(suite_name: str) -> List[str]:
    """Get prompt IDs for a specific test suite."""

    catalog = get_prompt_catalog()
    suite = catalog["test_suites"].get(suite_name, {})
    prompt_ids = suite.get("prompt_ids", [])

    if "all" in prompt_ids:
        return [prompt["id"] for prompt in catalog["prompts"]]
    return prompt_ids


__all__ = [
    "load_json_fixture",
    "get_canned_response",
    "get_prompt_catalog",
    "get_prompts_by_category",
    "get_test_suite",
    "FIXTURES_DIR",
]
