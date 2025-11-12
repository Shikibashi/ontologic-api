#!/bin/bash
# Pre-commit check to prevent top-level 'workflows' imports (Option A hardening)

echo "🔍 Checking for prohibited workflow imports..."

# Check for top-level workflows imports (excluding defensive fallbacks and test code)
prohibited_imports=$(grep -R --line-number -E 'from +workflows +import|import +workflows' app tests 2>/dev/null | \
    grep -v '# type: ignore' | \
    grep -v '# noqa' | \
    grep -v 'test_import_guards.py' | \
    grep -v 'workflow_imports.py')

if [ ! -z "$prohibited_imports" ]; then
    echo "❌ Do not import top-level 'workflows' (use llama_index.core.workflow)"
    echo "$prohibited_imports"
    echo "   Use: from llama_index.core.workflow import Workflow, StartEvent, StopEvent, step, Context"
    exit 1
fi

# Check for legacy llama_index.retrievers.fusion imports (excluding defensive fallbacks)
legacy_fusion=$(grep -R --line-number 'from llama_index\.retrievers\.fusion import' app tests 2>/dev/null | \
    grep -v '# legacy fallback' | \
    grep -v 'workflow_imports.py')
if [ ! -z "$legacy_fusion" ]; then
    echo "❌ Use canonical path: from llama_index.core.retrievers import QueryFusionRetriever"
    echo "$legacy_fusion"
    exit 1
fi

echo "✅ Import checks passed - using canonical Option A paths"
exit 0