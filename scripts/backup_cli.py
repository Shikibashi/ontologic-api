#!/usr/bin/env python3
"""
Command-line interface for Qdrant backup operations.

This script provides CLI commands for backing up Qdrant collections
from production to local development environments.
"""

import asyncio
import argparse
import json
import os
import sys
from typing import Dict, List, Optional

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.qdrant_backup_service import QdrantBackupService
from app.core.logger import log


class BackupCLI:
    """Command-line interface for backup operations."""
    
    def __init__(self):
        """Initialize the CLI with backup service."""
        self.backup_service = None
    
    async def initialize_service(self):
        """Initialize the backup service with configuration."""
        if self.backup_service is not None:
            return
        
        # Production Qdrant configuration
        production_config = {
            "url": os.environ.get("QDRANT_PRODUCTION_URL", "https://qdrant.ontologicai.com"),
            "api_key_env": "QDRANT_API_KEY",
            "timeout": 900,  # 15 minutes timeout for very large collections
            "retry_attempts": 3,
            "backup_batch_size": 100  # Smaller batches for reliability
        }

        # Local Qdrant configuration
        local_config = {
            "url": os.environ.get("QDRANT_LOCAL_URL", "http://127.0.0.1:6333"),
            "api_key_env": "QDRANT_LOCAL_API_KEY",  # Optional for local
            "timeout": 900,  # 15 minutes timeout for very large collections
            "retry_attempts": 3
        }
        
        try:
            self.backup_service = QdrantBackupService(production_config, local_config)
            print("✓ Backup service initialized successfully")
        except Exception as e:
            print(f"✗ Failed to initialize backup service: {e}")
            sys.exit(1)
    
    async def check_connections(self):
        """Check the health of Qdrant connections."""
        await self.initialize_service()
        
        print("Checking Qdrant connections...")
        
        try:
            production_valid, local_valid = await self.backup_service.validate_connections()
            
            print(f"Production Qdrant: {'✓ Connected' if production_valid else '✗ Failed'}")
            print(f"Local Qdrant: {'✓ Connected' if local_valid else '✗ Failed'}")
            
            if production_valid and local_valid:
                print("✓ All connections are healthy")
                return True
            else:
                print("✗ Some connections failed")
                return False
                
        except Exception as e:
            print(f"✗ Connection check failed: {e}")
            return False
    
    async def list_collections(self, source: str = "production"):
        """List collections in production or local Qdrant."""
        await self.initialize_service()
        
        try:
            if source == "production":
                collections = await self.backup_service.list_collections(self.backup_service.production_client)
                print(f"\nProduction Collections ({len(collections)}):")
            else:
                collections = await self.backup_service.list_collections(self.backup_service.local_client)
                print(f"\nLocal Collections ({len(collections)}):")
            
            for i, collection in enumerate(collections, 1):
                print(f"  {i:2d}. {collection}")
            
            return collections
            
        except Exception as e:
            print(f"✗ Failed to list {source} collections: {e}")
            return []
    
    async def get_collection_info(self, collection_name: str, source: str = "production"):
        """Get detailed information about a collection."""
        await self.initialize_service()
        
        try:
            client = (self.backup_service.production_client if source == "production" 
                     else self.backup_service.local_client)
            
            info = await self.backup_service.get_collection_info(collection_name, client)
            
            print(f"\nCollection Info: {collection_name} ({source})")
            print(f"  Points: {info.points_count:,}")
            print(f"  Vectors: {info.vectors_count:,}")
            print(f"  Indexed Vectors: {info.indexed_vectors_count:,}")
            print(f"  Segments: {info.segments_count}")
            
            return info
            
        except Exception as e:
            print(f"✗ Failed to get collection info: {e}")
            return None
    
    async def backup_snapshot(
        self,
        collection: str,
        target: Optional[str] = None,
        overwrite: bool = False
    ):
        """Backup a single collection using snapshot API (recommended method)."""
        await self.initialize_service()

        print(f"Starting snapshot-based backup of collection '{collection}'...")

        try:
            result = await self.backup_service.backup_collection_snapshot(
                collection_name=collection,
                target_name=target,
                overwrite=overwrite
            )

            if result['success']:
                print(f"\n✓ Snapshot backup completed successfully!")
                print(f"  Collection: {result['source_collection']} -> {result['target_collection']}")
                print(f"  Points: {result['source_points']:,} -> {result['target_points']:,}")
                print(f"  Method: {result['method']}")
            else:
                print(f"\n✗ Snapshot backup failed!")
                print(f"  Error: {result.get('error', 'Unknown error')}")

        except Exception as e:
            print(f"✗ Snapshot backup failed: {e}")
            import traceback
            traceback.print_exc()

    async def backup_collections(
        self,
        collections: Optional[List[str]] = None,
        collection_filter: Optional[str] = None,
        target_prefix: Optional[str] = None,
        overwrite: bool = False,
        philosophy_only: bool = True
    ):
        """Backup collections from production to local."""
        await self.initialize_service()
        
        print("Starting backup operation...")
        
        # Progress callback
        def progress_callback(current, total):
            percent = (current / total) * 100 if total > 0 else 0
            print(f"  Progress: {current:,}/{total:,} points ({percent:.1f}%)")
        
        try:
            if philosophy_only and not collections and not collection_filter:
                print("Backing up all philosophy collections...")
                result = await self.backup_service.backup_philosophy_collections(
                    target_prefix=target_prefix,
                    overwrite=overwrite
                )
            else:
                print(f"Backing up specific collections...")
                result = await self.backup_service.backup_collections(
                    collections=collections,
                    collection_filter=collection_filter,
                    target_prefix=target_prefix,
                    overwrite=overwrite
                )
            
            # Print results
            print(f"\n✓ Backup completed!")
            print(f"  Status: {result['status']}")
            print(f"  Total Collections: {result['total_collections']}")
            print(f"  Successful: {result['successful_backups']}")
            print(f"  Failed: {result['failed_backups']}")
            print(f"  Total Points: {result['total_source_points']:,} -> {result['total_target_points']:,}")
            print(f"  Duration: {result.get('duration_seconds', 0):.1f} seconds")
            
            if result['errors']:
                print(f"\nErrors:")
                for error in result['errors']:
                    print(f"  - {error}")
            
            # Print collection details
            if result.get('collections'):
                print(f"\nCollection Details:")
                for col_result in result['collections']:
                    status = "✓" if col_result['success'] else "✗"
                    points = f"{col_result.get('source_points', 0):,} -> {col_result.get('target_points', 0):,}"
                    print(f"  {status} {col_result['source_collection']} -> {col_result['target_collection']} ({points} points)")
            
            return result
            
        except Exception as e:
            print(f"✗ Backup failed: {e}")
            return None
    
    async def validate_backup(self, source_collection: str, target_collection: str, sample_size: int = 100):
        """Validate backup integrity."""
        await self.initialize_service()
        
        print(f"Validating backup: {source_collection} -> {target_collection}")
        
        try:
            result = await self.backup_service.validate_backup_integrity(
                source_collection=source_collection,
                target_collection=target_collection,
                sample_size=sample_size
            )
            
            print(f"\nValidation Result: {'✓ PASSED' if result['valid'] else '✗ FAILED'}")
            
            checks = result['checks']
            print(f"  Source exists: {'✓' if checks['source_exists'] else '✗'}")
            print(f"  Target exists: {'✓' if checks['target_exists'] else '✗'}")
            print(f"  Point count match: {'✓' if checks['point_count_match'] else '✗'}")
            print(f"  Source points: {checks['source_points']:,}")
            print(f"  Target points: {checks['target_points']:,}")
            print(f"  Config match: {'✓' if checks['config_match'] else '✗'}")
            
            if result['errors']:
                print(f"\nErrors:")
                for error in result['errors']:
                    print(f"  - {error}")
            
            if result['warnings']:
                print(f"\nWarnings:")
                for warning in result['warnings']:
                    print(f"  - {warning}")
            
            return result
            
        except Exception as e:
            print(f"✗ Validation failed: {e}")
            return None
    
    async def cleanup(self):
        """Clean up resources."""
        if self.backup_service:
            await self.backup_service.close()


async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Qdrant Backup CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Health check command
    health_parser = subparsers.add_parser("health", help="Check Qdrant connections")
    
    # List collections command
    list_parser = subparsers.add_parser("list", help="List collections")
    list_parser.add_argument("--source", choices=["production", "local"], default="production",
                           help="Source to list collections from")
    
    # Collection info command
    info_parser = subparsers.add_parser("info", help="Get collection information")
    info_parser.add_argument("collection", help="Collection name")
    info_parser.add_argument("--source", choices=["production", "local"], default="production",
                           help="Source to get info from")
    
    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Backup collections")
    backup_parser.add_argument("--collections", nargs="+", help="Specific collections to backup")
    backup_parser.add_argument("--filter", help="Collection name filter pattern")
    backup_parser.add_argument("--prefix", help="Target collection name prefix")
    backup_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing collections")
    backup_parser.add_argument("--all", action="store_true", help="Backup all collections (not just philosophy)")

    # Snapshot backup command (faster and more reliable)
    snapshot_parser = subparsers.add_parser("snapshot", help="Backup a single collection using snapshots (recommended)")
    snapshot_parser.add_argument("collection", help="Collection name to backup")
    snapshot_parser.add_argument("--target", help="Target collection name (defaults to source name)")
    snapshot_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing collection")

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate backup integrity")
    validate_parser.add_argument("source_collection", help="Source collection name")
    validate_parser.add_argument("target_collection", help="Target collection name")
    validate_parser.add_argument("--sample-size", type=int, default=100, help="Sample size for validation")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    cli = BackupCLI()
    
    try:
        if args.command == "health":
            await cli.check_connections()
        
        elif args.command == "list":
            await cli.list_collections(args.source)
        
        elif args.command == "info":
            await cli.get_collection_info(args.collection, args.source)
        
        elif args.command == "backup":
            await cli.backup_collections(
                collections=args.collections,
                collection_filter=args.filter,
                target_prefix=args.prefix,
                overwrite=args.overwrite,
                philosophy_only=not args.all
            )

        elif args.command == "snapshot":
            await cli.backup_snapshot(
                args.collection,
                target=args.target,
                overwrite=args.overwrite
            )

        elif args.command == "validate":
            await cli.validate_backup(
                args.source_collection,
                args.target_collection,
                args.sample_size
            )
        
    except KeyboardInterrupt:
        print("\n✗ Operation cancelled by user")
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
    finally:
        await cli.cleanup()


if __name__ == "__main__":
    asyncio.run(main())