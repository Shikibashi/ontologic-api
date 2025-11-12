#!/usr/bin/env python3
"""Validate Sophia responses against Expected Output specifications."""

import json
import re
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass
from functools import lru_cache
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

@dataclass
class ValidationResult:
    prompt_id: str
    passed: bool
    total_checks: int
    passed_checks: int
    failures: List[str]
    response_length: int

class SophiaValidator:
    def __init__(self, specs_path: str = "tests/sophia_specs.json"):
        with open(specs_path) as f:
            self.specs = json.load(f)

        # Compile regex patterns once at init for performance
        self._persona_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in [
                r"\bi\s+(?:believe|think|contend|argue|maintain|hold|assert|claim|would argue|would suggest|would propose)",
                r"\bin\s+my\s+(?:view|opinion|judgment|estimation|analysis|position)",
                r"\bit\s+seems\s+to\s+me",
                r"\bas\s+i\s+(?:have\s+)?(?:argued|written|stated|claimed|shown|demonstrated)",
                r"\bmy\s+(?:theory|view|position|account|framework|analysis)",
            ]
        ]

        self._prescriptive_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in [
                r"\btherefore,?\s+(?:we|one|you)\s+(?:must|should|ought to)\b",
                r"\b(?:clearly|obviously|definitively),?\s+the\s+(?:right|correct|best)\s+",
                r"\bwe\s+can\s+conclude\s+that\s+\w+\s+is\s+(?:right|wrong|superior)\b",
                r"\bthe\s+only\s+justified\s+(?:position|view|answer)\b",
            ]
        ]

        self._verdict_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in [
                r"\btherefore,?\s+",
                r"\b(?:should|must|ought to)\s+",
                r"\bi\s+(?:recommend|conclude|judge)\s+",
                r"\bthe\s+(?:right|just|correct)\s+(?:answer|position|view)\s+is\b",
            ]
        ]

    def validate_response(self, prompt_id: str, response_text: str) -> ValidationResult:
        """Validate a single response against its spec.

        Args:
            prompt_id: Identifier for the prompt
            response_text: The LLM response text to validate

        Returns:
            ValidationResult with pass/fail status and detailed failures
        """
        # Edge case: Empty or whitespace-only response
        if not response_text or not response_text.strip():
            return ValidationResult(
                prompt_id=prompt_id,
                passed=False,
                total_checks=1,
                passed_checks=0,
                failures=["Response is empty or whitespace-only"],
                response_length=0
            )

        # Edge case: No spec exists
        if prompt_id not in self.specs:
            return ValidationResult(
                prompt_id=prompt_id,
                passed=False,
                total_checks=0,
                passed_checks=0,
                failures=[f"No spec found for {prompt_id}"],
                response_length=len(response_text.split())
            )

        spec = self.specs[prompt_id]
        failures = []
        checks = 0
        passed = 0

        # Safe word count with unicode handling
        try:
            word_count = len(response_text.split())
        except (AttributeError, UnicodeDecodeError) as e:
            return ValidationResult(
                prompt_id=prompt_id,
                passed=False,
                total_checks=1,
                passed_checks=0,
                failures=[f"Cannot parse response text: {e}"],
                response_length=0
            )

        # Check word count with safe defaults
        checks += 1
        min_words = spec.get("min_words", 0)
        max_words = spec.get("max_words", float('inf'))

        # Edge case: Unreasonable word count thresholds
        if max_words < min_words:
            failures.append(f"Invalid spec: max_words ({max_words}) < min_words ({min_words})")
        elif min_words <= word_count <= max_words:
            passed += 1
        else:
            failures.append(f"Word count {word_count} outside range [{min_words}, {max_words}]")

        # Check required keywords (case-insensitive, handle unicode)
        try:
            response_lower = response_text.lower()
        except (AttributeError, UnicodeDecodeError):
            response_lower = str(response_text).lower()

        for keyword in spec.get("required_keywords", []):
            checks += 1
            try:
                keyword_lower = keyword.lower()
                if keyword_lower in response_lower:
                    passed += 1
                else:
                    failures.append(f"Missing keyword: '{keyword}'")
            except (AttributeError, TypeError) as e:
                failures.append(f"Invalid keyword format: {keyword} ({e})")

        # Check persona requirement with comprehensive pattern matching
        if spec.get("requires_persona"):
            checks += 1
            persona_found = any(pattern.search(response_text) for pattern in self._persona_patterns)

            if persona_found:
                passed += 1
            else:
                failures.append("Missing persona/first-person perspective (expected philosopher voice)")

        # Check conclusion type with context-aware detection
        checks += 1
        conclusion_type = spec.get("conclusion_type", "balanced")

        if conclusion_type == "balanced":
            # Look for STRONG prescriptive language (not just keywords in neutral context)
            prescriptive_found = any(pattern.search(response_text) for pattern in self._prescriptive_patterns)

            if not prescriptive_found:
                passed += 1
            else:
                failures.append("Response too prescriptive (expected balanced analysis)")

        elif conclusion_type == "verdict":
            # SHOULD have clear position-taking language
            verdict_found = any(pattern.search(response_text) for pattern in self._verdict_patterns)

            if verdict_found:
                passed += 1
            else:
                failures.append("Missing clear verdict/recommendation (expected definitive position)")
        else:
            # Edge case: Unknown conclusion type
            failures.append(f"Unknown conclusion_type in spec: '{conclusion_type}'")

        is_passed = len(failures) == 0

        return ValidationResult(
            prompt_id=prompt_id,
            passed=is_passed,
            total_checks=checks,
            passed_checks=passed,
            failures=failures,
            response_length=word_count
        )

    def validate_all(self, responses_path: str = "tests/live_responses.json") -> List[ValidationResult]:
        """Validate all responses from a test run."""
        with open(responses_path) as f:
            data = json.load(f)

        results = []

        # Handle structure: {metadata: ..., results: {prompt_id: {variants: [...]}}}
        if "results" in data:
            for prompt_id, prompt_data in data["results"].items():
                variants = prompt_data.get("variants", [])
                if variants:
                    # Use first variant (temperature 0.3) for validation
                    variant = variants[0]
                    text = variant.get("result", {}).get("text", "")
                    result = self.validate_response(prompt_id, text)
                    results.append(result)
        else:
            # Legacy format: list of responses
            for response in data:
                prompt_id = response.get("prompt_id", "unknown")
                text = response.get("response", {}).get("text", "")
                result = self.validate_response(prompt_id, text)
                results.append(result)

        return results

    def print_summary(self, results: List[ValidationResult]):
        """Print a summary table of validation results."""
        table = Table(title="Sophia Validation Summary", show_lines=True)
        table.add_column("Prompt ID", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Checks", justify="center")
        table.add_column("Words", justify="right")
        table.add_column("Issues", style="yellow")

        passed_count = 0
        for result in sorted(results, key=lambda r: r.prompt_id):
            status = "✅" if result.passed else "❌"
            checks = f"{result.passed_checks}/{result.total_checks}"
            issues = "; ".join(result.failures[:2]) if result.failures else "-"
            if len(result.failures) > 2:
                issues += f" (+{len(result.failures)-2} more)"

            table.add_row(
                result.prompt_id,
                status,
                checks,
                str(result.response_length),
                issues
            )

            if result.passed:
                passed_count += 1

        console.print(table)

        # Print overall stats
        total = len(results)
        pass_rate = (passed_count / total * 100) if total > 0 else 0

        stats_panel = Panel(
            f"[bold green]Passed:[/bold green] {passed_count}/{total} ({pass_rate:.1f}%)\n"
            f"[bold red]Failed:[/bold red] {total - passed_count}/{total}",
            title="Overall Results",
            border_style="blue"
        )
        console.print(stats_panel)

    def print_detailed_failures(self, results: List[ValidationResult]):
        """Print detailed failure information with actionable suggestions."""
        failures = [r for r in results if not r.passed]
        if not failures:
            console.print("[bold green]All prompts passed validation! 🎉[/bold green]")
            return

        console.print(f"\n[bold red]Detailed Failures ({len(failures)} prompts):[/bold red]\n")

        for result in sorted(failures, key=lambda r: r.prompt_id):
            console.print(f"[bold cyan]{result.prompt_id}[/bold cyan]")

            spec = self.specs.get(result.prompt_id, {})

            for failure in result.failures:
                console.print(f"  • {failure}")

                # Add actionable suggestions
                if "Word count" in failure:
                    min_w = spec.get("min_words", 0)
                    max_w = spec.get("max_words", "∞")
                    console.print(f"    [dim]💡 Target: {min_w}-{max_w} words (currently {result.response_length})[/dim]")

                elif "Missing keyword" in failure:
                    keyword = failure.split("'")[1]
                    console.print(f"    [dim]💡 Add discussion of '{keyword}' to the response[/dim]")

                elif "persona" in failure.lower():
                    console.print(f"    [dim]💡 Use first-person voice: 'I believe...', 'In my view...', 'I would argue...'[/dim]")

                elif "prescriptive" in failure.lower():
                    console.print(f"    [dim]💡 Present multiple views without asserting one as 'correct'[/dim]")

                elif "verdict" in failure.lower():
                    console.print(f"    [dim]💡 Add clear recommendation: 'Therefore, I conclude that...', 'One should...'[/dim]")

            console.print()

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Validate Sophia responses")
    parser.add_argument("--responses", default="tests/live_responses.json", help="Path to responses JSON")
    parser.add_argument("--specs", default="tests/sophia_specs.json", help="Path to specs JSON")
    parser.add_argument("--detailed", action="store_true", help="Show detailed failure information")
    args = parser.parse_args()

    validator = SophiaValidator(args.specs)
    results = validator.validate_all(args.responses)

    validator.print_summary(results)

    if args.detailed:
        validator.print_detailed_failures(results)

if __name__ == "__main__":
    main()
