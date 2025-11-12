"""
Defensive imports for LlamaIndex Workflows (Option A hardening).

Provides graceful fallbacks and ensures we always use the canonical bundled path,
staying resilient across minor version bumps.
"""

# Workflow imports with defensive fallbacks
try:
    from llama_index.core.workflow import Workflow, StartEvent, StopEvent, step, Context
    WORKFLOW_IMPORTS_OK = True
except ImportError as e:
    # Fallback for older versions or broken installs
    try:
        # Try legacy path (very old versions)
        from workflows import Workflow, StartEvent, StopEvent, step, Context  # type: ignore
        WORKFLOW_IMPORTS_OK = True
    except ImportError:
        # Create stub classes to prevent total failure
        class Workflow:  # type: ignore
            pass
        
        class StartEvent:  # type: ignore
            pass
            
        class StopEvent:  # type: ignore
            def __init__(self, result=None):
                self.result = result
                
        class Context:  # type: ignore
            def send_event(self, event):
                pass
                
        def step(func):  # type: ignore
            return func
            
        WORKFLOW_IMPORTS_OK = False

# Fusion retriever imports with graceful fallback
try:
    from llama_index.core.retrievers import QueryFusionRetriever
    from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
    FUSION_IMPORTS_OK = True
except ImportError:
    # Try legacy path for older versions (defensive fallback)
    try:
        from llama_index.retrievers.fusion import QueryFusionRetriever  # type: ignore # legacy fallback
        
        # Create enum-like fallback for FUSION_MODES
        class _FusionModes:
            RECIPROCAL_RANK = "reciprocal_rank"  # Updated to match actual enum
            RELATIVE_SCORE = "relative_score" 
            DIST_BASED_SCORE = "dist_based_score"
            SIMPLE = "simple"
            
        FUSION_MODES = _FusionModes()
        FUSION_IMPORTS_OK = True
    except ImportError as e:
        # Create stub for total failure case
        class QueryFusionRetriever:  # type: ignore
            def __init__(self, *args, **kwargs):
                raise ImportError("QueryFusionRetriever not available") from e
                
        class _FusionModes:
            RECIPROCAL_RANK = "reciprocal_rank"
            
        FUSION_MODES = _FusionModes()
        FUSION_IMPORTS_OK = False

# Export what we managed to import
__all__ = [
    'Workflow', 'StartEvent', 'StopEvent', 'step', 'Context',
    'QueryFusionRetriever', 'FUSION_MODES',
    'WORKFLOW_IMPORTS_OK', 'FUSION_IMPORTS_OK'
]