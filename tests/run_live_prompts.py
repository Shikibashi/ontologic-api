#!/usr/bin/env python
"""Run all philosophy prompts against a live API instance and collect responses."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.fixtures import get_prompt_catalog, get_canned_response

console = Console()


def load_prompt_catalog() -> dict[str, Any]:
    """Load the prompt catalog."""
    return get_prompt_catalog()


def run_prompt_against_api(
    api_url: str,
    prompt_id: str,
    query_str: str,
    collection: str,
    immersive: bool = False,
    temperature: float = 0.3,
    prompt_type: str | None = None,
    timeout: int = 120,
    retry_on_rate_limit: bool = True,
    rate_limit_delay: int = 65,
) -> dict[str, Any]:
    """Execute a single prompt against the live API with retry logic."""

    params = {
        "immersive": immersive,
        "temperature": temperature,
    }
    if prompt_type:
        params["prompt_type"] = prompt_type

    payload = {
        "query_str": query_str,
        "collection": collection,
    }

    max_retries = 3 if retry_on_rate_limit else 1

    cumulative_elapsed_seconds = 0.0

    for attempt in range(max_retries):
        start_time = time.time()
        try:
            response = requests.post(
                f"{api_url}/ask_philosophy",
                params=params,
                json=payload,
                timeout=timeout,
            )
            elapsed_time = time.time() - start_time
            cumulative_elapsed_seconds += elapsed_time

            if response.status_code == 200:
                result = response.json()
                result["_metadata"] = {
                    "prompt_id": prompt_id,
                    "elapsed_seconds": round(elapsed_time, 2),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status_code": response.status_code,
                    "attempt": attempt + 1,
                }
                return result
            elif response.status_code == 429 and attempt < max_retries - 1:
                # Rate limit hit, wait and retry
                time.sleep(rate_limit_delay)
                continue
            else:
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "message": response.text,
                    "_metadata": {
                        "prompt_id": prompt_id,
                        "elapsed_seconds": round(elapsed_time, 2),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "status_code": response.status_code,
                        "attempt": attempt + 1,
                    },
                }
        except requests.exceptions.RequestException as e:
            elapsed_time = time.time() - start_time
            cumulative_elapsed_seconds += elapsed_time
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            return {
                "error": True,
                "exception": str(e),
                "_metadata": {
                    "prompt_id": prompt_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "attempt": attempt + 1,
                },
            }

    return {
        "error": True,
        "message": "Max retries exceeded",
        "_metadata": {
            "prompt_id": prompt_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(cumulative_elapsed_seconds, 2),
            "status_code": None,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run philosophy prompts against live API and collect responses"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--output",
        default="tests/live_responses.json",
        help="Output file for collected responses (default: tests/live_responses.json)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Request timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of prompts to run (for testing)",
    )
    parser.add_argument(
        "--prompt-ids",
        nargs="+",
        help="Run specific prompt IDs only",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=7,
        help="Delay between requests in seconds (default: 7)",
    )

    args = parser.parse_args()

    # Load catalog
    console.print(f"[cyan]Loading prompt catalog...[/cyan]")
    catalog = load_prompt_catalog()
    prompts = catalog.get("prompts", [])

    # Filter for /ask_philosophy prompts
    philosophy_prompts = [p for p in prompts if p.get("endpoint") == "/ask_philosophy"]

    # Filter by specific prompt IDs if provided
    if args.prompt_ids:
        philosophy_prompts = [p for p in philosophy_prompts if p["id"] in args.prompt_ids]

    # Limit if requested
    if args.limit:
        philosophy_prompts = philosophy_prompts[:args.limit]

    console.print(f"[green]Found {len(philosophy_prompts)} prompts to run[/green]")

    # Test API connection
    console.print(f"[cyan]Testing API connection to {args.api_url}...[/cyan]")
    try:
        response = requests.get(f"{args.api_url}/health", timeout=5)
        if response.status_code == 200:
            console.print(f"[green]✓ API is reachable[/green]")
        else:
            console.print(f"[red]✗ API returned status {response.status_code}[/red]")
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        console.print(f"[red]✗ Cannot reach API: {e}[/red]")
        sys.exit(1)

    # Run prompts
    results: dict[str, Any] = {}
    errors = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:

        task = progress.add_task(
            "[cyan]Running prompts...",
            total=len(philosophy_prompts)
        )

        for prompt in philosophy_prompts:
            prompt_id = prompt["id"]

            # Get canned input data
            try:
                canned = get_canned_response(prompt_id)
                canned_input = canned["input"]
            except Exception as e:
                console.print(f"[red]✗ {prompt_id}: Cannot load canned data - {e}[/red]")
                errors.append({"prompt_id": prompt_id, "error": str(e)})
                progress.advance(task)
                continue

            # Get test variants
            variants = prompt.get("test_variants") or [{"immersive": False, "temperature": 0.3}]

            # Run each variant
            prompt_results = []
            for idx, variant in enumerate(variants):
                variant_id = f"{prompt_id}::variant{idx}"

                # Use Combined Collection as fallback for prompts without specific philosopher requirements
                collection = prompt.get("requires_philosopher") or "Combined Collection"

                progress.update(task, description=f"[cyan]Running {variant_id}...")

                result = run_prompt_against_api(
                    api_url=args.api_url,
                    prompt_id=variant_id,
                    query_str=canned_input["query_str"],
                    collection=collection,
                    immersive=variant.get("immersive", False),
                    temperature=variant.get("temperature", 0.3),
                    prompt_type=variant.get("payload", {}).get("prompt_type"),
                    timeout=args.timeout,
                )

                if result.get("error"):
                    console.print(f"[red]✗ {variant_id}: {result.get('message', result.get('exception'))}[/red]")
                    errors.append(result)
                else:
                    console.print(f"[green]✓ {variant_id} ({result['_metadata']['elapsed_seconds']}s)[/green]")

                prompt_results.append({
                    "variant_index": idx,
                    "variant_config": variant,
                    "result": result,
                })

            results[prompt_id] = {
                "prompt": prompt,
                "canned_input": canned_input,
                "variants": prompt_results,
            }

            progress.advance(task)

            # Add delay between requests to respect rate limiting
            if args.delay > 0:
                time.sleep(args.delay)

    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "metadata": {
            "api_url": args.api_url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_prompts": len(philosophy_prompts),
            "total_errors": len(errors),
        },
        "results": results,
        "errors": errors,
    }

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    console.print(f"\n[green]✓ Results saved to {output_path}[/green]")
    console.print(f"[cyan]Total prompts: {len(philosophy_prompts)}[/cyan]")
    console.print(f"[cyan]Total errors: {len(errors)}[/cyan]")

    if errors:
        console.print("\n[yellow]Errors:[/yellow]")
        for error in errors[:10]:  # Show first 10 errors
            console.print(f"  [red]• {error.get('prompt_id', 'unknown')}: {error.get('message', error.get('error'))}[/red]")


if __name__ == "__main__":
    main()
