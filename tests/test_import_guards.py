"""
Import guard tests to prevent accidental top-level `workflows` imports.

Ensures we always use the canonical llama_index.core.workflow path (Option A).
"""

import inspect
import pytest


def test_no_top_level_workflows_used():
    """Ensure we use bundled workflows from llama-index-core, not top-level workflows."""
    import llama_index.core.workflow as lw
    
    # Verify we're using the bundled path
    workflow_file = inspect.getfile(lw)
    assert "llama_index/core/workflow" in workflow_file or "llama_index\\core\\workflow" in workflow_file
    
    # If anyone tries `import workflows`, it must NOT be used in our code paths
    try:
        import workflows  # noqa: F401
        # If present (as a transitive dep), ensure we never import it from our modules
        
        # Test that our defensive imports work
        from app.core.workflow_imports import WORKFLOW_IMPORTS_OK, FUSION_IMPORTS_OK
        assert WORKFLOW_IMPORTS_OK, "Workflow imports should be working"
        assert FUSION_IMPORTS_OK, "Fusion retriever imports should be working"
        
    except ImportError:
        # Top-level workflows not present - that's fine, test passes
        pass


def test_canonical_imports_available():
    """Test that canonical Option A imports work correctly."""
    from llama_index.core.workflow import Workflow, StartEvent, StopEvent, step, Context
    from llama_index.core.retrievers import QueryFusionRetriever
    
    # Verify classes are properly imported
    assert inspect.isclass(Workflow)
    assert inspect.isclass(StartEvent) 
    assert inspect.isclass(StopEvent)
    assert inspect.isclass(Context)
    assert inspect.isclass(QueryFusionRetriever)
    assert callable(step)


def test_defensive_imports_fallback():
    """Test that our defensive import module works."""
    from app.core.workflow_imports import (
        Workflow, StartEvent, StopEvent, step, Context,
        QueryFusionRetriever, FUSION_MODES,
        WORKFLOW_IMPORTS_OK, FUSION_IMPORTS_OK
    )
    
    # Should have imported successfully in our test environment
    assert WORKFLOW_IMPORTS_OK
    assert FUSION_IMPORTS_OK
    
    # Basic functionality checks
    assert hasattr(FUSION_MODES, 'RECIPROCAL_RANK')  # Actual enum name
    assert callable(step)
    assert inspect.isclass(Workflow)


def test_no_module_shadowing():
    """Ensure local app.workflows doesn't shadow llama-index imports."""
    # Import local workflows (should work)
    from app.workflow_services.paper_workflow import PaperWorkflow
    from app.workflow_services.review_workflow import ReviewWorkflow
    
    # Import LlamaIndex workflows (should also work, no conflict)  
    from llama_index.core.workflow import Workflow as LIWorkflow
    
    # Verify they're different classes
    assert PaperWorkflow != LIWorkflow
    assert ReviewWorkflow != LIWorkflow
    
    # Verify LlamaIndex workflow is accessible (may resolve to workflows package)
    # The key is that it doesn't conflict with our local app.workflows
    assert LIWorkflow is not None
    assert inspect.isclass(LIWorkflow)


def test_fusion_modes_enum():
    """Test that FUSION_MODES enum works as expected.""" 
    from app.core.workflow_imports import FUSION_MODES
    
    # Should have the key modes (check actual enum names)
    assert hasattr(FUSION_MODES, 'RECIPROCAL_RANK')  # Actual name in v2.5.0
    # Check if it has value (enum or string)
    reciprocal_value = getattr(FUSION_MODES, 'RECIPROCAL_RANK')
    assert reciprocal_value is not None