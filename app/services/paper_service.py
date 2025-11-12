import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_models import PaperDraft, DraftStatus, ReviewSuggestion
from app.core.database import get_session, AsyncSessionLocal
from app.core.draft_options import DraftCreateOptions
from app.core.logger import log


class PaperDraftService:
    """
    Service layer for managing paper drafts and their lifecycle.

    Handles creation, updates, status tracking, and section management.
    """

    @staticmethod
    async def create_draft(
        title: str,
        topic: str,
        collection: str,
        immersive_mode: bool = False,
        temperature: float = 0.3,
        workflow_metadata: Optional[Dict[str, Any]] = None
    ) -> PaperDraft:
        """Create a new paper draft using legacy signature."""
        options = DraftCreateOptions(
            title=title,
            topic=topic,
            collection=collection,
            immersive_mode=immersive_mode,
            temperature=temperature,
            workflow_metadata=workflow_metadata
        )
        return await PaperDraftService.create_draft_from_options(options)
    
    @staticmethod
    async def create_draft_from_options(options: DraftCreateOptions) -> PaperDraft:
        """Create a new paper draft from DraftCreateOptions."""
        draft_id = str(uuid.uuid4())
        
        draft = PaperDraft(
            draft_id=draft_id,
            **options.to_dict(),
            status=DraftStatus.CREATED
        )
        
        async with AsyncSessionLocal() as session:
            try:
                session.add(draft)
                await session.commit()
                await session.refresh(draft)
                log.info(f"Created new paper draft: {draft_id} - {options.title}")
                return draft
            except Exception as e:
                await session.rollback()
                log.error(f"Failed to create draft: {e}")
                raise

    @staticmethod
    async def get_draft(draft_id: str) -> Optional[PaperDraft]:
        """Get a draft by ID."""
        async with AsyncSessionLocal() as session:
            statement = select(PaperDraft).where(PaperDraft.draft_id == draft_id)
            result = await session.execute(statement)
            return result.scalars().first()

    @staticmethod
    async def update_draft_status(
        draft_id: str,
        status: DraftStatus,
        session: Optional[AsyncSession] = None
    ) -> bool:
        """Update the status of a draft."""
        async def _update(session: AsyncSession):
            statement = select(PaperDraft).where(PaperDraft.draft_id == draft_id)
            result = await session.execute(statement)
            draft = result.scalars().first()

            if not draft:
                return False

            draft.status = status
            # Note: updated_at is automatically set by SQLAlchemy onupdate trigger

            # Set specific timestamp fields based on status
            if status == DraftStatus.GENERATING:
                draft.generation_started_at = datetime.now(timezone.utc)
            elif status == DraftStatus.GENERATED:
                draft.generation_completed_at = datetime.now(timezone.utc)
            elif status == DraftStatus.REVIEWING:
                draft.review_started_at = datetime.now(timezone.utc)
            elif status == DraftStatus.REVIEWED:
                draft.review_completed_at = datetime.now(timezone.utc)

            session.add(draft)
            await session.commit()
            return True

        if session:
            return await _update(session)
        else:
            async with AsyncSessionLocal() as session:
                return await _update(session)

    @staticmethod
    async def update_section(
        draft_id: str,
        section_name: str,
        content: str,
        session: Optional[AsyncSession] = None
    ) -> bool:
        """Update a specific section of a draft."""
        async def _update(session: AsyncSession):
            statement = select(PaperDraft).where(PaperDraft.draft_id == draft_id)
            result = await session.execute(statement)
            draft = result.scalars().first()

            if not draft:
                return False

            try:
                draft.set_section(section_name, content)
                # Note: updated_at is automatically set by SQLAlchemy onupdate trigger
                session.add(draft)
                await session.commit()
                log.info(f"Updated {section_name} section for draft {draft_id}")
                return True
            except ValueError as e:
                log.error(f"Failed to update section {section_name}: {e}")
                return False

        if session:
            return await _update(session)
        else:
            async with AsyncSessionLocal() as session:
                return await _update(session)

    @staticmethod
    async def set_review_data(
        draft_id: str,
        review_data: Dict[str, Any],
        suggestions: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """Set review data and suggestions for a draft."""
        async with AsyncSessionLocal() as session:
            try:
                statement = select(PaperDraft).where(PaperDraft.draft_id == draft_id)
                result = await session.execute(statement)
                draft = result.scalars().first()

                if not draft:
                    return False

                draft.review_data = review_data
                if suggestions is not None:
                    draft.suggestions = suggestions
                # Note: updated_at is automatically set by SQLAlchemy onupdate trigger

                session.add(draft)
                await session.commit()

                log.info(f"Set review data for draft {draft_id}")
                return True
            except Exception as e:
                await session.rollback()
                log.error(f"Failed to set review data for draft {draft_id}: {e}")
                raise

    @staticmethod
    async def apply_suggestions(
        draft_id: str,
        accept_all: bool = False,
        accept_sections: Optional[List[str]] = None,
        suggestion_ids: Optional[List[str]] = None,
        session: Optional[AsyncSession] = None
    ) -> bool:
        """Apply suggestions to a draft based on acceptance criteria."""
        async def _apply(session: AsyncSession):
            statement = select(PaperDraft).where(PaperDraft.draft_id == draft_id)
            result = await session.execute(statement)
            draft = result.scalars().first()

            if not draft or not draft.suggestions:
                return False

            applied_count = 0

            for suggestion_data in draft.suggestions:
                suggestion = ReviewSuggestion(**suggestion_data)

                # Determine if this suggestion should be applied
                should_apply = False
                if accept_all:
                    should_apply = True
                elif accept_sections and suggestion.section in accept_sections:
                    should_apply = True
                elif suggestion_ids and suggestion.suggestion_id in suggestion_ids:
                    should_apply = True

                if should_apply:
                    # Apply the suggestion by updating the section content
                    current_section = getattr(draft, suggestion.section, "")
                    if current_section and suggestion.before in current_section:
                        try:
                            # Enhanced string replacement with safety checks
                            updated_content = self._apply_safe_replacement(
                                current_section,
                                suggestion.before,
                                suggestion.after,
                                suggestion.suggestion_id
                            )

                            # Validate the replacement actually occurred and makes sense
                            if updated_content and updated_content != current_section:
                                # Additional validation: ensure content isn't corrupted
                                if self._validate_replacement_quality(current_section, updated_content, suggestion):
                                    draft.set_section(suggestion.section, updated_content)
                                    suggestion_data["status"] = "applied"
                                    applied_count += 1
                                    log.info(f"Applied suggestion {suggestion.suggestion_id} to {suggestion.section}")
                                else:
                                    log.warning(f"Suggestion {suggestion.suggestion_id} failed quality validation")
                                    suggestion_data["status"] = "failed"
                            else:
                                log.warning(f"Suggestion {suggestion.suggestion_id} replacement had no effect or was unsafe")
                                suggestion_data["status"] = "failed"
                        except Exception as e:
                            log.error(f"Failed to apply suggestion {suggestion.suggestion_id}: {e}")
                            suggestion_data["status"] = "failed"

            # Note: updated_at is automatically set by SQLAlchemy onupdate trigger
            session.add(draft)
            await session.commit()

            log.info(f"Applied {applied_count} suggestions to draft {draft_id}")
            return True

        if session:
            return await _apply(session)
        else:
            async with AsyncSessionLocal() as session:
                return await _apply(session)

    @staticmethod
    async def get_draft_progress(draft_id: str) -> Optional[Dict[str, Any]]:
        """Get progress information for a draft."""
        draft = await PaperDraftService.get_draft(draft_id)
        if not draft:
            return None

        return draft.get_progress()

    @staticmethod
    async def list_drafts(
        limit: int = 50,
        offset: int = 0,
        status_filter: Optional[DraftStatus] = None
    ) -> List[PaperDraft]:
        """List drafts with optional filtering."""
        async with AsyncSessionLocal() as session:
            statement = select(PaperDraft)

            if status_filter:
                statement = statement.where(PaperDraft.status == status_filter)

            statement = statement.order_by(PaperDraft.created_at.desc())
            statement = statement.offset(offset).limit(limit)

            result = await session.execute(statement)
            return result.scalars().all()

    @staticmethod
    async def update_sections_atomic(
        draft_id: str,
        section_updates: Dict[str, str],
        session: Optional[AsyncSession] = None
    ) -> bool:
        """
        Update multiple sections atomically.

        Args:
            draft_id: Draft identifier
            section_updates: Dictionary mapping section names to content
            session: Optional existing session to use

        Returns:
            True if all updates successful, False otherwise
        """
        async def _update(session: AsyncSession):
            try:
                statement = select(PaperDraft).where(PaperDraft.draft_id == draft_id)
                result = await session.execute(statement)
                draft = result.scalars().first()

                if not draft:
                    log.error(f"Draft not found for atomic update: {draft_id}")
                    return False

                # Validate all sections exist before making any changes
                valid_sections = {"abstract", "introduction", "argument", "counterarguments", "conclusion"}
                for section_name in section_updates.keys():
                    if section_name not in valid_sections:
                        log.error(f"Invalid section name in atomic update: {section_name}")
                        return False

                # Apply all updates
                for section_name, content in section_updates.items():
                    try:
                        draft.set_section(section_name, content)
                        log.info(f"Updated section {section_name} ({len(content)} chars)")
                    except Exception as e:
                        log.error(f"Failed to update section {section_name}: {e}")
                        raise

                # Update metadata
                # Note: updated_at is automatically set by SQLAlchemy onupdate trigger
                if hasattr(draft, 'generation_completed_at') and not draft.generation_completed_at:
                    draft.generation_completed_at = datetime.now(timezone.utc)

                session.add(draft)
                await session.commit()

                log.info(f"Atomic update successful for draft {draft_id}, updated {len(section_updates)} sections")
                return True

            except Exception as e:
                await session.rollback()
                log.error(f"Atomic update failed for draft {draft_id}: {e}")
                return False

        if session:
            return await _update(session)
        else:
            async with AsyncSessionLocal() as session:
                return await _update(session)

    @staticmethod
    def _apply_safe_replacement(
        content: str,
        before: str,
        after: str,
        suggestion_id: str
    ) -> Optional[str]:
        """
        Apply string replacement with enhanced safety checks.

        Args:
            content: Original content
            before: Text to replace
            after: Replacement text
            suggestion_id: ID for logging

        Returns:
            Updated content or None if replacement is unsafe
        """
        import re

        # Safety checks on input parameters
        if not content or not before:
            log.warning(f"Invalid input for suggestion {suggestion_id}: empty content or before text")
            return None

        if len(before) > 1000 or len(after) > 1000:
            log.warning(f"Suggestion {suggestion_id} has excessively long replacement text")
            return None

        # Count occurrences to detect ambiguous replacements
        occurrence_count = content.count(before)
        if occurrence_count == 0:
            log.info(f"Suggestion {suggestion_id}: before text not found in content")
            return None
        elif occurrence_count > 3:
            log.warning(f"Suggestion {suggestion_id}: too many occurrences ({occurrence_count}) - replacement may be ambiguous")
            return None

        # For single word replacements, prefer word boundary matching
        if ' ' not in before.strip() and ' ' not in after.strip() and len(before) > 2:
            # Try word boundary replacement first for single words
            word_pattern = rf'\b{re.escape(before)}\b'
            try:
                word_matches = re.findall(word_pattern, content, re.IGNORECASE)
                if len(word_matches) == 1:
                    # Safe single word boundary match
                    updated_content = re.sub(word_pattern, after, content, count=1, flags=re.IGNORECASE)
                    log.info(f"Applied word boundary replacement for suggestion {suggestion_id}")
                    return updated_content
            except re.error as e:
                log.warning(f"Word boundary regex failed for suggestion {suggestion_id}: {e}")
                # Fall through to simple replacement

        # Context-aware replacement for phrases
        if occurrence_count <= 2:
            # Find the position of the first occurrence
            first_pos = content.find(before)
            if first_pos == -1:
                return None

            # Examine context around the replacement (50 chars before/after)
            context_start = max(0, first_pos - 50)
            context_end = min(len(content), first_pos + len(before) + 50)
            context = content[context_start:context_end]

            # Ensure we're not breaking sentence structure
            before_char = content[first_pos - 1] if first_pos > 0 else ' '
            after_char = content[first_pos + len(before)] if first_pos + len(before) < len(content) else ' '

            # Check if replacement maintains logical text flow
            if before_char.isalnum() and after[0].isalnum() and not before[0].isupper():
                # Might be breaking a word - be more careful
                if before not in [' ' + before + ' ', '. ' + before + ' ', '(' + before + ')']:
                    log.warning(f"Suggestion {suggestion_id}: replacement might break word boundaries")

            # Apply the replacement (first occurrence only)
            updated_content = content.replace(before, after, 1)

            # Validate the change makes sense
            if len(updated_content) == len(content) + len(after) - len(before):
                log.info(f"Applied context-aware replacement for suggestion {suggestion_id}")
                return updated_content
            else:
                log.error(f"Length validation failed for suggestion {suggestion_id}")
                return None

        # Fallback for multiple occurrences - require exact context match
        log.warning(f"Suggestion {suggestion_id}: multiple occurrences, requiring manual review")
        return None

    @staticmethod
    def _validate_replacement_quality(
        original: str,
        updated: str,
        suggestion: 'ReviewSuggestion'
    ) -> bool:
        """
        Validate that the replacement maintains content quality.

        Args:
            original: Original content
            updated: Updated content
            suggestion: The applied suggestion

        Returns:
            True if replacement quality is acceptable
        """
        # Basic length validation
        length_change = len(updated) - len(original)
        max_length_change = max(100, len(original) * 0.2)  # Max 20% change or 100 chars

        if abs(length_change) > max_length_change:
            log.warning(f"Suggestion {suggestion.suggestion_id}: excessive length change ({length_change} chars)")
            return False

        # Word count validation
        original_words = len(original.split())
        updated_words = len(updated.split())
        word_change = abs(updated_words - original_words)

        if word_change > max(10, original_words * 0.15):  # Max 15% word change or 10 words
            log.warning(f"Suggestion {suggestion.suggestion_id}: excessive word count change ({word_change} words)")
            return False

        # Check for excessive repetition introduced by replacement
        if updated != original:
            # Look for repeated phrases that might indicate corruption
            import re
            repeated_patterns = re.findall(r'(\b\w+(?:\s+\w+){1,3}\b)(?:\s+\1){2,}', updated)
            if repeated_patterns:
                log.warning(f"Suggestion {suggestion.suggestion_id}: introduced repetitive content")
                return False

            # Check for broken punctuation or formatting
            if updated.count('..') > original.count('..') + 2:
                log.warning(f"Suggestion {suggestion.suggestion_id}: introduced excessive ellipses")
                return False

            # Check for malformed sentences (basic heuristic)
            sentences_before = original.count('.') + original.count('!') + original.count('?')
            sentences_after = updated.count('.') + updated.count('!') + updated.count('?')

            if sentences_after > 0 and abs(sentences_after - sentences_before) > max(2, sentences_before * 0.3):
                log.warning(f"Suggestion {suggestion.suggestion_id}: significant sentence structure change")
                return False

        log.info(f"Suggestion {suggestion.suggestion_id} passed quality validation")
        return True