#!/usr/bin/env python
"""Generate a comparison report between mock responses and actual LLM responses."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


def load_json(path: Path) -> dict[str, Any]:
    """Load JSON file."""
    with open(path) as f:
        return json.load(f)


def extract_keywords(text: str) -> set[str]:
    """Extract significant words from text (simple implementation)."""
    words = text.lower().split()
    # Filter out common words
    common = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "can", "this", "that", "these",
        "those", "i", "you", "he", "she", "it", "we", "they", "them"
    }
    return {w.strip(".,!?;:") for w in words if len(w) > 3 and w not in common}


def calculate_keyword_overlap(mock: str, actual: str) -> float:
    """Calculate Jaccard similarity between mock and actual keywords."""
    mock_words = extract_keywords(mock)
    actual_words = extract_keywords(actual)

    if not mock_words or not actual_words:
        return 0.0

    intersection = len(mock_words & actual_words)
    union = len(mock_words | actual_words)

    return intersection / union if union > 0 else 0.0


def compare_responses(
    prompt_id: str,
    mock_response: dict[str, Any],
    actual_response: dict[str, Any],
) -> dict[str, Any]:
    """Compare mock and actual responses for a prompt."""

    mock_content = mock_response.get("content", "")
    actual_text = actual_response.get("text", "")

    # Basic stats
    mock_length = len(mock_content)
    actual_length = len(actual_text)
    length_ratio = actual_length / mock_length if mock_length > 0 else 0

    # Keyword overlap
    keyword_similarity = calculate_keyword_overlap(mock_content, actual_text)

    # Token usage comparison
    mock_usage = mock_response.get("raw", {}).get("usage", {})
    actual_usage = actual_response.get("raw", {}).get("usage", {})

    mock_tokens = mock_usage.get("total_tokens", 0)
    actual_tokens = actual_usage.get("total_tokens", 0)

    # Response time
    elapsed_time = actual_response.get("_metadata", {}).get("elapsed_seconds", 0)

    return {
        "prompt_id": prompt_id,
        "lengths": {
            "mock": mock_length,
            "actual": actual_length,
            "ratio": round(length_ratio, 2),
        },
        "keyword_similarity": round(keyword_similarity, 3),
        "tokens": {
            "mock": mock_tokens,
            "actual": actual_tokens,
            "difference": actual_tokens - mock_tokens,
        },
        "response_time_seconds": elapsed_time,
        "mock_snippet": mock_content[:200] + "..." if len(mock_content) > 200 else mock_content,
        "actual_snippet": actual_text[:200] + "..." if len(actual_text) > 200 else actual_text,
        "mock_full": mock_content,
        "actual_full": actual_text,
    }


def generate_markdown_report(
    comparisons: list[dict[str, Any]],
    output_path: Path,
    metadata: dict[str, Any],
) -> None:
    """Generate a markdown report with comparisons."""

    report_lines = [
        "# Philosophy Prompt Comparison Report",
        "",
        f"**Generated:** {datetime.now().isoformat()}",
        f"**API URL:** {metadata.get('api_url', 'Unknown')}",
        f"**Total Prompts:** {metadata.get('total_prompts', 0)}",
        f"**Total Errors:** {metadata.get('total_errors', 0)}",
        "",
        "---",
        "",
        "## Summary Statistics",
        "",
    ]

    # Calculate aggregate stats
    if comparisons:
        avg_length_ratio = sum(c["lengths"]["ratio"] for c in comparisons) / len(comparisons)
        avg_keyword_sim = sum(c["keyword_similarity"] for c in comparisons) / len(comparisons)
        avg_response_time = sum(c["response_time_seconds"] for c in comparisons) / len(comparisons)
        total_tokens_mock = sum(c["tokens"]["mock"] for c in comparisons)
        total_tokens_actual = sum(c["tokens"]["actual"] for c in comparisons)

        report_lines.extend([
            f"- **Average Length Ratio (Actual/Mock):** {avg_length_ratio:.2f}",
            f"- **Average Keyword Similarity:** {avg_keyword_sim:.3f}",
            f"- **Average Response Time:** {avg_response_time:.2f}s",
            f"- **Total Tokens (Mock):** {total_tokens_mock:,}",
            f"- **Total Tokens (Actual):** {total_tokens_actual:,}",
            f"- **Token Difference:** {total_tokens_actual - total_tokens_mock:,}",
            "",
        ])

    report_lines.extend([
        "---",
        "",
        "## Individual Prompt Comparisons",
        "",
    ])

    # Add each comparison
    for i, comp in enumerate(comparisons, 1):
        report_lines.extend([
            f"### {i}. {comp['prompt_id']}",
            "",
            "**Metrics:**",
            "",
            f"- Length: Mock={comp['lengths']['mock']} chars, Actual={comp['lengths']['actual']} chars, Ratio={comp['lengths']['ratio']}",
            f"- Keyword Similarity: {comp['keyword_similarity']}",
            f"- Tokens: Mock={comp['tokens']['mock']}, Actual={comp['tokens']['actual']}, Diff={comp['tokens']['difference']:+}",
            f"- Response Time: {comp['response_time_seconds']}s",
            "",
            "<details>",
            "<summary><strong>Mock Response (click to expand)</strong></summary>",
            "",
            f"> {comp['mock_full']}",
            "",
            "</details>",
            "",
            "<details>",
            "<summary><strong>Actual Response (click to expand)</strong></summary>",
            "",
            f"> {comp['actual_full']}",
            "",
            "</details>",
            "",
            "---",
            "",
        ])

    # Write to file
    with open(output_path, "w") as f:
        f.write("\n".join(report_lines))

    console.print(f"[green]✓ Markdown report saved to {output_path}[/green]")


def generate_json_report(
    comparisons: list[dict[str, Any]],
    output_path: Path,
    metadata: dict[str, Any],
) -> None:
    """Generate a JSON report with comparisons."""

    report = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            **metadata,
        },
        "comparisons": comparisons,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    console.print(f"[green]✓ JSON report saved to {output_path}[/green]")


def print_summary_table(comparisons: list[dict[str, Any]]) -> None:
    """Print a summary table to console."""

    table = Table(title="Prompt Comparison Summary")
    table.add_column("Prompt ID", style="cyan", no_wrap=True)
    table.add_column("Length Ratio", justify="right", style="magenta")
    table.add_column("Keyword Sim", justify="right", style="green")
    table.add_column("Token Diff", justify="right", style="yellow")
    table.add_column("Time (s)", justify="right", style="blue")

    for comp in comparisons:
        table.add_row(
            comp["prompt_id"][:40],
            f"{comp['lengths']['ratio']:.2f}",
            f"{comp['keyword_similarity']:.3f}",
            f"{comp['tokens']['difference']:+}",
            f"{comp['response_time_seconds']:.1f}",
        )

    console.print(table)


def main():
    parser = argparse.ArgumentParser(
        description="Generate comparison report between mock and actual LLM responses"
    )
    parser.add_argument(
        "--live-responses",
        default="tests/live_responses.json",
        help="Path to live responses JSON (default: tests/live_responses.json)",
    )
    parser.add_argument(
        "--canned-responses",
        default="tests/fixtures/canned_responses.json",
        help="Path to canned responses JSON (default: tests/fixtures/canned_responses.json)",
    )
    parser.add_argument(
        "--output-md",
        default="tests/comparison_report.md",
        help="Output markdown report path (default: tests/comparison_report.md)",
    )
    parser.add_argument(
        "--output-json",
        default="tests/comparison_report.json",
        help="Output JSON report path (default: tests/comparison_report.json)",
    )

    args = parser.parse_args()

    # Load data
    console.print(f"[cyan]Loading live responses from {args.live_responses}...[/cyan]")
    live_data = load_json(Path(args.live_responses))

    console.print(f"[cyan]Loading canned responses from {args.canned_responses}...[/cyan]")
    canned_data = load_json(Path(args.canned_responses))

    # Process comparisons
    comparisons = []

    for prompt_id, prompt_data in live_data.get("results", {}).items():
        if prompt_id not in canned_data:
            console.print(f"[yellow]⚠ No canned response for {prompt_id}[/yellow]")
            continue

        canned = canned_data[prompt_id]
        mock_response = canned.get("mock_response", {})

        # Compare each variant
        for variant in prompt_data.get("variants", []):
            result = variant.get("result", {})

            if result.get("error"):
                console.print(f"[red]✗ {prompt_id} variant {variant['variant_index']}: Error in live response[/red]")
                continue

            variant_id = f"{prompt_id}::variant{variant['variant_index']}"

            comparison = compare_responses(variant_id, mock_response, result)
            comparisons.append(comparison)

    if not comparisons:
        console.print("[red]No successful comparisons to report[/red]")
        return

    console.print(f"[green]✓ Generated {len(comparisons)} comparisons[/green]\n")

    # Print summary table
    print_summary_table(comparisons)

    # Generate reports
    generate_markdown_report(
        comparisons,
        Path(args.output_md),
        live_data.get("metadata", {}),
    )

    generate_json_report(
        comparisons,
        Path(args.output_json),
        live_data.get("metadata", {}),
    )

    console.print("\n[green]✓ Comparison report generation complete![/green]")


if __name__ == "__main__":
    main()
