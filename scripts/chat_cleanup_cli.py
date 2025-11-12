#!/usr/bin/env python3
"""
Chat history cleanup CLI tool.
Provides command-line interface for managing chat history data retention.
"""
import asyncio
import argparse
import json
import sys
from pathlib import Path

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.settings import Settings
from app.services.feature_flags import FeatureFlagService
from app.services.chat_config import ChatHistoryConfig
from app.services.chat_cleanup import ChatCleanupService

async def cleanup_expired_data(args):
    """Clean up expired chat history data."""
    settings = Settings()
    feature_flags = FeatureFlagService(settings)
    chat_config = ChatHistoryConfig(settings)
    cleanup_service = ChatCleanupService(chat_config, feature_flags)
    
    if args.dry_run:
        print("Performing dry run - no data will be deleted")
        stats = await cleanup_service.get_cleanup_stats()
        print(json.dumps(stats, indent=2))
    else:
        print("Starting cleanup of expired chat history data...")
        if not args.force:
            response = input("This will permanently delete expired data. Continue? (y/N): ")
            if response.lower() != 'y':
                print("Cleanup cancelled")
                return
        
        stats = await cleanup_service.cleanup_expired_sessions()
        print(json.dumps(stats, indent=2))

async def cleanup_session(args):
    """Clean up data for a specific session."""
    settings = Settings()
    feature_flags = FeatureFlagService(settings)
    chat_config = ChatHistoryConfig(settings)
    cleanup_service = ChatCleanupService(chat_config, feature_flags)
    
    print(f"Cleaning up session: {args.session_id}")
    if not args.force:
        response = input("This will permanently delete all data for this session. Continue? (y/N): ")
        if response.lower() != 'y':
            print("Cleanup cancelled")
            return
    
    stats = await cleanup_service.cleanup_session_data(args.session_id)
    print(json.dumps(stats, indent=2))

async def show_config(args):
    """Show current chat history configuration."""
    settings = Settings()
    feature_flags = FeatureFlagService(settings)
    chat_config = ChatHistoryConfig(settings)
    
    config_summary = chat_config.get_config_summary()
    feature_status = feature_flags.get_chat_history_status()
    
    print("Chat History Configuration:")
    print(json.dumps({
        "feature_status": feature_status,
        "configuration": config_summary
    }, indent=2))

async def show_stats(args):
    """Show cleanup statistics (dry run)."""
    settings = Settings()
    feature_flags = FeatureFlagService(settings)
    chat_config = ChatHistoryConfig(settings)
    cleanup_service = ChatCleanupService(chat_config, feature_flags)
    
    stats = await cleanup_service.get_cleanup_stats()
    print("Cleanup Statistics (Dry Run):")
    print(json.dumps(stats, indent=2))

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Chat history cleanup and management tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show current configuration
  python scripts/chat_cleanup_cli.py config
  
  # Show cleanup statistics (dry run)
  python scripts/chat_cleanup_cli.py stats
  
  # Perform dry run cleanup
  python scripts/chat_cleanup_cli.py cleanup --dry-run
  
  # Clean up expired data (with confirmation)
  python scripts/chat_cleanup_cli.py cleanup
  
  # Clean up expired data (no confirmation)
  python scripts/chat_cleanup_cli.py cleanup --force
  
  # Clean up specific session
  python scripts/chat_cleanup_cli.py session --session-id "user123" --force
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Config command
    config_parser = subparsers.add_parser('config', help='Show current configuration')
    
    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show cleanup statistics')
    
    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up expired data')
    cleanup_parser.add_argument('--dry-run', action='store_true', 
                               help='Show what would be deleted without actually deleting')
    cleanup_parser.add_argument('--force', action='store_true',
                               help='Skip confirmation prompt')
    
    # Session cleanup command
    session_parser = subparsers.add_parser('session', help='Clean up specific session')
    session_parser.add_argument('--session-id', required=True,
                               help='Session ID to clean up')
    session_parser.add_argument('--force', action='store_true',
                               help='Skip confirmation prompt')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Run the appropriate command
    if args.command == 'config':
        asyncio.run(show_config(args))
    elif args.command == 'stats':
        asyncio.run(show_stats(args))
    elif args.command == 'cleanup':
        asyncio.run(cleanup_expired_data(args))
    elif args.command == 'session':
        asyncio.run(cleanup_session(args))

if __name__ == '__main__':
    main()