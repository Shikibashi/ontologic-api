"""
Chat history data migration utilities.

Provides utilities for migrating chat data between environments,
backing up data, and performing data transformations safely.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_models import ChatMessage, ChatConversation, MessageRole
from app.core.database import AsyncSessionLocal
from app.core.logger import log
from app.services.chat_qdrant_service import ChatQdrantService


@dataclass
class MigrationResult:
    """Result of a migration operation."""
    operation: str
    source_conversations: int
    source_messages: int
    migrated_conversations: int
    migrated_messages: int
    skipped_items: int
    errors: List[str]
    duration_seconds: float
    migration_id: str


@dataclass
class BackupMetadata:
    """Metadata for chat history backups."""
    backup_id: str
    created_at: datetime
    source_environment: str
    total_conversations: int
    total_messages: int
    session_ids: List[str]
    format_version: str = "1.0"


class ChatMigrationUtility:
    """
    Utility for migrating and backing up chat history data.
    
    Handles data export/import, environment migrations, and backup operations
    with proper data validation and integrity checks.
    """
    
    def __init__(self, qdrant_service: Optional[ChatQdrantService] = None):
        """
        Initialize migration utility.
        
        Args:
            qdrant_service: Optional Qdrant service for vector operations
        """
        self.qdrant_service = qdrant_service
    
    async def export_chat_data(
        self,
        output_path: str,
        session_ids: Optional[List[str]] = None,
        include_vectors: bool = False
    ) -> MigrationResult:
        """
        Export chat data to JSON format for backup or migration.
        
        Args:
            output_path: Path to output JSON file
            session_ids: Optional list of session IDs to export
            include_vectors: Whether to include vector data from Qdrant
            
        Returns:
            MigrationResult with export statistics
        """
        migration_id = f"export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        start_time = datetime.now(timezone.utc)
        
        try:
            conversations_exported = 0
            messages_exported = 0
            errors = []
            
            # Prepare export data structure
            export_data = {
                "metadata": BackupMetadata(
                    backup_id=migration_id,
                    created_at=start_time,
                    source_environment="current",
                    total_conversations=0,
                    total_messages=0,
                    session_ids=session_ids or []
                ).__dict__,
                "conversations": [],
                "messages": []
            }
            
            async with AsyncSessionLocal() as db_session:
                # Export conversations
                conversations = await self._get_conversations_for_export(db_session, session_ids)
                
                for conversation in conversations:
                    try:
                        conv_data = {
                            "conversation_id": conversation.conversation_id,
                            "session_id": conversation.session_id,
                            "title": conversation.title,
                            "philosopher_collection": conversation.philosopher_collection,
                            "created_at": conversation.created_at.isoformat(),
                            "updated_at": conversation.updated_at.isoformat()
                        }
                        export_data["conversations"].append(conv_data)
                        conversations_exported += 1
                        
                    except Exception as e:
                        errors.append(f"Error exporting conversation {conversation.conversation_id}: {e}")
                
                # Export messages
                messages = await self._get_messages_for_export(db_session, session_ids)
                
                for message in messages:
                    try:
                        msg_data = {
                            "message_id": message.message_id,
                            "conversation_id": message.conversation_id,
                            "session_id": message.session_id,
                            "role": message.role.value,
                            "content": message.content,
                            "philosopher_collection": message.philosopher_collection,
                            "qdrant_point_id": message.qdrant_point_id,
                            "created_at": message.created_at.isoformat()
                        }
                        
                        # Include vector data if requested
                        if include_vectors and message.qdrant_point_id and self.qdrant_service:
                            try:
                                vector_data = await self.qdrant_service.get_point_by_id(message.qdrant_point_id)
                                if vector_data:
                                    msg_data["vector_data"] = vector_data
                            except Exception as e:
                                errors.append(f"Error getting vector for message {message.message_id}: {e}")
                        
                        export_data["messages"].append(msg_data)
                        messages_exported += 1
                        
                    except Exception as e:
                        errors.append(f"Error exporting message {message.message_id}: {e}")
            
            # Update metadata
            export_data["metadata"]["total_conversations"] = conversations_exported
            export_data["metadata"]["total_messages"] = messages_exported
            
            # Write to file
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = MigrationResult(
                operation="export_chat_data",
                source_conversations=conversations_exported,
                source_messages=messages_exported,
                migrated_conversations=conversations_exported,
                migrated_messages=messages_exported,
                skipped_items=0,
                errors=errors,
                duration_seconds=duration,
                migration_id=migration_id
            )
            
            log.info(f"Chat data export completed: {conversations_exported} conversations, "
                    f"{messages_exported} messages exported to {output_path}")
            
            return result
            
        except Exception as e:
            log.error(f"Chat data export failed: {e}")
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            return MigrationResult(
                operation="export_chat_data",
                source_conversations=0,
                source_messages=0,
                migrated_conversations=0,
                migrated_messages=0,
                skipped_items=0,
                errors=[str(e)],
                duration_seconds=duration,
                migration_id=migration_id
            )
    
    async def import_chat_data(
        self,
        input_path: str,
        overwrite_existing: bool = False,
        validate_data: bool = True
    ) -> MigrationResult:
        """
        Import chat data from JSON format.
        
        Args:
            input_path: Path to input JSON file
            overwrite_existing: Whether to overwrite existing data
            validate_data: Whether to validate data before import
            
        Returns:
            MigrationResult with import statistics
        """
        migration_id = f"import_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        start_time = datetime.now(timezone.utc)
        
        try:
            # Load import data
            with open(input_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            # Validate format
            if validate_data:
                validation_errors = await self._validate_import_data(import_data)
                if validation_errors:
                    return MigrationResult(
                        operation="import_chat_data",
                        source_conversations=0,
                        source_messages=0,
                        migrated_conversations=0,
                        migrated_messages=0,
                        skipped_items=0,
                        errors=validation_errors,
                        duration_seconds=0,
                        migration_id=migration_id
                    )
            
            conversations_imported = 0
            messages_imported = 0
            skipped_items = 0
            errors = []
            
            async with AsyncSessionLocal() as db_session:
                # Import conversations
                for conv_data in import_data.get("conversations", []):
                    try:
                        # Check if conversation exists
                        existing_conv = await self._get_existing_conversation(
                            db_session, conv_data["conversation_id"]
                        )
                        
                        if existing_conv and not overwrite_existing:
                            skipped_items += 1
                            continue
                        
                        # Create or update conversation
                        if existing_conv and overwrite_existing:
                            conversation = existing_conv
                            conversation.title = conv_data.get("title")
                            conversation.philosopher_collection = conv_data.get("philosopher_collection")
                            conversation.updated_at = datetime.fromisoformat(conv_data["updated_at"])
                        else:
                            conversation = ChatConversation(
                                conversation_id=conv_data["conversation_id"],
                                session_id=conv_data["session_id"],
                                title=conv_data.get("title"),
                                philosopher_collection=conv_data.get("philosopher_collection"),
                                created_at=datetime.fromisoformat(conv_data["created_at"]),
                                updated_at=datetime.fromisoformat(conv_data["updated_at"])
                            )
                        
                        db_session.add(conversation)
                        conversations_imported += 1
                        
                    except Exception as e:
                        errors.append(f"Error importing conversation {conv_data.get('conversation_id')}: {e}")
                
                # Commit conversations first
                await db_session.commit()
                
                # Import messages
                for msg_data in import_data.get("messages", []):
                    try:
                        # Check if message exists
                        existing_msg = await self._get_existing_message(
                            db_session, msg_data["message_id"]
                        )
                        
                        if existing_msg and not overwrite_existing:
                            skipped_items += 1
                            continue
                        
                        # Create or update message
                        if existing_msg and overwrite_existing:
                            message = existing_msg
                            message.content = msg_data["content"]
                            message.philosopher_collection = msg_data.get("philosopher_collection")
                            message.qdrant_point_id = msg_data.get("qdrant_point_id")
                        else:
                            message = ChatMessage(
                                message_id=msg_data["message_id"],
                                conversation_id=msg_data["conversation_id"],
                                session_id=msg_data["session_id"],
                                role=MessageRole(msg_data["role"]),
                                content=msg_data["content"],
                                philosopher_collection=msg_data.get("philosopher_collection"),
                                qdrant_point_id=msg_data.get("qdrant_point_id"),
                                created_at=datetime.fromisoformat(msg_data["created_at"])
                            )
                        
                        db_session.add(message)
                        messages_imported += 1
                        
                        # Import vector data if available
                        if "vector_data" in msg_data and self.qdrant_service:
                            try:
                                await self.qdrant_service.import_point_data(
                                    msg_data["qdrant_point_id"],
                                    msg_data["vector_data"]
                                )
                            except Exception as e:
                                errors.append(f"Error importing vector for message {msg_data['message_id']}: {e}")
                        
                    except Exception as e:
                        errors.append(f"Error importing message {msg_data.get('message_id')}: {e}")
                
                # Commit messages
                await db_session.commit()
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = MigrationResult(
                operation="import_chat_data",
                source_conversations=len(import_data.get("conversations", [])),
                source_messages=len(import_data.get("messages", [])),
                migrated_conversations=conversations_imported,
                migrated_messages=messages_imported,
                skipped_items=skipped_items,
                errors=errors,
                duration_seconds=duration,
                migration_id=migration_id
            )
            
            log.info(f"Chat data import completed: {conversations_imported} conversations, "
                    f"{messages_imported} messages imported from {input_path}")
            
            return result
            
        except Exception as e:
            log.error(f"Chat data import failed: {e}")
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            return MigrationResult(
                operation="import_chat_data",
                source_conversations=0,
                source_messages=0,
                migrated_conversations=0,
                migrated_messages=0,
                skipped_items=0,
                errors=[str(e)],
                duration_seconds=duration,
                migration_id=migration_id
            )
    
    async def migrate_session_data(
        self,
        old_session_id: str,
        new_session_id: str,
        update_qdrant: bool = True
    ) -> MigrationResult:
        """
        Migrate data from one session ID to another.
        
        Args:
            old_session_id: Source session ID
            new_session_id: Target session ID
            update_qdrant: Whether to update Qdrant metadata
            
        Returns:
            MigrationResult with migration statistics
        """
        migration_id = f"migrate_session_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        start_time = datetime.now(timezone.utc)
        
        try:
            conversations_migrated = 0
            messages_migrated = 0
            errors = []
            
            async with AsyncSessionLocal() as db_session:
                # Update conversations
                conversations_stmt = select(ChatConversation).where(
                    ChatConversation.session_id == old_session_id
                )
                conversations_result = await db_session.execute(conversations_stmt)
                conversations = conversations_result.scalars().all()
                
                for conversation in conversations:
                    conversation.session_id = new_session_id
                    db_session.add(conversation)
                    conversations_migrated += 1
                
                # Update messages
                messages_stmt = select(ChatMessage).where(
                    ChatMessage.session_id == old_session_id
                )
                messages_result = await db_session.execute(messages_stmt)
                messages = messages_result.scalars().all()
                
                qdrant_point_ids = []
                for message in messages:
                    message.session_id = new_session_id
                    db_session.add(message)
                    messages_migrated += 1
                    
                    if message.qdrant_point_id:
                        qdrant_point_ids.append(message.qdrant_point_id)
                
                await db_session.commit()
                
                # Update Qdrant metadata
                if update_qdrant and self.qdrant_service and qdrant_point_ids:
                    try:
                        updated_points = await self.qdrant_service.update_session_metadata(
                            qdrant_point_ids, old_session_id, new_session_id
                        )
                        log.info(f"Updated {updated_points} Qdrant points with new session ID")
                    except Exception as e:
                        errors.append(f"Error updating Qdrant metadata: {e}")
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = MigrationResult(
                operation="migrate_session_data",
                source_conversations=conversations_migrated,
                source_messages=messages_migrated,
                migrated_conversations=conversations_migrated,
                migrated_messages=messages_migrated,
                skipped_items=0,
                errors=errors,
                duration_seconds=duration,
                migration_id=migration_id
            )
            
            log.info(f"Session migration completed: {conversations_migrated} conversations, "
                    f"{messages_migrated} messages migrated from {old_session_id} to {new_session_id}")
            
            return result
            
        except Exception as e:
            log.error(f"Session migration failed: {e}")
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            return MigrationResult(
                operation="migrate_session_data",
                source_conversations=0,
                source_messages=0,
                migrated_conversations=0,
                migrated_messages=0,
                skipped_items=0,
                errors=[str(e)],
                duration_seconds=duration,
                migration_id=migration_id
            )
    
    async def _get_conversations_for_export(
        self, 
        db_session: AsyncSession, 
        session_ids: Optional[List[str]]
    ) -> List[ChatConversation]:
        """Get conversations for export."""
        statement = select(ChatConversation)
        
        if session_ids:
            statement = statement.where(ChatConversation.session_id.in_(session_ids))
        
        statement = statement.order_by(ChatConversation.created_at.asc())
        
        result = await db_session.execute(statement)
        return result.scalars().all()
    
    async def _get_messages_for_export(
        self, 
        db_session: AsyncSession, 
        session_ids: Optional[List[str]]
    ) -> List[ChatMessage]:
        """Get messages for export."""
        statement = select(ChatMessage)
        
        if session_ids:
            statement = statement.where(ChatMessage.session_id.in_(session_ids))
        
        statement = statement.order_by(ChatMessage.created_at.asc())
        
        result = await db_session.execute(statement)
        return result.scalars().all()
    
    async def _get_existing_conversation(
        self, 
        db_session: AsyncSession, 
        conversation_id: str
    ) -> Optional[ChatConversation]:
        """Check if conversation exists."""
        statement = select(ChatConversation).where(
            ChatConversation.conversation_id == conversation_id
        )
        result = await db_session.execute(statement)
        return result.scalars().first()
    
    async def _get_existing_message(
        self, 
        db_session: AsyncSession, 
        message_id: str
    ) -> Optional[ChatMessage]:
        """Check if message exists."""
        statement = select(ChatMessage).where(ChatMessage.message_id == message_id)
        result = await db_session.execute(statement)
        return result.scalars().first()
    
    async def _validate_import_data(self, import_data: Dict[str, Any]) -> List[str]:
        """Validate import data format."""
        errors = []
        
        # Check required fields
        if "metadata" not in import_data:
            errors.append("Missing metadata section")
        
        if "conversations" not in import_data:
            errors.append("Missing conversations section")
        
        if "messages" not in import_data:
            errors.append("Missing messages section")
        
        # Validate conversations
        for i, conv in enumerate(import_data.get("conversations", [])):
            required_fields = ["conversation_id", "session_id", "created_at", "updated_at"]
            for field in required_fields:
                if field not in conv:
                    errors.append(f"Conversation {i}: Missing required field '{field}'")
        
        # Validate messages
        for i, msg in enumerate(import_data.get("messages", [])):
            required_fields = ["message_id", "conversation_id", "session_id", "role", "content", "created_at"]
            for field in required_fields:
                if field not in msg:
                    errors.append(f"Message {i}: Missing required field '{field}'")
            
            # Validate role
            if msg.get("role") not in ["user", "assistant"]:
                errors.append(f"Message {i}: Invalid role '{msg.get('role')}'")
        
        return errors


# Convenience functions for common migration operations

async def export_session_data(
    session_id: str,
    output_path: str,
    include_vectors: bool = False
) -> MigrationResult:
    """
    Export data for a specific session.
    
    Args:
        session_id: Session ID to export
        output_path: Output file path
        include_vectors: Whether to include vector data
        
    Returns:
        MigrationResult with export statistics
    """
    migration_utility = ChatMigrationUtility()
    return await migration_utility.export_chat_data(
        output_path=output_path,
        session_ids=[session_id],
        include_vectors=include_vectors
    )


async def backup_all_chat_data(
    output_path: str,
    include_vectors: bool = False
) -> MigrationResult:
    """
    Backup all chat data to a file.
    
    Args:
        output_path: Output file path
        include_vectors: Whether to include vector data
        
    Returns:
        MigrationResult with backup statistics
    """
    migration_utility = ChatMigrationUtility()
    return await migration_utility.export_chat_data(
        output_path=output_path,
        session_ids=None,
        include_vectors=include_vectors
    )


async def restore_chat_data(
    input_path: str,
    overwrite_existing: bool = False
) -> MigrationResult:
    """
    Restore chat data from a backup file.
    
    Args:
        input_path: Input file path
        overwrite_existing: Whether to overwrite existing data
        
    Returns:
        MigrationResult with restore statistics
    """
    migration_utility = ChatMigrationUtility()
    return await migration_utility.import_chat_data(
        input_path=input_path,
        overwrite_existing=overwrite_existing,
        validate_data=True
    )