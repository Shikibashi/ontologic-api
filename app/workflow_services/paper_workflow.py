from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime
import asyncio
import time

from app.core.db_models import PaperDraft, DraftStatus
from app.services.paper_service import PaperDraftService
from app.core.logger import log
from app.core.exceptions import (
    DraftNotFoundError, GenerationError, WorkflowError,
    LLMError, LLMTimeoutError, LLMResponseError, ValidationError
)
from app.core.llm_response_processor import LLMResponseProcessor
from app.core.validation import workflow_validator

if TYPE_CHECKING:
    from app.services.expansion_service import ExpansionService
    from app.services.llm_manager import LLMManager
    from app.services.prompt_renderer import PromptRenderer


class PaperWorkflow:
    """
    Orchestrates the complete paper generation workflow.

    Handles draft creation, section generation with enhanced retrieval,
    and status management through the paper lifecycle.
    Dependencies can be injected via constructor or will be created automatically for backward compatibility.
    Prefer using dependency injection from app.core.dependencies.get_paper_workflow().
    """

    def __init__(
        self,
        expansion_service: 'ExpansionService' = None,
        llm_manager: 'LLMManager' = None,
        prompt_renderer: 'PromptRenderer' = None
    ):
        # ExpansionService initialization
        if expansion_service is not None:
            self.expansion_service = expansion_service
            log.debug("PaperWorkflow using injected ExpansionService")
        else:
            from app.services.expansion_service import ExpansionService

            self.expansion_service = ExpansionService()
            log.warning("PaperWorkflow creating own ExpansionService - consider using dependency injection")

        # LLMManager initialization
        if llm_manager is not None:
            self.llm_manager = llm_manager
            log.debug("PaperWorkflow using injected LLMManager")
        else:
            from app.services.llm_manager import LLMManager

            self.llm_manager = LLMManager()
            log.warning("PaperWorkflow creating own LLMManager - consider using dependency injection")

        # PromptRenderer initialization
        if prompt_renderer is not None:
            self.prompt_renderer = prompt_renderer
            log.debug("PaperWorkflow using injected PromptRenderer")
        else:
            from app.services.prompt_renderer import PromptRenderer

            self.prompt_renderer = PromptRenderer()
            log.warning("PaperWorkflow creating own PromptRenderer - consider using dependency injection")

    async def create_draft(
        self,
        title: str,
        topic: str,
        collection: str,
        immersive_mode: bool = False,
        temperature: float = 0.3,
        workflow_metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a new paper draft.

        Args:
            title: Paper title
            topic: Main topic or research question
            collection: Philosopher collection to focus on
            immersive_mode: Whether to use immersive philosopher voice
            temperature: LLM temperature for generation
            workflow_metadata: Additional workflow metadata

        Returns:
            draft_id: Unique identifier for the created draft
        """
        # Validate inputs
        workflow_validator.validate_paper_creation(
            title=title,
            topic=topic,
            collection=collection,
            immersive_mode=immersive_mode,
            temperature=temperature,
            metadata=workflow_metadata
        )

        draft = await PaperDraftService.create_draft(
            title=title,
            topic=topic,
            collection=collection,
            immersive_mode=immersive_mode,
            temperature=temperature,
            workflow_metadata=workflow_metadata
        )

        log.info(f"Created paper draft: {draft.draft_id} - {title}")
        return draft.draft_id

    async def generate_sections(
        self,
        draft_id: str,
        sections: Optional[List[str]] = None,
        use_expansion: bool = True,
        expansion_methods: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Generate content for specified sections of a paper draft with atomic transaction management.

        Args:
            draft_id: Draft identifier
            sections: Sections to generate (default: all sections)
            use_expansion: Whether to use query expansion for retrieval
            expansion_methods: Query expansion methods to use

        Returns:
            Generation results with status and section content
        """
        from app.core.database import AsyncSessionLocal

        # Validate inputs
        workflow_validator.validate_draft_id(draft_id)

        if sections is not None:
            workflow_validator.validate_section_generation(
                sections=sections,
                use_expansion=use_expansion,
                expansion_methods=expansion_methods
            )

        # Get draft
        draft = await PaperDraftService.get_draft(draft_id)
        if not draft:
            raise DraftNotFoundError(draft_id)

        # Default sections
        if sections is None:
            sections = ["abstract", "introduction", "argument", "counterarguments", "conclusion"]

        results = {
            "draft_id": draft_id,
            "sections_generated": [],
            "sections_failed": [],
            "total_sections": len(sections),
            "metadata": {}
        }

        # Use single transaction for all operations
        async with AsyncSessionLocal() as session:
            try:
                # Update status to generating
                await PaperDraftService.update_draft_status(draft_id, DraftStatus.GENERATING, session)

                # Generate all sections first (content generation doesn't need DB)
                section_content = {}
                for section in sections:
                    try:
                        log.info(f"Generating {section} section for draft {draft_id}")

                        content = await self._generate_section(
                            draft=draft,
                            section_type=section,
                            use_expansion=use_expansion,
                            expansion_methods=expansion_methods
                        )

                        section_content[section] = content
                        results["sections_generated"].append(section)
                        log.info(f"Successfully generated {section} section ({len(content)} chars)")

                    except Exception as e:
                        log.error(f"Failed to generate {section} section: {e}")
                        results["sections_failed"].append(section)

                # Atomically update all successful sections
                if section_content:
                    success = await PaperDraftService.update_sections_atomic(
                        draft_id=draft_id,
                        section_updates=section_content,
                        session=session
                    )

                    if not success:
                        # If atomic update failed, mark all sections as failed
                        results["sections_failed"].extend(results["sections_generated"])
                        results["sections_generated"] = []
                        log.error("Atomic section update failed")

                # Update final status atomically
                final_status = DraftStatus.ERROR if results["sections_failed"] else DraftStatus.GENERATED
                await PaperDraftService.update_draft_status(draft_id, final_status, session)

                await session.commit()
                results["final_status"] = "completed" if not results["sections_failed"] else "partial"

                log.info(f"Section generation completed for draft {draft_id}: {len(results['sections_generated'])} successful, {len(results['sections_failed'])} failed")
                return results

            except Exception as e:
                await session.rollback()
                try:
                    # Use the same session for error status update to avoid session leak
                    await PaperDraftService.update_draft_status(draft_id, DraftStatus.ERROR, session)
                    await session.commit()
                except Exception as status_error:
                    log.error(f"Failed to update error status for draft {draft_id}: {status_error}")
                log.error(f"Section generation failed for draft {draft_id}: {e}")
                raise GenerationError(f"Failed to generate sections: {e}")

    async def _generate_section(
        self,
        draft: PaperDraft,
        section_type: str,
        use_expansion: bool = True,
        expansion_methods: Optional[List[str]] = None
    ) -> str:
        """Generate content for a specific section."""

        # Create section-specific query
        base_query = f"{draft.topic} {section_type}"

        if section_type == "abstract":
            query = f"Summary and overview of {draft.topic} in {draft.collection} philosophy"
        elif section_type == "introduction":
            query = f"Introduction to {draft.topic} philosophical background context {draft.collection}"
        elif section_type == "argument":
            query = f"Main philosophical arguments for {draft.topic} {draft.collection} position"
        elif section_type == "counterarguments":
            query = f"Objections criticisms counterarguments to {draft.topic} {draft.collection}"
        elif section_type == "conclusion":
            query = f"Implications conclusions significance of {draft.topic} {draft.collection} philosophy"
        else:
            query = base_query

        # Get enhanced context using expansion if enabled
        if use_expansion:
            try:
                expansion_result = await self.expansion_service.expand_query(
                    query=query,
                    collection=draft.collection,
                    methods=expansion_methods,
                    max_results=15
                )
                context_nodes = expansion_result.retrieval_results
                log.info(f"Retrieved {len(context_nodes)} nodes using expansion for {section_type}")
            except Exception as e:
                log.warning(f"Expansion failed for {section_type}, using direct retrieval: {e}")
                # Fallback to direct retrieval
                results = await self.expansion_service.qdrant_manager.query_hybrid(
                    query_text=query,
                    collection=draft.collection,
                    limit=10
                )
                context_nodes = []
                for points in results.values():
                    context_nodes.extend(points)
        else:
            # Direct retrieval without expansion
            results = await self.expansion_service.qdrant_manager.query_hybrid(
                query_text=query,
                collection=draft.collection,
                limit=10
            )
            context_nodes = []
            for points in results.values():
                context_nodes.extend(points)

        # Prepare context string with citations
        context_with_citations = self._prepare_context_with_citations(context_nodes)

        # Generate section content using appropriate prompt template
        if draft.immersive_mode:
            # Use immersive writer template
            system_prompt = self._render_immersive_writer_prompt(draft.collection)
        else:
            # Use academic writer template
            system_prompt = self.prompt_renderer.render("workflows/writer/academic_system.j2")

        # Generate user prompt
        user_prompt = self.prompt_renderer.render(
            "workflows/writer/user.j2",
            {
                "context": context_with_citations,
                "section_type": section_type.title(),
                "topic": draft.topic,
                "paper_title": draft.title,
                "specific_instructions": f"Generate approximately 300-500 words for the {section_type} section."
            }
        )

        # Generate content with retry logic
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        content = await self._generate_content_with_retries(
            full_prompt,
            draft.temperature,
            section_type
        )

        return content

    async def _generate_content_with_retries(
        self,
        prompt: str,
        temperature: float,
        section_type: str
    ) -> str:
        """Generate content with retry logic and comprehensive error handling."""
        max_retries = 3
        base_delay = 1.0

        max_length = 20000

        for attempt in range(max_retries):
            try:
                response = await self.llm_manager.aquery(prompt, temperature=temperature)

                # Extract content using centralized processor
                try:
                    content = LLMResponseProcessor.extract_content(response)
                except ValueError as e:
                    raise LLMResponseError(f"Failed to extract content: {e}")

                # Validate content length
                try:
                    min_length = 100 if section_type in ["abstract", "introduction", "argument"] else 50

                    LLMResponseProcessor.validate_content_length(
                        content,
                        min_length=min_length,
                        max_length=max_length
                    )
                except ValueError as e:
                    raise LLMResponseError(str(e))

                log.info(f"Successfully generated {len(content)} characters for {section_type}")
                return content

            except LLMTimeoutError as e:
                log.warning(f"LLM timeout on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    return self._generate_fallback_content(section_type, "LLM timeout after retries")
                await asyncio.sleep(base_delay * (2 ** attempt))

            except LLMResponseError as e:
                log.warning(f"LLM response error on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    return self._generate_fallback_content(section_type, f"Response error: {str(e)}")
                await asyncio.sleep(base_delay * (2 ** attempt))

            except Exception as e:
                log.error(f"Unexpected error generating {section_type} content, attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    return self._generate_fallback_content(section_type, f"Generation failed: {str(e)}")
                await asyncio.sleep(base_delay * (2 ** attempt))

        # This should never be reached due to the fallback in the exception handlers
        return self._generate_fallback_content(section_type, "Maximum retries exceeded")

    def _generate_fallback_content(self, section_type: str, error_reason: str) -> str:
        """Generate fallback content when LLM generation fails."""
        return self.prompt_renderer.render(
            "workflows/writer/fallback.j2",
            {"section_type": section_type, "error_reason": error_reason}
        )

    def _render_immersive_writer_prompt(self, collection: str) -> str:
        """Render immersive writer prompt for specific philosopher."""
        # Get philosopher info (this would come from your philosopher_info module)
        from app.core.philosopher_info import PHILOSOPHER_INFO

        if collection in PHILOSOPHER_INFO:
            philosopher_data = PHILOSOPHER_INFO[collection]
            return self.prompt_renderer.render(
                "workflows/writer/immersive_system.j2",
                {
                    "philosopher_name": collection,
                    "axioms": philosopher_data.get("axioms", []),
                    "personality": philosopher_data.get("personality", []),
                    "rhetorical_tactics": philosopher_data.get("rhetorical_tactics", []),
                    "cognitive_tone": philosopher_data.get("cognitive_tone", [])
                }
            )
        else:
            # Fallback to academic style if philosopher not found
            return self.prompt_renderer.render("workflows/writer/academic_system.j2")

    def _prepare_context_with_citations(self, nodes: List[Any]) -> str:
        """Prepare context string with proper citations."""
        context_parts = []
        citations = {}

        for i, node in enumerate(nodes[:15], 1):  # Limit to top 15 nodes
            if hasattr(node, 'payload') and 'text' in node.payload:
                text = node.payload['text']

                # Create citation
                author = node.payload.get('author', 'Unknown')
                work = node.payload.get('work', node.payload.get('title', 'Unknown Work'))
                # Score can be a Mock during tests; coerce to float safely for formatting
                raw_score = getattr(node, 'score', 0.0)
                try:
                    score_val = float(raw_score)
                except (TypeError, ValueError):
                    score_val = 0.0

                citation_key = f"^{i}"
                citations[citation_key] = f"{author}. *{work}*. (score: {score_val:.2f})"

                # Add text with citation
                context_parts.append(f"{text} [{citation_key}]")

        # Combine context
        context = "\n\n".join(context_parts)

        # Add citation list
        if citations:
            citation_list = "\n".join([f"[{key}]: {value}" for key, value in citations.items()])
            context += f"\n\n---\nSources:\n{citation_list}"

        return context

    async def get_draft_status(self, draft_id: str) -> Optional[Dict[str, Any]]:
        """Get comprehensive status information for a draft."""
        draft = await PaperDraftService.get_draft(draft_id)
        if not draft:
            return None

        progress = draft.get_progress()

        return {
            "draft_id": draft.draft_id,
            "title": draft.title,
            "topic": draft.topic,
            "collection": draft.collection,
            "status": draft.status,
            "progress": progress,
            "created_at": draft.created_at.isoformat(),
            "updated_at": draft.updated_at.isoformat(),
            "generation_started_at": draft.generation_started_at.isoformat() if draft.generation_started_at else None,
            "generation_completed_at": draft.generation_completed_at.isoformat() if draft.generation_completed_at else None,
            "sections": draft.get_sections(),
            "has_review": bool(draft.review_data),
            "suggestions_count": len(draft.suggestions) if draft.suggestions else 0
        }

    async def apply_suggestions(
        self,
        draft_id: str,
        accept_all: bool = False,
        accept_sections: Optional[List[str]] = None,
        suggestion_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Apply review suggestions to a draft with atomic transaction management.

        Args:
            draft_id: Draft identifier
            accept_all: Accept all suggestions
            accept_sections: Accept suggestions for specific sections
            suggestion_ids: Accept specific suggestion IDs

        Returns:
            Application results
        """
        from app.core.database import AsyncSessionLocal

        # Use single transaction for all operations
        async with AsyncSessionLocal() as session:
            try:
                # Update status to applying
                await PaperDraftService.update_draft_status(draft_id, DraftStatus.APPLYING, session)

                # Apply suggestions atomically
                success = await PaperDraftService.apply_suggestions(
                    draft_id=draft_id,
                    accept_all=accept_all,
                    accept_sections=accept_sections,
                    suggestion_ids=suggestion_ids
                )

                # Update final status based on results
                final_status = DraftStatus.COMPLETED if success else DraftStatus.ERROR
                await PaperDraftService.update_draft_status(draft_id, final_status, session)

                await session.commit()

                result_status = "success" if success else "failed"
                log.info(f"Suggestion application {result_status} for draft {draft_id}")

                return {
                    "draft_id": draft_id,
                    "status": result_status,
                    "applied_suggestions": success
                }

            except Exception as e:
                await session.rollback()
                try:
                    # Use the same session for error status update to avoid session leak
                    await PaperDraftService.update_draft_status(draft_id, DraftStatus.ERROR, session)
                    await session.commit()
                except Exception as status_error:
                    log.error(f"Failed to update error status for draft {draft_id}: {status_error}")
                log.error(f"Failed to apply suggestions for draft {draft_id}: {e}")
                raise WorkflowError(f"Failed to apply suggestions: {e}")
