from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import json
import re
import uuid
import functools
from datetime import datetime, timezone
import multiprocessing
import queue
import asyncio

from app.core.db_models import PaperDraft, DraftStatus
from app.services.paper_service import PaperDraftService
from app.core.logger import log
from app.core.exceptions import (
    LLMError, LLMTimeoutError, LLMResponseError, LLMUnavailableError,
    ReviewError, DraftNotFoundError
)
from app.core.llm_response_processor import LLMResponseProcessor
from app.core.validation import workflow_validator
from app.config import get_workflow_config

if TYPE_CHECKING:
    from app.services.expansion_service import ExpansionService
    from app.services.llm_manager import LLMManager
    from app.services.prompt_renderer import PromptRenderer


# Use default (fork on Linux) for performance - spawn is too slow due to import overhead
# The review workflow doesn't maintain persistent DB connections in the parent process,
# so fork is safe here. The worker processes don't inherit async event loops.
_mp_context = multiprocessing.get_context()


# Module-level worker functions for multiprocessing
def _regex_search_process_worker(pattern: str, text: str, flags: int) -> Optional[Tuple[int, int, str, Tuple[str, ...]]]:
    """Worker function that runs in a separate process. Returns match data including groups."""
    try:
        compiled_pattern = re.compile(pattern, flags)
        match = compiled_pattern.search(text)
        if match:
            return (match.start(), match.end(), match.group(), match.groups())
        return None
    except re.error as e:
        # Regex compilation or matching error
        from app.core.logger import log

        log.warning(
            f"Regex error in worker process: {e}. "
            f"Pattern: {pattern[:100]}{'...' if len(pattern) > 100 else ''}"
        )
        return None
    except Exception as e:
        # Unexpected error in worker process
        from app.core.logger import log

        log.error(
            f"Unexpected error in regex search worker: {e}. "
            f"Pattern: {pattern[:100]}{'...' if len(pattern) > 100 else ''}, "
            f"Text length: {len(text)}",
            exc_info=True
        )
        return None


def _regex_finditer_process_worker(pattern: str, text: str, flags: int) -> List[Tuple[int, int, str, Tuple[str, ...]]]:
    """Worker function for finditer that runs in a separate process. Returns match data including groups."""
    try:
        compiled_pattern = re.compile(pattern, flags)
        matches = list(compiled_pattern.finditer(text))
        return [(m.start(), m.end(), m.group(), m.groups()) for m in matches]
    except re.error as e:
        # Regex compilation or matching error
        from app.core.logger import log

        log.warning(
            f"Regex error in finditer worker: {e}. "
            f"Pattern: {pattern[:100]}{'...' if len(pattern) > 100 else ''}"
        )
        return []
    except Exception as e:
        # Unexpected error in worker process
        from app.core.logger import log

        log.error(
            f"Unexpected error in regex finditer worker: {e}. "
            f"Pattern: {pattern[:100]}{'...' if len(pattern) > 100 else ''}, "
            f"Text length: {len(text)}",
            exc_info=True
        )
        return []


def _search_worker_wrapper(pattern: str, text: str, flags: int, result_queue):
    """Module-level wrapper for safe_regex_search (required for spawn context)."""
    try:
        result = _regex_search_process_worker(pattern, text, flags)
        result_queue.put(("success", result))
    except Exception as e:
        result_queue.put(("error", str(e)))


def _finditer_worker_wrapper(pattern: str, text: str, flags: int, result_queue):
    """Module-level wrapper for safe_regex_finditer (required for spawn context)."""
    try:
        result = _regex_finditer_process_worker(pattern, text, flags)
        result_queue.put(("success", result))
    except Exception as e:
        result_queue.put(("error", str(e)))


def _validate_timeout(timeout: float) -> None:
    """Validate timeout parameter is within acceptable range."""
    if not (0.1 <= timeout <= 10.0):
        raise ValueError(
            f"Timeout must be between 0.1 and 10.0 seconds, got {timeout}. "
            "This limit prevents both immediate failures and ineffective protection."
        )


def _validate_and_truncate_inputs(pattern: str, text: str) -> Tuple[str, str]:
    """Validate and truncate regex inputs to prevent ReDoS attacks."""
    if len(pattern) > 500:  # Prevent overly complex patterns
        log.warning(f"Regex pattern too long ({len(pattern)} chars), truncating")
        pattern = pattern[:500]

    if len(text) > 50000:  # Limit text size to prevent ReDoS
        log.warning(f"Text too long for regex ({len(text)} chars), truncating")
        text = text[:50000]

    return pattern, text


class _MatchProxy:
    """Proxy object that mimics re.Match interface with full group support."""
    def __init__(self, start: int, end: int, matched_text: str, groups: Tuple[str, ...] = ()):
        self._start = start
        self._end = end
        self._matched_text = matched_text
        self._groups = groups

    def start(self, group: int = 0) -> int:
        if group == 0:
            return self._start
        raise IndexError("no such group")

    def end(self, group: int = 0) -> int:
        if group == 0:
            return self._end
        raise IndexError("no such group")

    def group(self, *args):
        """Support group(0), group(1), group(1, 2), etc. Returns None for missing groups."""
        if len(args) == 0:
            return self._matched_text
        elif len(args) == 1:
            group_num = args[0]
            if group_num == 0:
                return self._matched_text
            elif 1 <= group_num <= len(self._groups):
                return self._groups[group_num - 1]
            else:
                raise IndexError("no such group")  # Match actual re.Match behavior
        else:
            # Multiple groups: match.group(1, 2) returns tuple
            return tuple(self.group(g) for g in args)

    def groups(self, default=None) -> Tuple[str, ...]:
        """Return all captured groups as tuple."""
        return self._groups

    def span(self, group: int = 0) -> Tuple[int, int]:
        if group == 0:
            return (self._start, self._end)
        raise IndexError("no such group")


def safe_regex_search(pattern: str, text: str, timeout: float = 2.0, flags: int = 0):
    """
    Perform regex search with timeout protection against ReDoS attacks.

    Uses process isolation to ensure timed-out operations are truly terminated.
    The computation runs in a separate process which can be forcibly killed.

    Args:
        pattern: Regex pattern to search for
        text: Text to search in
        timeout: Maximum time to allow for regex operation (0.1-10.0 seconds)
        flags: Regex flags

    Returns:
        Match-like object or None if no match or timeout

    Raises:
        ValueError: If timeout is out of valid range
    """
    result_queue = None
    process = None

    try:
        _validate_timeout(timeout)
        pattern, text = _validate_and_truncate_inputs(pattern, text)

        # Create a process to run the regex operation
        result_queue = _mp_context.Queue()

        process = _mp_context.Process(
            target=_search_worker_wrapper,
            args=(pattern, text, flags, result_queue)
        )
        process.start()
        process.join(timeout)

        if process.is_alive():
            # Process is still running after timeout - terminate it
            try:
                process.terminate()
                process.join(timeout=1.0)
                if process.is_alive():
                    # Force kill if terminate didn't work
                    process.kill()
                    process.join()
            except ProcessLookupError:
                # Process already exited between check and terminate - this is fine
                pass
            log.warning(
                f"Regex search timed out after {timeout}s. "
                f"Pattern length: {len(pattern)}, Text length: {len(text)}. "
                f"Process terminated."
            )
            return None

        # Get result from queue (with small timeout to avoid race condition)
        try:
            status, result = result_queue.get(timeout=0.1)
            if status == "success" and result:
                return _MatchProxy(result[0], result[1], result[2], result[3])
            return None
        except queue.Empty:
            return None

    except ValueError:
        # Re-raise validation errors
        raise
    except (re.error, Exception) as e:
        log.warning(f"Regex search operation failed: {e}")
        return None
    finally:
        # Clean up resources
        if result_queue is not None:
            try:
                result_queue.close()
                result_queue.join_thread()
            except (OSError, ValueError) as e:
                # Queue cleanup errors are expected if process was terminated
                log.debug(f"Queue cleanup error (expected during process termination): {e}")
        if process is not None and process.is_alive():
            try:
                process.terminate()
                process.join(timeout=0.5)
            except (ProcessLookupError, OSError) as e:
                # Process may have already exited - this is fine
                log.debug(f"Process cleanup error (expected if already exited): {e}")


def safe_regex_finditer(pattern: str, text: str, timeout: float = 2.0, flags: int = 0):
    """
    Safe version of re.finditer with timeout protection.

    Uses process isolation to ensure timed-out operations are truly terminated.
    The computation runs in a separate process which can be forcibly killed.

    Args:
        pattern: Regex pattern to search for
        text: Text to search in
        timeout: Maximum time to allow for regex operation (0.1-10.0 seconds)
        flags: Regex flags

    Returns:
        List of match-like objects or empty list on timeout

    Raises:
        ValueError: If timeout is out of valid range
    """
    result_queue = None
    process = None

    try:
        _validate_timeout(timeout)
        pattern, text = _validate_and_truncate_inputs(pattern, text)

        # Create a process to run the regex operation
        result_queue = _mp_context.Queue()

        process = _mp_context.Process(
            target=_finditer_worker_wrapper,
            args=(pattern, text, flags, result_queue)
        )
        process.start()
        process.join(timeout)

        if process.is_alive():
            # Process is still running after timeout - terminate it
            try:
                process.terminate()
                process.join(timeout=1.0)
                if process.is_alive():
                    # Force kill if terminate didn't work
                    process.kill()
                    process.join()
            except ProcessLookupError:
                # Process already exited between check and terminate - this is fine
                pass
            log.warning(
                f"Regex finditer timed out after {timeout}s. "
                f"Pattern length: {len(pattern)}, Text length: {len(text)}. "
                f"Process terminated."
            )
            return []

        # Get result from queue (with small timeout to avoid race condition)
        try:
            status, results = result_queue.get(timeout=0.1)
            if status == "success":
                return [_MatchProxy(start, end, matched_text, groups) for start, end, matched_text, groups in results]
            return []
        except queue.Empty:
            return []

    except ValueError:
        # Re-raise validation errors
        raise
    except (re.error, Exception) as e:
        log.warning(f"Regex finditer operation failed: {e}")
        return []
    finally:
        # Clean up resources
        if result_queue is not None:
            try:
                result_queue.close()
                result_queue.join_thread()
            except (OSError, ValueError) as e:
                # Queue cleanup errors are expected if process was terminated
                log.debug(f"Queue cleanup error (expected during process termination): {e}")
        if process is not None and process.is_alive():
            try:
                process.terminate()
                process.join(timeout=0.5)
            except (ProcessLookupError, OSError) as e:
                # Process may have already exited - this is fine
                log.debug(f"Process cleanup error (expected if already exited): {e}")


class ReviewWorkflow:
    """
    Orchestrates the AI review workflow for paper drafts.

    Implements Chain-of-Verification, Self-RAG, and evidence-based review
    with actionable suggestions and blocking flags.
    Dependencies can be injected via constructor or will be created automatically for backward compatibility.
    Prefer using dependency injection from app.core.dependencies.get_review_workflow().
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
            log.debug("ReviewWorkflow using injected ExpansionService")
        else:
            from app.services.expansion_service import ExpansionService

            self.expansion_service = ExpansionService()
            log.warning("ReviewWorkflow creating own ExpansionService - consider using dependency injection")

        # LLMManager initialization
        if llm_manager is not None:
            self.llm_manager = llm_manager
            log.debug("ReviewWorkflow using injected LLMManager")
        else:
            from app.services.llm_manager import LLMManager

            self.llm_manager = LLMManager()
            log.warning("ReviewWorkflow creating own LLMManager - consider using dependency injection")

        # PromptRenderer initialization
        if prompt_renderer is not None:
            self.prompt_renderer = prompt_renderer
            log.debug("ReviewWorkflow using injected PromptRenderer")
        else:
            from app.services.prompt_renderer import PromptRenderer

            self.prompt_renderer = PromptRenderer()
            log.warning("ReviewWorkflow creating own PromptRenderer - consider using dependency injection")

    async def review_draft(
        self,
        draft_id: str,
        rubric: Optional[List[str]] = None,
        severity_gate: str = "medium",
        max_evidence_per_question: int = 5
    ) -> Dict[str, Any]:
        """
        Perform comprehensive AI review of a paper draft.

        Args:
            draft_id: Draft identifier
            rubric: Review criteria (default: standard philosophical rubric)
            severity_gate: Minimum severity for blocking issues
            max_evidence_per_question: Max evidence items per verification question

        Returns:
            Complete review results with suggestions and verification
        """
        from app.core.database import AsyncSessionLocal

        # Validate inputs
        workflow_validator.validate_draft_id(draft_id)
        workflow_validator.validate_review_request(
            rubric=rubric,
            severity_gate=severity_gate,
            max_evidence_per_question=max_evidence_per_question
        )

        # Get draft
        draft = await PaperDraftService.get_draft(draft_id)
        if not draft:
            raise DraftNotFoundError(draft_id)

        # Default rubric
        if rubric is None:
            rubric = ["accuracy", "argument", "coherence", "citations", "style"]

        # Use single transaction for all operations
        async with AsyncSessionLocal() as session:
            try:
                # Update status to reviewing
                await PaperDraftService.update_draft_status(draft_id, DraftStatus.REVIEWING, session)

                # Get full draft content
                sections = draft.get_sections()
                full_content = self._combine_sections(sections)

                if not full_content.strip():
                    raise ValueError("Draft has no content to review")

                log.info(f"Starting AI review for draft {draft_id}")

                # Step 1: Generate verification plan
                verification_plan = await self._generate_verification_plan(full_content)
                log.info(f"Generated {len(verification_plan)} verification questions")

                # Step 2: Gather evidence for verification questions
                evidence_results = await self._gather_verification_evidence(
                    verification_plan,
                    draft.collection,
                    max_evidence_per_question
                )

                # Step 3: Perform comprehensive review
                review_results = await self._perform_comprehensive_review(
                    draft=draft,
                    content=full_content,
                    rubric=rubric,
                    verification_plan=verification_plan,
                    evidence_results=evidence_results
                )

                # Step 4: Generate actionable suggestions
                suggestions = await self._generate_suggestions(
                    draft=draft,
                    content=full_content,
                    review_results=review_results,
                    evidence_results=evidence_results,
                    severity_gate=severity_gate
                )

                # Step 5: Compile final review data
                review_data = {
                    "review_id": str(uuid.uuid4()),
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "rubric": rubric,
                    "severity_gate": severity_gate,
                    "verification_plan": verification_plan,
                    "evidence_summary": {
                        "total_questions": len(verification_plan),
                        "evidence_gathered": len(evidence_results),
                        "successful_retrievals": sum(1 for e in evidence_results.values() if e)
                    },
                    "review_results": review_results,
                    "suggestions_summary": {
                        "total_suggestions": len(suggestions),
                        "blocking_suggestions": sum(1 for s in suggestions if s.get("blocking", False)),
                        "suggestions_by_section": self._group_suggestions_by_section(suggestions)
                    },
                    "overall_assessment": review_results.get("overall_assessment", ""),
                    "metadata": {
                        "draft_title": draft.title,
                        "collection": draft.collection,
                        "review_length": len(full_content),
                        "expansion_methods_used": ["hyde", "rag_fusion", "self_ask"]
                    }
                }

                # Save review data and suggestions atomically
                suggestion_dicts = [self._suggestion_to_dict(s) for s in suggestions]
                review_saved = await PaperDraftService.set_review_data(
                    draft_id=draft_id,
                    review_data=review_data,
                    suggestions=suggestion_dicts
                )

                if not review_saved:
                    raise ReviewError("Failed to save review data")

                # Update status to reviewed
                await PaperDraftService.update_draft_status(draft_id, DraftStatus.REVIEWED, session)

                await session.commit()

                log.info(f"Completed AI review for draft {draft_id} with {len(suggestions)} suggestions")

                return {
                    "draft_id": draft_id,
                    "review_id": review_data["review_id"],
                    "status": "completed",
                    "summary": review_data["suggestions_summary"],
                    "blocking_issues": review_data["suggestions_summary"]["blocking_suggestions"],
                    "verification_coverage": f"{review_data['evidence_summary']['successful_retrievals']}/{review_data['evidence_summary']['total_questions']}",
                    "review_data": review_data
                }

            except DraftNotFoundError:
                # Re-raise specific errors without modification
                raise
            except ValueError as e:
                # Validation errors (empty content, invalid parameters)
                await session.rollback()
                log.error(
                    f"Validation error during review of draft {draft_id}: {e}. "
                    f"Rubric: {rubric}, Severity gate: {severity_gate}"
                )
                try:
                    await PaperDraftService.update_draft_status(draft_id, DraftStatus.ERROR, session)
                    await session.commit()
                except Exception as status_error:
                    log.error(
                        f"Failed to update error status for draft {draft_id} after validation error: {status_error}",
                        exc_info=True
                    )
                raise ReviewError(f"Review validation failed: {e}")
            except (LLMError, LLMTimeoutError, LLMUnavailableError) as e:
                # LLM-specific errors
                await session.rollback()
                log.error(
                    f"LLM error during review of draft {draft_id}: {e}. "
                    f"Collection: {draft.collection if 'draft' in locals() else 'unknown'}"
                )
                try:
                    await PaperDraftService.update_draft_status(draft_id, DraftStatus.ERROR, session)
                    await session.commit()
                except Exception as status_error:
                    log.error(
                        f"Failed to update error status for draft {draft_id} after LLM error: {status_error}",
                        exc_info=True
                    )
                raise ReviewError(f"Review LLM processing failed: {e}")
            except Exception as e:
                # Unexpected errors
                await session.rollback()
                log.error(
                    f"Unexpected error during review of draft {draft_id}: {e}. "
                    f"Rubric: {rubric}, Severity gate: {severity_gate}, "
                    f"Max evidence per question: {max_evidence_per_question}, "
                    f"Draft collection: {draft.collection if 'draft' in locals() else 'unknown'}",
                    exc_info=True
                )
                try:
                    await PaperDraftService.update_draft_status(draft_id, DraftStatus.ERROR, session)
                    await session.commit()
                except Exception as status_error:
                    log.error(
                        f"Failed to update error status for draft {draft_id} after unexpected error: {status_error}",
                        exc_info=True
                    )
                raise ReviewError(f"Review workflow failed unexpectedly: {e}")

    async def _generate_verification_plan(self, content: str) -> List[Dict[str, Any]]:
        """Generate verification plan with factual claims and search questions."""
        try:
            system_prompt = self.prompt_renderer.render("workflows/reviewer/verification_system.j2")
            user_prompt = self.prompt_renderer.render(
                "workflows/reviewer/verification_user.j2",
                {"content": content}
            )

            response = await self.llm_manager.aquery(
                f"{system_prompt}\n\n{user_prompt}",
                temperature=0.2  # Lower temperature for consistent structure
            )

            # Parse verification plan from response
            content = LLMResponseProcessor.extract_content(response)
            verification_plan = self._parse_verification_plan(content)
            return verification_plan

        except LLMTimeoutError as e:
            log.warning(
                f"Verification plan generation timed out: {e}. "
                f"Content length: {len(content)} chars"
            )
            return []
        except LLMResponseError as e:
            log.warning(
                f"Invalid LLM response during verification plan generation: {e}. "
                f"Content length: {len(content)} chars"
            )
            return []
        except Exception as e:
            log.error(
                f"Unexpected error generating verification plan: {e}. "
                f"Content length: {len(content)} chars",
                exc_info=True
            )
            return []

    def _parse_verification_plan(self, response_content: str) -> List[Dict[str, Any]]:
        """Parse verification plan from LLM response."""
        verification_plan = []
        current_claim = None
        current_questions = []

        lines = response_content.split('\n')
        claim_counter = 0

        for line in lines:
            line = line.strip()

            # Look for claim lines
            if line.startswith('**Claim') or line.startswith('Claim'):
                # Save previous claim if exists
                if current_claim and current_questions:
                    verification_plan.append({
                        "claim_id": f"claim_{claim_counter}",
                        "claim": current_claim["text"],
                        "type": current_claim["type"],
                        "questions": current_questions
                    })
                    claim_counter += 1

                # Parse new claim with more robust pattern matching
                claim_text = self._extract_field_value(line, ["claim", "**claim"])
                if claim_text:
                    current_claim = {"text": claim_text}
                    current_questions = []

            # Look for type lines
            elif line.startswith('**Type') or line.startswith('Type'):
                if current_claim:
                    type_text = self._extract_field_value(line, ["type", "**type"])
                    if type_text:
                        current_claim["type"] = type_text

            # Look for questions (numbered lists)
            elif self._is_numbered_list_item(line) and current_claim:
                question = self._extract_list_item_text(line)
                if question:
                    current_questions.append(question)

        # Don't forget the last claim
        if current_claim and current_questions:
            verification_plan.append({
                "claim_id": f"claim_{claim_counter}",
                "claim": current_claim["text"],
                "type": current_claim.get("type", "Unknown"),
                "questions": current_questions
            })

        return verification_plan

    async def _gather_verification_evidence(
        self,
        verification_plan: List[Dict[str, Any]],
        collection: str,
        max_evidence_per_question: int
    ) -> Dict[str, List[Any]]:
        """Gather evidence for verification questions using query expansion."""
        evidence_results = {}

        for claim_data in verification_plan:
            claim_id = claim_data["claim_id"]
            questions = claim_data["questions"]

            claim_evidence = []

            for question in questions:
                try:
                    # Use expansion service to get comprehensive evidence
                    expansion_result = await self.expansion_service.expand_query(
                        query=question,
                        collection=collection,
                        methods=["hyde", "rag_fusion"],  # Fast methods for verification
                        max_results=max_evidence_per_question
                    )

                    evidence_nodes = expansion_result.retrieval_results
                    claim_evidence.extend(evidence_nodes)

                except LLMTimeoutError as e:
                    log.warning(
                        f"Evidence gathering timed out for question: {question[:100]}{'...' if len(question) > 100 else ''}. "
                        f"Collection: {collection}, Claim ID: {claim_id}"
                    )
                    continue
                except ConnectionError as e:
                    log.warning(
                        f"Connection error during evidence gathering: {e}. "
                        f"Question: {question[:100]}{'...' if len(question) > 100 else ''}, "
                        f"Collection: {collection}, Claim ID: {claim_id}"
                    )
                    continue
                except Exception as e:
                    log.error(
                        f"Unexpected error gathering evidence: {e}. "
                        f"Question: {question[:100]}{'...' if len(question) > 100 else ''}, "
                        f"Collection: {collection}, Claim ID: {claim_id}",
                        exc_info=True
                    )
                    continue

            # Deduplicate evidence
            unique_evidence = self.expansion_service.qdrant_manager.deduplicate_results(
                claim_evidence
            )
            evidence_results[claim_id] = unique_evidence[:max_evidence_per_question * len(questions)]

        return evidence_results

    async def _perform_comprehensive_review(
        self,
        draft: PaperDraft,
        content: str,
        rubric: List[str],
        verification_plan: List[Dict[str, Any]],
        evidence_results: Dict[str, List[Any]]
    ) -> Dict[str, Any]:
        """Perform comprehensive review with Chain-of-Verification and Self-RAG."""
        try:
            system_prompt = self.prompt_renderer.render("workflows/reviewer/system.j2")

            # Prepare evidence summary for review
            evidence_summary = self._prepare_evidence_summary(verification_plan, evidence_results)

            user_prompt = self.prompt_renderer.render(
                "workflows/reviewer/user.j2",
                {
                    "paper_title": draft.title,
                    "section_type": "Complete Draft",
                    "content": content,
                    "rubric": rubric
                }
            )

            # Add evidence to the prompt
            full_user_prompt = f"{user_prompt}\n\n## Verification Evidence\n{evidence_summary}"

            response = await self.llm_manager.aquery(
                f"{system_prompt}\n\n{full_user_prompt}",
                temperature=0.3
            )

            # Parse review results
            review_content = LLMResponseProcessor.extract_content(response)
            return {
                "raw_review": review_content,
                "rubric_scores": self._extract_rubric_scores(review_content, rubric),
                "verification_assessment": self._extract_verification_assessment(review_content),
                "argument_analysis": self._extract_argument_analysis(review_content),
                "overall_assessment": self._extract_overall_assessment(review_content)
            }

        except LLMTimeoutError as e:
            log.error(
                f"Review generation timed out for draft {draft.draft_id}: {e}. "
                f"Content length: {len(content)} chars, Rubric: {rubric}"
            )
            return {
                "error": f"Review generation timed out: {e}",
                "raw_review": "Review generation timed out"
            }
        except LLMResponseError as e:
            log.error(
                f"Invalid LLM response during review of draft {draft.draft_id}: {e}. "
                f"Content length: {len(content)} chars, Rubric: {rubric}"
            )
            return {
                "error": f"Invalid LLM response: {e}",
                "raw_review": "Review generation failed due to invalid response"
            }
        except Exception as e:
            log.error(
                f"Unexpected error during comprehensive review of draft {draft.draft_id}: {e}. "
                f"Content length: {len(content)} chars, Rubric: {rubric}, "
                f"Verification plan items: {len(verification_plan)}, "
                f"Evidence results: {len(evidence_results)}",
                exc_info=True
            )
            return {
                "error": f"Review generation failed unexpectedly: {e}",
                "raw_review": "Review generation failed"
            }

    def _prepare_evidence_summary(
        self,
        verification_plan: List[Dict[str, Any]],
        evidence_results: Dict[str, List[Any]]
    ) -> str:
        """Prepare evidence summary for review prompt."""
        summary_parts = []

        for claim_data in verification_plan:
            claim_id = claim_data["claim_id"]
            claim_text = claim_data["claim"]
            evidence = evidence_results.get(claim_id, [])

            summary_parts.append(f"**Claim**: {claim_text}")

            if evidence:
                summary_parts.append("**Evidence Found**:")
                for i, node in enumerate(evidence[:3], 1):  # Top 3 evidence items
                    if hasattr(node, 'payload') and 'text' in node.payload:
                        text = node.payload['text'][:200] + "..." if len(node.payload['text']) > 200 else node.payload['text']
                        author = node.payload.get('author', 'Unknown')
                        work = node.payload.get('work', 'Unknown Work')
                        score = getattr(node, 'score', 0.0)
                        summary_parts.append(f"{i}. {text} ({author}, {work}, score: {score:.2f})")
            else:
                summary_parts.append("**No supporting evidence found**")

            summary_parts.append("")  # Empty line

        return "\n".join(summary_parts)

    async def _generate_suggestions(
        self,
        draft: PaperDraft,
        content: str,
        review_results: Dict[str, Any],
        evidence_results: Dict[str, List[Any]],
        severity_gate: str
    ) -> List[Dict[str, Any]]:
        """Generate actionable suggestions based on review analysis."""
        suggestions = []

        # Parse suggestions from review results
        raw_review = review_results.get("raw_review", "")

        # Look for suggestion sections in the review
        suggestion_patterns = [
            r"### 4\. Specific Suggestions(.*?)(?=###|$)",
            r"## Specific Suggestions(.*?)(?=##|$)",
            r"Suggestions:(.*?)(?=###|##|$)"
        ]

        suggestion_text = ""
        for pattern in suggestion_patterns:
            match = safe_regex_search(pattern, raw_review, timeout=1.0, flags=re.DOTALL | re.IGNORECASE)
            if match:
                suggestion_text = match.group(1)
                break

        if suggestion_text:
            # Parse individual suggestions
            parsed_suggestions = self._parse_suggestions_from_text(suggestion_text, severity_gate)
            suggestions.extend(parsed_suggestions)

        # Add blocking suggestions for missing evidence
        evidence_suggestions = self._generate_evidence_based_suggestions(evidence_results, severity_gate)
        suggestions.extend(evidence_suggestions)

        return suggestions

    def _parse_suggestions_from_text(self, text: str, severity_gate: str) -> List[Dict[str, Any]]:
        """Parse suggestions from review text."""
        suggestions = []
        lines = text.split('\n')

        current_suggestion = {}
        for line in lines:
            line = line.strip()

            if line.startswith('- **Section**'):
                if current_suggestion:
                    suggestions.append(self._finalize_suggestion(current_suggestion, severity_gate))
                current_suggestion = {"suggestion_id": str(uuid.uuid4())}

            # Parse suggestion fields
            if '**Section**:' in line:
                current_suggestion["section"] = line.split(':', 1)[1].strip()
            elif '**Issue**:' in line:
                current_suggestion["issue"] = line.split(':', 1)[1].strip()
            elif '**Suggestion**:' in line:
                current_suggestion["suggestion"] = line.split(':', 1)[1].strip()
            elif '**Rationale**:' in line:
                current_suggestion["rationale"] = line.split(':', 1)[1].strip()
            elif '**Blocking**:' in line:
                blocking_text = line.split(':', 1)[1].strip().lower()
                current_suggestion["blocking"] = blocking_text in ['yes', 'true', 'critical', 'high']

        # Don't forget the last suggestion
        if current_suggestion:
            suggestions.append(self._finalize_suggestion(current_suggestion, severity_gate))

        return suggestions

    def _finalize_suggestion(self, suggestion_data: Dict[str, Any], severity_gate: str) -> Dict[str, Any]:
        """Finalize suggestion with all required fields."""
        return {
            "suggestion_id": suggestion_data.get("suggestion_id", str(uuid.uuid4())),
            "section": suggestion_data.get("section", "general"),
            "before": suggestion_data.get("issue", "Issue identified"),
            "after": suggestion_data.get("suggestion", "Improvement suggested"),
            "rationale": suggestion_data.get("rationale", "Quality improvement"),
            "blocking": suggestion_data.get("blocking", False),
            "status": "pending"
        }

    def _generate_evidence_based_suggestions(
        self,
        evidence_results: Dict[str, List[Any]],
        severity_gate: str
    ) -> List[Dict[str, Any]]:
        """Generate suggestions based on evidence verification results."""
        suggestions = []

        for claim_id, evidence in evidence_results.items():
            if not evidence:  # No evidence found
                suggestions.append({
                    "suggestion_id": str(uuid.uuid4()),
                    "section": "general",
                    "before": f"Claim {claim_id} lacks supporting evidence",
                    "after": "Add citations or supporting evidence for this claim",
                    "rationale": "Factual claims should be supported by authoritative sources",
                    "blocking": severity_gate in ["low", "medium", "high"],
                    "status": "pending"
                })

        return suggestions

    def _combine_sections(self, sections: Dict[str, Optional[str]]) -> str:
        """Combine all sections into a single content string.

        Section order is loaded from configuration (workflows.section_order in TOML)
        and can be overridden via the SECTION_ORDER environment variable.

        Args:
            sections: Dictionary mapping section names to their content

        Returns:
            Combined content string with sections in configured order
        """
        parts = []
        # Get section order from config (can be overridden via SECTION_ORDER env var)
        workflow_config = get_workflow_config()
        section_order = workflow_config.get(
            "section_order",
            ["abstract", "introduction", "argument", "counterarguments", "conclusion"]
        )
        log.debug(f"Using section order: {section_order}")

        for section in section_order:
            content = sections.get(section)
            if content:
                parts.append(f"## {section.title()}\n\n{content}")

        return "\n\n".join(parts)

    def _suggestion_to_dict(self, suggestion: Dict[str, Any]) -> Dict[str, Any]:
        """Convert suggestion to dictionary format for database storage."""
        return {
            "suggestion_id": suggestion.get("suggestion_id"),
            "section": suggestion.get("section"),
            "before": suggestion.get("before"),
            "after": suggestion.get("after"),
            "rationale": suggestion.get("rationale"),
            "blocking": suggestion.get("blocking", False),
            "status": suggestion.get("status", "pending")
        }

    def _group_suggestions_by_section(self, suggestions: List[Dict[str, Any]]) -> Dict[str, int]:
        """Group suggestions by section for summary."""
        groups = {}
        for suggestion in suggestions:
            section = suggestion.get("section", "general")
            groups[section] = groups.get(section, 0) + 1
        return groups

    def _extract_rubric_scores(self, review_content: str, rubric: List[str]) -> Dict[str, Any]:
        """Extract rubric scores from review content."""
        import re
        scores = {}

        for criterion in rubric:
            # Use robust score extraction
            score_info = self._extract_criterion_score(review_content, criterion)

            if score_info:
                scores[criterion] = {
                    "score": score_info["score"],
                    "max_score": score_info["max_score"],
                    "percentage": round((score_info["score"] / score_info["max_score"]) * 100, 1),
                    "parsed": True
                }
            else:
                # Fallback for unparseable scores
                scores[criterion] = {
                    "score": 0,
                    "max_score": 10,
                    "percentage": 0.0,
                    "parsed": False
                }

            # Add raw text for unparsed scores
            if criterion in scores and not scores[criterion]["parsed"]:
                criterion_text = self._extract_criterion_text(review_content, criterion)
                scores[criterion]["raw_text"] = criterion_text[:200] + "..." if len(criterion_text) > 200 else criterion_text

        return scores

    def _extract_criterion_text(self, content: str, criterion: str) -> str:
        """Extract relevant text for a specific criterion."""
        import re
        # Look for sections related to this criterion
        patterns = [
            rf"### {criterion}(.*?)(?=###|$)",
            rf"## {criterion}(.*?)(?=##|$)",
            rf"\*\*{criterion}\*\*[:\s]+(.*?)(?=\*\*|\n\n|$)",
            rf"{criterion}[:\s]+(.*?)(?=\n\n|\w+:|$)"
        ]

        for pattern in patterns:
            match = safe_regex_search(pattern, content, timeout=1.0, flags=re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return f"No specific {criterion} assessment found"

    def _extract_verification_assessment(self, review_content: str) -> str:
        """Extract verification assessment from review."""
        import re
        # Look for verification plan results or fact-checking sections
        patterns = [
            r"### 3\. Verification Plan Results(.*?)(?=###|$)",
            r"## Verification Results(.*?)(?=##|$)",
            r"### Fact-?[Cc]hecking(.*?)(?=###|$)",
            r"\*\*Verification\*\*[:\s]+(.*?)(?=\*\*|\n\n|$)",
            r"Claim verification(.*?)(?=\n\n|###|$)"
        ]

        for pattern in patterns:
            match = safe_regex_search(pattern, review_content, timeout=1.0, flags=re.DOTALL | re.IGNORECASE)
            if match:
                verification_text = match.group(1).strip()
                if len(verification_text) > 50:  # Ensure we have substantial content
                    return verification_text

        # If no specific verification section found, look for claim-related content
        claim_patterns = [
            r"(Claim.*?(?:verified|supported|contradicted).*?)(?=\n\n|$)",
            r"(Evidence.*?(?:supports|contradicts|insufficient).*?)(?=\n\n|$)"
        ]

        found_claims = []
        for pattern in claim_patterns:
            matches = safe_regex_finditer(pattern, review_content, timeout=1.0, flags=re.DOTALL | re.IGNORECASE)
            for match in matches:
                claim_text = match.group(1).strip()
                if len(claim_text) > 20:
                    found_claims.append(claim_text)

        if found_claims:
            return "\n\n".join(found_claims[:3])  # Return top 3 claim assessments

        return "No specific verification assessment found in review"

    def _extract_argument_analysis(self, review_content: str) -> str:
        """Extract argument analysis from review."""
        import re
        # Look for argument analysis sections
        patterns = [
            r"### 2\. Argument Analysis(.*?)(?=###|$)",
            r"## Argument Analysis(.*?)(?=##|$)",
            r"### Argument Structure(.*?)(?=###|$)",
            r"\*\*Argument\*\*[:\s]+(.*?)(?=\*\*|\n\n|$)",
            r"Logical structure(.*?)(?=\n\n|###|$)"
        ]

        for pattern in patterns:
            match = safe_regex_search(pattern, review_content, timeout=1.0, flags=re.DOTALL | re.IGNORECASE)
            if match:
                argument_text = match.group(1).strip()
                if len(argument_text) > 50:  # Ensure substantial content
                    return argument_text

        # Look for argument-related keywords and extract surrounding context
        argument_keywords = [
            r"((?:premise|conclusion|logic|reasoning|inference).*?)(?=\n\n|$)",
            r"((?:validity|soundness|fallacy|coherence).*?)(?=\n\n|$)",
            r"((?:evidence|support|justification).*?)(?=\n\n|$)"
        ]

        found_analysis = []
        for pattern in argument_keywords:
            matches = safe_regex_finditer(pattern, review_content, timeout=1.0, flags=re.DOTALL | re.IGNORECASE)
            for match in matches:
                analysis_text = match.group(1).strip()
                if len(analysis_text) > 30:
                    found_analysis.append(analysis_text)

        if found_analysis:
            return "\n\n".join(found_analysis[:2])  # Return top 2 argument analyses

        return "No specific argument analysis found in review"

    def _extract_overall_assessment(self, review_content: str) -> str:
        """Extract overall assessment from review."""
        # Look for overall assessment section
        patterns = [
            r"### 5\. Overall Assessment(.*?)(?=###|$)",
            r"## Overall Assessment(.*?)(?=##|$)"
        ]

        for pattern in patterns:
            match = safe_regex_search(pattern, review_content, timeout=1.0, flags=re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "See complete review for overall assessment"

    def _extract_field_value(self, line: str, field_names: List[str]) -> Optional[str]:
        """Extract field value from line with robust pattern matching."""
        line_lower = line.lower().strip()

        for field_name in field_names:
            field_name_clean = field_name.replace('*', '').lower()

            # Try multiple separators: colon, colon+space, equals
            separators = [':', ': ', '=', '= ']

            for separator in separators:
                if line_lower.startswith(field_name_clean + separator):
                    value = line[len(field_name) + len(separator):].strip()
                    # Remove trailing asterisks if present
                    value = value.rstrip('*').strip()
                    return value if value else None

        return None

    def _is_numbered_list_item(self, line: str) -> bool:
        """Check if line is a numbered list item with flexible patterns."""
        line = line.strip()

        # Match various numbered list patterns:
        # 1. text, 1) text, (1) text, 1- text, 1: text
        patterns = [
            r'^\d+\.\s+',      # 1. text
            r'^\d+\)\s+',      # 1) text
            r'^\(\d+\)\s+',    # (1) text
            r'^\d+-\s+',       # 1- text
            r'^\d+:\s+',       # 1: text
        ]

        return any(re.match(pattern, line) for pattern in patterns)

    def _extract_list_item_text(self, line: str) -> str:
        """Extract text from numbered list item, removing the number prefix."""
        line = line.strip()

        # Remove various numbered list prefixes
        patterns = [
            r'^\d+\.\s*',      # 1.
            r'^\d+\)\s*',      # 1)
            r'^\(\d+\)\s*',    # (1)
            r'^\d+-\s*',       # 1-
            r'^\d+:\s*',       # 1:
        ]

        for pattern in patterns:
            if re.match(pattern, line):
                return re.sub(pattern, '', line).strip()

        return line  # Return original if no pattern matches

    def _extract_criterion_score(self, content: str, criterion: str) -> Optional[Dict[str, int]]:
        """Extract score for a specific criterion with robust pattern matching."""
        content_lower = content.lower()
        criterion_lower = criterion.lower()

        # Look for various score patterns near the criterion name
        score_patterns = [
            # Simple patterns: "Accuracy: 8/10", "Score: 7"
            rf"{re.escape(criterion_lower)}[:\s]*(\d+)(?:/(\d+))?",
            # Header patterns: "### Accuracy (8/10)"
            rf"#{1,4}\s*{re.escape(criterion_lower)}[^0-9]*?(\d+)(?:/(\d+))?",
            # Bold patterns: "**Accuracy**: 8/10"
            rf"\*\*{re.escape(criterion_lower)}\*\*[:\s]*(\d+)(?:/(\d+))?",
            # Parenthetical: "Accuracy (8/10)"
            rf"{re.escape(criterion_lower)}\s*\((\d+)(?:/(\d+))?\)",
            # Score keyword: "Accuracy Score: 8"
            rf"{re.escape(criterion_lower)}\s+score[:\s]*(\d+)(?:/(\d+))?",
        ]

        for pattern in score_patterns:
            matches = safe_regex_finditer(pattern, content_lower, timeout=1.0, flags=re.IGNORECASE)
            for match in matches:
                try:
                    score = int(match.group(1))
                    max_score = int(match.group(2)) if match.group(2) else 10

                    # Validate score range
                    if 0 <= score <= max_score <= 100:
                        return {"score": score, "max_score": max_score}
                except (ValueError, IndexError):
                    continue

        return None
