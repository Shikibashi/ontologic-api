#!/usr/bin/env python3
"""
Database migration utility script for ontologic-api.

This script provides utilities for managing database migrations using Alembic.
"""

import os
import sys
import subprocess
from pathlib import Path

# Add the app directory to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def run_command(command: list[str]) -> int:
    """Run a command and return the exit code."""
    print(f"Running: {' '.join(command)}")
    result = subprocess.run(command, cwd=project_root)
    return result.returncode

def migrate_up():
    """Run all pending migrations."""
    return run_command(["alembic", "upgrade", "head"])

def migrate_down(revision: str = None):
    """Downgrade to a specific revision or one step back."""
    if revision:
        return run_command(["alembic", "downgrade", revision])
    else:
        return run_command(["alembic", "downgrade", "-1"])

def create_migration(message: str):
    """Create a new migration with autogenerate."""
    return run_command(["alembic", "revision", "--autogenerate", "-m", message])

def show_current():
    """Show current migration status."""
    return run_command(["alembic", "current"])

def show_history():
    """Show migration history."""
    return run_command(["alembic", "history"])

def main():
    """Main CLI interface."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/migrate_db.py <command> [args]")
        print("Commands:")
        print("  up                    - Run all pending migrations")
        print("  down [revision]       - Downgrade to revision or one step back")
        print("  create <message>      - Create new migration")
        print("  current               - Show current migration status")
        print("  history               - Show migration history")
        return 1

    command = sys.argv[1]
    
    if command == "up":
        return migrate_up()
    elif command == "down":
        revision = sys.argv[2] if len(sys.argv) > 2 else None
        return migrate_down(revision)
    elif command == "create":
        if len(sys.argv) < 3:
            print("Error: Migration message required")
            return 1
        message = " ".join(sys.argv[2:])
        return create_migration(message)
    elif command == "current":
        return show_current()
    elif command == "history":
        return show_history()
    else:
        print(f"Unknown command: {command}")
        return 1

if __name__ == "__main__":
    sys.exit(main())