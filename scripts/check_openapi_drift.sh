#!/bin/bash
# Check for OpenAPI schema drift
# This script should be run in CI to detect when openapi_spec.json is out of sync
# REQUIREMENT: FastAPI app must be running at http://localhost:8080

set -e

echo "🔍 Checking OpenAPI schema drift..."

echo "🏥 Checking if FastAPI app is running..."
if ! curl -f -s -m 5 http://localhost:8080/health > /dev/null 2>&1; then
    echo "❌ FastAPI app is not running at http://localhost:8080"
    echo "Please start the application before running this script."
    echo "The OpenAPI schema generation requires a running FastAPI instance."
    exit 1
fi
echo "✅ FastAPI app is running"

# Generate fresh schema from running app
python3 scripts/generate_api_docs.py

# Normalize schema location
if [ -f "docs/openapi_schema.json" ]; then
    echo "✅ Found schema at docs/openapi_schema.json"
elif [ -f "openapi_schema.json" ]; then
    echo "⚠️  Schema generated at repo root, copying to docs/"
    mkdir -p docs
    cp openapi_schema.json docs/openapi_schema.json
else
    echo "❌ Failed to generate OpenAPI schema at any location"
    exit 1
fi

# Check if openapi_spec.json exists
if [ ! -f "openapi_spec.json" ]; then
    echo "⚠️  openapi_spec.json not found - this may be the first run"
    echo "📝 Copying generated schema to openapi_spec.json"
    cp docs/openapi_schema.json openapi_spec.json
    exit 0
fi

# Compare the two files
if diff -q openapi_spec.json docs/openapi_schema.json > /dev/null; then
    echo "✅ OpenAPI schema is in sync"
    exit 0
else
    echo "❌ OpenAPI schema drift detected!"
    echo ""
    echo "The openapi_spec.json file is out of sync with the current API."
    echo "This usually means endpoints were added, modified, or removed without updating the spec."
    echo ""
    echo "To fix this, run:"
    echo "  python3 scripts/generate_api_docs.py"
    echo "  cp docs/openapi_schema.json openapi_spec.json"
    echo "  git add openapi_spec.json"
    echo "  git commit -m 'Update OpenAPI spec'"
    echo ""
    echo "Differences:"
    diff openapi_spec.json docs/openapi_schema.json || true
    exit 1
fi
