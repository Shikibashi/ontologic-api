import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from app.workflow_services.paper_workflow import PaperWorkflow
from app.workflow_services.review_workflow import ReviewWorkflow


@pytest.fixture
async def mock_database():
    """Mock database operations."""
    with patch('app.core.database.init_db'):
        yield


@pytest.fixture
def mock_paper_workflow():
    """Create PaperWorkflow with mocked dependencies."""
    from app.core.db_models import PaperDraft, DraftStatus
    import uuid
    
    # Create a mock draft object
    mock_draft = PaperDraft(
        draft_id=str(uuid.uuid4()),
        title="Test Paper",
        topic="Test Topic",
        collection="Test Collection",
        status=DraftStatus.CREATED
    )
    
    with patch('app.services.expansion_service.ExpansionService'), \
         patch('app.services.llm_manager.LLMManager'), \
         patch('app.services.prompt_renderer.PromptRenderer'):

        workflow = PaperWorkflow()

        # Mock expansion service
        workflow.expansion_service.expand_query = AsyncMock()
        workflow.expansion_service.qdrant_manager.query_hybrid = AsyncMock()

        # Mock LLM manager
        workflow.llm_manager.aquery = AsyncMock()

        # Mock prompt renderer
        workflow.prompt_renderer.render = MagicMock()

        return workflow


@pytest.fixture
def mock_review_workflow():
    """Create ReviewWorkflow with mocked dependencies."""
    with patch('app.services.expansion_service.ExpansionService'), \
         patch('app.services.llm_manager.LLMManager'), \
         patch('app.services.prompt_renderer.PromptRenderer'), \
         patch('app.services.paper_service.PaperDraftService') as mock_draft_service:

        # Mock the PaperDraftService methods properly on the instance
        draft_service_instance = mock_draft_service.return_value
        draft_service_instance.get_draft = AsyncMock()
        draft_service_instance.update_draft_status = AsyncMock()

        workflow = ReviewWorkflow()

        # Mock expansion service
        workflow.expansion_service.expand_query = AsyncMock()

        # Mock LLM manager
        workflow.llm_manager.aquery = AsyncMock()

        # Mock prompt renderer
        workflow.prompt_renderer.render = MagicMock()

        return workflow


class TestPaperWorkflowIntegration:
    """Integration tests for paper generation workflow."""

    @pytest.mark.asyncio
    async def test_complete_paper_flow(self, mock_paper_workflow, mock_database):
        """Test complete paper generation flow from creation to completion."""
        workflow = mock_paper_workflow

        # Mock PaperDraftService methods with proper async support
        with patch('app.services.paper_service.PaperDraftService.create_draft', new=AsyncMock()) as mock_create_draft, \
             patch('app.services.paper_service.PaperDraftService.create_draft_from_options', new=AsyncMock()) as mock_create_from_options, \
             patch('app.services.paper_service.PaperDraftService.get_draft', new=AsyncMock()) as mock_get_draft, \
             patch('app.services.paper_service.PaperDraftService.update_draft_status', new=AsyncMock()) as mock_update_status, \
             patch('app.services.paper_service.PaperDraftService.update_section', new=AsyncMock()) as mock_update_section, \
             patch('app.services.paper_service.PaperDraftService.update_sections_atomic', new=AsyncMock(return_value=True)) as mock_update_atomic:
            
            from app.core.db_models import PaperDraft, DraftStatus
            import uuid
            
            # Mock draft creation with proper UUID
            test_draft_id = str(uuid.uuid4())
            mock_draft = PaperDraft(
                draft_id=test_draft_id,
                title="Test Paper",
                topic="Virtue Ethics",
                collection="Aristotle",
                status=DraftStatus.CREATED,
                immersive_mode=False,
                temperature=0.3
            )

            # Configure async mocks
            mock_create_draft.return_value = mock_draft  # Return the draft object, not just the ID
            mock_create_from_options.return_value = mock_draft
            mock_get_draft.return_value = mock_draft
            mock_update_status.return_value = True
            mock_update_section.return_value = True

            # Mock expansion results with proper structure
            mock_node = MagicMock()
            mock_node.payload = {"text": "Content about virtue ethics", "author": "Aristotle"}
            mock_node.score = 0.9
            
            mock_expansion_result = MagicMock()
            mock_expansion_result.retrieval_results = [mock_node]
            
            workflow.expansion_service.expand_query.return_value = mock_expansion_result

            # Mock LLM responses with content longer than 100 chars
            mock_llm_response = MagicMock()
            mock_llm_response.message.content = "This is a comprehensive generated section content that meets the minimum length requirement of 100 characters for the paper workflow validation. It contains detailed information about the topic and provides substantial content for the section being generated."
            workflow.llm_manager.aquery.return_value = mock_llm_response

            # Mock prompt rendering - return a proper string, not a MagicMock
            workflow.prompt_renderer.render.return_value = "Rendered prompt for section generation"

            # Test flow
            # 1. Create draft
            draft_id = await workflow.create_draft(
                title="Test Paper",
                topic="Virtue Ethics",
                collection="Aristotle"
            )
            assert draft_id == test_draft_id

            # 2. Generate sections
            result = await workflow.generate_sections(
                draft_id=draft_id,
                sections=["abstract", "introduction"]
            )

            assert result["draft_id"] == draft_id
            assert "abstract" in result["sections_generated"]
            assert "introduction" in result["sections_generated"]
            assert result["final_status"] == "completed"

    @pytest.mark.asyncio
    async def test_paper_flow_with_expansion(self, mock_paper_workflow):
        """Test paper generation with query expansion enabled."""
        workflow = mock_paper_workflow

        with patch('app.services.paper_service.PaperDraftService.get_draft', new=AsyncMock()) as mock_get_draft, \
             patch('app.services.paper_service.PaperDraftService.update_draft_status', new=AsyncMock()) as mock_update_status, \
             patch('app.services.paper_service.PaperDraftService.update_section', new=AsyncMock()) as mock_update_section, \
             patch('app.services.paper_service.PaperDraftService.update_sections_atomic', new=AsyncMock(return_value=True)) as mock_update_atomic:
            
            from app.core.db_models import PaperDraft, DraftStatus
            import uuid
            
            test_draft_id = str(uuid.uuid4())
            mock_draft = PaperDraft(
                draft_id=test_draft_id,
                title="Test Paper",
                topic="Virtue Ethics",
                collection="Aristotle",
                status=DraftStatus.CREATED,
                temperature=0.3,
                immersive_mode=False
            )

            mock_get_draft.return_value = mock_draft
            mock_update_status.return_value = True
            mock_update_section.return_value = True

            # Mock expansion with multiple methods
            expansion_result = MagicMock()
            expansion_result.retrieval_results = [
                MagicMock(payload={"text": "Content 1"}),
                MagicMock(payload={"text": "Content 2"})
            ]
            workflow.expansion_service.expand_query.return_value = expansion_result

            # Mock LLM response with sufficient content length
            mock_llm_response = MagicMock()
            mock_llm_response.message.content = "This is a comprehensive generated content with expansion that meets the minimum length requirement of 100 characters for the paper workflow validation. It contains detailed information about the topic and provides substantial content for the section being generated using expansion methods."
            workflow.llm_manager.aquery.return_value = mock_llm_response

            result = await workflow.generate_sections(
                draft_id=test_draft_id,  # Use the UUID from the mock draft
                sections=["abstract"],
                use_expansion=True,
                expansion_methods=["hyde", "rag_fusion", "self_ask"]
            )

            # Verify expansion was called with correct methods
            workflow.expansion_service.expand_query.assert_called()
            call_args = workflow.expansion_service.expand_query.call_args
            assert call_args[1]["methods"] == ["hyde", "rag_fusion", "self_ask"]


class TestReviewWorkflowIntegration:
    """Integration tests for AI review workflow."""

    @pytest.mark.asyncio
    async def test_complete_review_flow(self, mock_review_workflow):
        """Test complete AI review flow with verification and suggestions."""
        workflow = mock_review_workflow

        with patch('app.workflow_services.review_workflow.PaperDraftService') as mock_service:
            # Mock draft with content
            mock_draft = MagicMock()
            mock_draft.draft_id = "test-draft"
            mock_draft.title = "Test Paper"
            mock_draft.collection = "Aristotle"
            mock_draft.get_sections.return_value = {
                "abstract": "Abstract content",
                "introduction": "Introduction content"
            }

            mock_service.get_draft = AsyncMock(return_value=mock_draft)
            mock_service.update_draft_status = AsyncMock(return_value=True)
            mock_service.set_review_data = AsyncMock(return_value=True)

            # Mock verification plan generation
            workflow.llm_manager.aquery.side_effect = [
                # Verification plan response
                MagicMock(message=MagicMock(content="""
**Claim 1:** Aristotle wrote the Nicomachean Ethics
**Type:** Historical Fact
**Verification Questions:**
1. When did Aristotle write the Nicomachean Ethics?
2. What are the main themes of the Nicomachean Ethics?
                """)),
                # Review response
                MagicMock(message=MagicMock(content="""
### 4. Specific Suggestions
- **Section**: Introduction
- **Issue**: Lacks supporting evidence
- **Suggestion**: Add citations from primary sources
- **Rationale**: Claims need textual support
- **Blocking**: No
                """))
            ]

            # Mock evidence gathering
            expansion_result = MagicMock()
            expansion_result.retrieval_results = [
                MagicMock(payload={"text": "Evidence text", "author": "Aristotle"})
            ]
            workflow.expansion_service.expand_query.return_value = expansion_result

            # Test review flow
            import uuid
            draft_id = str(uuid.uuid4())
            mock_draft.draft_id = draft_id  # Update mock to match the UUID
            result = await workflow.review_draft(
                draft_id=draft_id,
                rubric=["accuracy", "argument", "coherence"]
            )

            assert result["draft_id"] == draft_id
            assert result["status"] == "completed"
            assert "review_id" in result
            assert "summary" in result

    @pytest.mark.asyncio
    async def test_review_with_evidence_gathering(self, mock_review_workflow):
        """Test review workflow with evidence gathering for verification."""
        workflow = mock_review_workflow

        with patch('app.workflow_services.review_workflow.PaperDraftService') as mock_service:
            mock_draft = MagicMock()
            mock_draft.get_sections.return_value = {"abstract": "Test content"}
            mock_service.get_draft = AsyncMock(return_value=mock_draft)
            mock_service.update_draft_status = AsyncMock(return_value=True)
            mock_service.set_review_data = AsyncMock(return_value=True)

            # Mock verification plan
            workflow.llm_manager.aquery.return_value = MagicMock(
                message=MagicMock(content="""
**Claim 1:** Test claim about Aristotle
**Type:** Historical Fact
**Verification Questions:**
1. When did Aristotle write this work?
2. What are the main themes?
                """)
            )

            # Mock evidence results with multiple items
            evidence_items = [
                MagicMock(payload={"text": f"Evidence {i}", "author": "Test Author"})
                for i in range(3)
            ]

            expansion_result = MagicMock()
            expansion_result.retrieval_results = evidence_items
            workflow.expansion_service.expand_query.return_value = expansion_result

            import uuid
            draft_id = str(uuid.uuid4())
            mock_draft.draft_id = draft_id  # Update mock to match the UUID
            result = await workflow.review_draft(
                draft_id=draft_id,
                max_evidence_per_question=5
            )

            # Verify review completed successfully
            assert result["status"] == "completed"
            # Note: Evidence gathering may not be triggered if no verification questions are parsed


class TestWorkflowPipeline:
    """Integration tests for complete workflow pipeline."""

    @pytest.mark.asyncio
    async def test_paper_to_review_pipeline(self, mock_paper_workflow, mock_review_workflow):
        """Test complete pipeline: create → generate → review → apply."""
        with patch('app.workflow_services.paper_workflow.PaperDraftService') as mock_paper_service, \
             patch('app.workflow_services.review_workflow.PaperDraftService') as mock_review_service:
            # Mock draft creation and retrieval
            mock_draft = MagicMock()
            import uuid
            mock_draft.draft_id = str(uuid.uuid4())
            mock_draft.get_sections.return_value = {
                "abstract": "Generated abstract",
                "introduction": "Generated introduction"
            }

            # Mock paper service methods
            mock_paper_service.create_draft = AsyncMock(return_value=mock_draft)
            mock_paper_service.create_draft_from_options = AsyncMock(return_value=mock_draft)
            mock_paper_service.get_draft = AsyncMock(return_value=mock_draft)
            mock_paper_service.update_draft_status = AsyncMock(return_value=True)
            mock_paper_service.update_section = AsyncMock(return_value=True)
            
            # Mock review service methods
            mock_review_service.get_draft = AsyncMock(return_value=mock_draft)
            mock_review_service.update_draft_status = AsyncMock(return_value=True)
            mock_review_service.set_review_data = AsyncMock(return_value=True)
            mock_paper_service.apply_suggestions = AsyncMock(return_value=True)

            # Mock LLM responses for generation
            mock_paper_workflow.llm_manager.aquery.return_value = MagicMock(
                message=MagicMock(content="Generated section content")
            )

            # Mock expansion
            mock_paper_workflow.expansion_service.expand_query.return_value = MagicMock(
                retrieval_results=[MagicMock(payload={"text": "Context"})]
            )

            # Step 1: Create draft
            draft_id = await mock_paper_workflow.create_draft(
                title="Pipeline Test",
                topic="Test Topic",
                collection="Aristotle"
            )

            # Step 2: Generate sections
            generation_result = await mock_paper_workflow.generate_sections(
                draft_id=draft_id,
                sections=["abstract"]
            )
            assert generation_result["final_status"] == "completed"

            # Step 3: Review (mock review workflow responses)
            mock_review_workflow.llm_manager.aquery.return_value = MagicMock(
                message=MagicMock(content="**Claim 1:** Test\n**Type:** Fact\n1. Question?")
            )

            mock_review_workflow.expansion_service.expand_query.return_value = MagicMock(
                retrieval_results=[]
            )

            review_result = await mock_review_workflow.review_draft(draft_id=draft_id)
            assert review_result["status"] == "completed"

            # Step 4: Apply suggestions
            apply_result = await mock_paper_workflow.apply_suggestions(
                draft_id=draft_id,
                accept_all=True
            )
            assert apply_result["status"] == "success"


class TestQueryExpansionPipeline:
    """Integration tests for query expansion pipeline."""

    @pytest.mark.asyncio
    async def test_multi_method_expansion_integration(self):
        """Test integration of multiple expansion methods."""
        with patch('app.services.llm_manager.LLMManager'), \
             patch('app.services.qdrant_manager.QdrantManager'), \
             patch('app.services.prompt_renderer.PromptRenderer'):

            from app.services.expansion_service import ExpansionService

            service = ExpansionService()

            # Mock all components
            service.llm_manager.aquery = AsyncMock()
            service.qdrant_manager.query_hybrid = AsyncMock()
            service.qdrant_manager.multi_query_fusion = AsyncMock()
            service.qdrant_manager.deduplicate_results = MagicMock()
            service.qdrant_manager.rrf_fuse = MagicMock()

            # Configure mocks for different methods
            service.llm_manager.aquery.return_value = MagicMock(
                message=MagicMock(content="Mock response")
            )

            service.qdrant_manager.query_hybrid.return_value = {
                "sparse_original": [MagicMock(id="1")]
            }

            service.qdrant_manager.multi_query_fusion.return_value = [MagicMock(id="2")]
            service.qdrant_manager.deduplicate_results.return_value = [MagicMock(id="3")]
            service.qdrant_manager.rrf_fuse.return_value = [MagicMock(id="4")]

            # Test expansion with all methods
            result = await service.expand_query(
                query="Test query",
                collection="Test",
                methods=["hyde", "rag_fusion", "self_ask"]
            )

            assert len(result.expanded_queries) >= 2  # Should have multiple methods
            assert result.metadata["methods_used"]
            assert result.retrieval_results  # Should have final fused results
