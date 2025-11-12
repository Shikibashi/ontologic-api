#!/usr/bin/env python3
"""
Chat History Maintenance CLI

Command-line interface for chat history batch processing, cleanup, and migration utilities.
Provides easy access to maintenance operations for chat data.
"""

import asyncio
import argparse
import json
import sys
from functools import lru_cache
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.chat_batch_processor import (
    ChatBatchProcessor, BatchProcessingProgress, batch_process_chat_vectors, batch_upload_to_qdrant
)
from app.utils.chat_cleanup import (
    ChatCleanupUtility, RetentionPolicy, cleanup_expired_chat_data, 
    cleanup_oversized_chat_sessions, cleanup_orphaned_chat_data
)
from app.utils.chat_migration import (
    ChatMigrationUtility, export_session_data, backup_all_chat_data, restore_chat_data
)
from app.core.logger import log
from app.services.chat_qdrant_service import ChatQdrantService
from app.services.llm_manager import LLMManager
from app.services.qdrant_manager import QdrantManager


@lru_cache()
def get_cli_chat_qdrant_service() -> ChatQdrantService:
    """Create or return a cached ChatQdrantService for CLI operations."""
    llm_manager = LLMManager()
    qdrant_manager = QdrantManager(llm_manager=llm_manager)
    return ChatQdrantService(qdrant_client=qdrant_manager.qclient, llm_manager=llm_manager)


def progress_callback(progress: BatchProcessingProgress):
    """Progress callback for batch operations."""
    percent = (progress.processed_items / progress.total_items) * 100 if progress.total_items > 0 else 0
    print(f"Progress: {progress.processed_items}/{progress.total_items} ({percent:.1f}%) - "
          f"Batch {progress.current_batch}/{progress.total_batches} - {progress.current_operation}")


async def cmd_batch_vectors(args):
    """Process chat messages to generate vectors in batches."""
    print(f"Starting batch vector processing...")
    print(f"Session ID: {args.session_id or 'All sessions'}")
    print(f"Batch size: {args.batch_size}")
    print(f"Max concurrent: {args.max_concurrent}")
    qdrant_service = get_cli_chat_qdrant_service()
    
    result = await batch_process_chat_vectors(
        session_id=args.session_id,
        batch_size=args.batch_size,
        max_concurrent=args.max_concurrent,
        qdrant_service=qdrant_service,
        progress_callback=progress_callback if args.verbose else None
    )
    
    print(f"\nBatch vector processing completed:")
    print(f"  Total processed: {result.total_processed}")
    print(f"  Successful: {result.successful}")
    print(f"  Failed: {result.failed}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    
    if result.errors and args.verbose:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors[:10]:  # Show first 10 errors
            print(f"  - {error}")
        if len(result.errors) > 10:
            print(f"  ... and {len(result.errors) - 10} more errors")


async def cmd_batch_upload(args):
    """Upload chat messages to Qdrant in batches."""
    print(f"Starting batch Qdrant upload...")
    print(f"Session ID: {args.session_id or 'All sessions'}")
    print(f"Batch size: {args.batch_size}")
    print(f"Max concurrent: {args.max_concurrent}")
    qdrant_service = get_cli_chat_qdrant_service()
    
    result = await batch_upload_to_qdrant(
        session_id=args.session_id,
        batch_size=args.batch_size,
        max_concurrent=args.max_concurrent,
        qdrant_service=qdrant_service,
        progress_callback=progress_callback if args.verbose else None
    )
    
    print(f"\nBatch Qdrant upload completed:")
    print(f"  Total processed: {result.total_processed}")
    print(f"  Successful: {result.successful}")
    print(f"  Failed: {result.failed}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    
    if result.errors and args.verbose:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors[:10]:
            print(f"  - {error}")
        if len(result.errors) > 10:
            print(f"  ... and {len(result.errors) - 10} more errors")


async def cmd_cleanup_expired(args):
    """Clean up expired chat data."""
    print(f"Starting cleanup of expired chat data...")
    print(f"Max age: {args.max_age_days} days")
    
    result = await cleanup_expired_chat_data(
        max_age_days=args.max_age_days
    )
    
    print(f"\nExpired data cleanup completed:")
    print(f"  Operation: {result.operation}")
    print(f"  Conversations deleted: {result.conversations_deleted}")
    print(f"  Messages deleted: {result.messages_deleted}")
    print(f"  Qdrant points deleted: {result.qdrant_points_deleted}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    
    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  - {error}")


async def cmd_cleanup_oversized(args):
    """Clean up oversized chat sessions."""
    print(f"Starting cleanup of oversized chat sessions...")
    print(f"Max messages per session: {args.max_messages}")
    print(f"Max conversations per session: {args.max_conversations}")
    
    result = await cleanup_oversized_chat_sessions(
        max_messages=args.max_messages,
        max_conversations=args.max_conversations
    )
    
    print(f"\nOversized sessions cleanup completed:")
    print(f"  Operation: {result.operation}")
    print(f"  Conversations deleted: {result.conversations_deleted}")
    print(f"  Messages deleted: {result.messages_deleted}")
    print(f"  Qdrant points deleted: {result.qdrant_points_deleted}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    
    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  - {error}")


async def cmd_cleanup_orphaned(args):
    """Clean up orphaned chat data."""
    print(f"Starting cleanup of orphaned chat data...")
    
    result = await cleanup_orphaned_chat_data()
    
    print(f"\nOrphaned data cleanup completed:")
    print(f"  Operation: {result.operation}")
    print(f"  Conversations deleted: {result.conversations_deleted}")
    print(f"  Messages deleted: {result.messages_deleted}")
    print(f"  Qdrant points deleted: {result.qdrant_points_deleted}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    
    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  - {error}")


async def cmd_cleanup_stats(args):
    """Show cleanup statistics."""
    print("Getting cleanup statistics...")
    
    policy = RetentionPolicy(
        max_age_days=args.max_age_days,
        max_messages_per_session=args.max_messages,
        max_conversations_per_session=args.max_conversations
    )
    
    cleanup_utility = ChatCleanupUtility(retention_policy=policy)
    stats = await cleanup_utility.get_cleanup_statistics()
    
    if "error" in stats:
        print(f"Error getting statistics: {stats['error']}")
        return
    
    print(f"\nCleanup Statistics:")
    print(f"  Total conversations: {stats['total_conversations']}")
    print(f"  Total messages: {stats['total_messages']}")
    print(f"  Expired sessions: {stats['expired_sessions']}")
    print(f"  Oversized sessions: {stats['oversized_sessions']}")
    print(f"  Orphaned messages: {stats['orphaned_messages']}")
    print(f"  Empty conversations: {stats['empty_conversations']}")
    
    print(f"\nRetention Policy:")
    policy_info = stats['retention_policy']
    print(f"  Max age: {policy_info['max_age_days']} days")
    print(f"  Max messages per session: {policy_info['max_messages_per_session']}")
    print(f"  Max conversations per session: {policy_info['max_conversations_per_session']}")
    
    print(f"\nRecommendations:")
    for recommendation in stats['recommendations']:
        print(f"  - {recommendation}")


async def cmd_export_session(args):
    """Export data for a specific session."""
    print(f"Exporting session data...")
    print(f"Session ID: {args.session_id}")
    print(f"Output file: {args.output}")
    print(f"Include vectors: {args.include_vectors}")
    
    result = await export_session_data(
        session_id=args.session_id,
        output_path=args.output,
        include_vectors=args.include_vectors
    )
    
    print(f"\nSession export completed:")
    print(f"  Operation: {result.operation}")
    print(f"  Conversations exported: {result.migrated_conversations}")
    print(f"  Messages exported: {result.migrated_messages}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    
    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  - {error}")


async def cmd_backup_all(args):
    """Backup all chat data."""
    print(f"Backing up all chat data...")
    print(f"Output file: {args.output}")
    print(f"Include vectors: {args.include_vectors}")
    
    result = await backup_all_chat_data(
        output_path=args.output,
        include_vectors=args.include_vectors
    )
    
    print(f"\nBackup completed:")
    print(f"  Operation: {result.operation}")
    print(f"  Conversations backed up: {result.migrated_conversations}")
    print(f"  Messages backed up: {result.migrated_messages}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    
    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  - {error}")


async def cmd_restore(args):
    """Restore chat data from backup."""
    print(f"Restoring chat data...")
    print(f"Input file: {args.input}")
    print(f"Overwrite existing: {args.overwrite}")
    
    result = await restore_chat_data(
        input_path=args.input,
        overwrite_existing=args.overwrite
    )
    
    print(f"\nRestore completed:")
    print(f"  Operation: {result.operation}")
    print(f"  Conversations restored: {result.migrated_conversations}")
    print(f"  Messages restored: {result.migrated_messages}")
    print(f"  Skipped items: {result.skipped_items}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    
    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  - {error}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Chat History Maintenance CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Batch process vectors for all sessions
  python scripts/chat_maintenance_cli.py batch-vectors --batch-size 50

  # Clean up data older than 30 days
  python scripts/chat_maintenance_cli.py cleanup-expired --max-age-days 30

  # Export a specific session
  python scripts/chat_maintenance_cli.py export-session --session-id user123 --output backup.json

  # Get cleanup statistics
  python scripts/chat_maintenance_cli.py cleanup-stats
        """
    )
    
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Batch processing commands
    batch_vectors_parser = subparsers.add_parser('batch-vectors', help='Process chat messages to generate vectors')
    batch_vectors_parser.add_argument('--session-id', help='Specific session ID to process')
    batch_vectors_parser.add_argument('--batch-size', type=int, default=100, help='Batch size (default: 100)')
    batch_vectors_parser.add_argument('--max-concurrent', type=int, default=5, help='Max concurrent operations (default: 5)')
    
    batch_upload_parser = subparsers.add_parser('batch-upload', help='Upload chat messages to Qdrant')
    batch_upload_parser.add_argument('--session-id', help='Specific session ID to upload')
    batch_upload_parser.add_argument('--batch-size', type=int, default=100, help='Batch size (default: 100)')
    batch_upload_parser.add_argument('--max-concurrent', type=int, default=5, help='Max concurrent operations (default: 5)')
    
    # Cleanup commands
    cleanup_expired_parser = subparsers.add_parser('cleanup-expired', help='Clean up expired chat data')
    cleanup_expired_parser.add_argument('--max-age-days', type=int, default=90, help='Maximum age in days (default: 90)')
    
    cleanup_oversized_parser = subparsers.add_parser('cleanup-oversized', help='Clean up oversized sessions')
    cleanup_oversized_parser.add_argument('--max-messages', type=int, default=10000, help='Max messages per session (default: 10000)')
    cleanup_oversized_parser.add_argument('--max-conversations', type=int, default=1000, help='Max conversations per session (default: 1000)')
    
    cleanup_orphaned_parser = subparsers.add_parser('cleanup-orphaned', help='Clean up orphaned data')
    
    cleanup_stats_parser = subparsers.add_parser('cleanup-stats', help='Show cleanup statistics')
    cleanup_stats_parser.add_argument('--max-age-days', type=int, default=90, help='Maximum age in days for stats (default: 90)')
    cleanup_stats_parser.add_argument('--max-messages', type=int, default=10000, help='Max messages per session for stats (default: 10000)')
    cleanup_stats_parser.add_argument('--max-conversations', type=int, default=1000, help='Max conversations per session for stats (default: 1000)')
    
    # Migration commands
    export_session_parser = subparsers.add_parser('export-session', help='Export data for a specific session')
    export_session_parser.add_argument('--session-id', required=True, help='Session ID to export')
    export_session_parser.add_argument('--output', required=True, help='Output JSON file path')
    export_session_parser.add_argument('--include-vectors', action='store_true', help='Include vector data')
    
    backup_all_parser = subparsers.add_parser('backup-all', help='Backup all chat data')
    backup_all_parser.add_argument('--output', required=True, help='Output JSON file path')
    backup_all_parser.add_argument('--include-vectors', action='store_true', help='Include vector data')
    
    restore_parser = subparsers.add_parser('restore', help='Restore chat data from backup')
    restore_parser.add_argument('--input', required=True, help='Input JSON file path')
    restore_parser.add_argument('--overwrite', action='store_true', help='Overwrite existing data')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Map commands to functions
    command_map = {
        'batch-vectors': cmd_batch_vectors,
        'batch-upload': cmd_batch_upload,
        'cleanup-expired': cmd_cleanup_expired,
        'cleanup-oversized': cmd_cleanup_oversized,
        'cleanup-orphaned': cmd_cleanup_orphaned,
        'cleanup-stats': cmd_cleanup_stats,
        'export-session': cmd_export_session,
        'backup-all': cmd_backup_all,
        'restore': cmd_restore,
    }
    
    command_func = command_map.get(args.command)
    if command_func:
        try:
            asyncio.run(command_func(args))
        except KeyboardInterrupt:
            print("\nOperation cancelled by user")
        except Exception as e:
            print(f"Error: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
    else:
        print(f"Unknown command: {args.command}")
        parser.print_help()


if __name__ == '__main__':
    main()

