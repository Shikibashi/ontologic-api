#!/usr/bin/env python3
"""
API Documentation Generator for Ontologic API.
Creates comprehensive documentation with examples, schemas, and usage patterns.
Fetches OpenAPI schema from running FastAPI app.
"""

import json
import sys
import asyncio
import httpx
from typing import Dict, List, Any
from datetime import datetime
from pathlib import Path

class APIDocumentationGenerator:
    def __init__(self, test_results_file: str = "endpoint_test_results.json"):
        self.test_results_file = test_results_file
        self.test_results = []
        
    def load_test_results(self):
        """Load test results from JSON file."""
        try:
            with open(self.test_results_file, 'r') as f:
                self.test_results = json.load(f)
            print(f"✅ Loaded {len(self.test_results)} test results")
        except FileNotFoundError:
            print(f"⚠️  Test results file not found: {self.test_results_file}")
            self.test_results = []
    
    def generate_endpoint_documentation(self) -> str:
        """Generate comprehensive endpoint documentation."""
        
        doc = f"""# Ontologic API - Complete Endpoint Documentation

Generated on: {datetime.now().isoformat()}
Total Endpoints: {len(self.test_results)}

## Table of Contents
- [Health & Monitoring](#health--monitoring)
- [Core Philosophy API](#core-philosophy-api)
- [Authentication](#authentication)
- [User Management](#user-management)
- [Document Management](#document-management)
- [Chat History](#chat-history)
- [Workflows](#workflows)
- [Admin & Backup](#admin--backup)

---

"""
        
        # Group endpoints by category
        categories = {
            "Health & Monitoring": [],
            "Core Philosophy API": [],
            "Authentication": [],
            "User Management": [],
            "Document Management": [],
            "Chat History": [],
            "Workflows": [],
            "Admin & Backup": []
        }
        
        # Categorize endpoints
        for result in self.test_results:
            path = result.get("path", "")
            
            if path.startswith("/health"):
                categories["Health & Monitoring"].append(result)
            elif path in ["/ask", "/ask/stream", "/ask_philosophy", "/ask_philosophy/stream", "/get_philosophers", "/query_hybrid"]:
                categories["Core Philosophy API"].append(result)
            elif path.startswith("/auth"):
                categories["Authentication"].append(result)
            elif path.startswith("/users"):
                categories["User Management"].append(result)
            elif path.startswith("/documents"):
                categories["Document Management"].append(result)
            elif path.startswith("/chat"):
                categories["Chat History"].append(result)
            elif path.startswith("/workflows"):
                categories["Workflows"].append(result)
            elif path.startswith("/admin"):
                categories["Admin & Backup"].append(result)
        
        # Generate documentation for each category
        for category_name, endpoints in categories.items():
            if endpoints:
                doc += self.generate_category_docs(category_name, endpoints)
        
        return doc
    
    def generate_category_docs(self, category_name: str, endpoints: List[Dict]) -> str:
        """Generate documentation for a category of endpoints."""
        
        doc = f"\n## {category_name}\n\n"
        
        for endpoint in sorted(endpoints, key=lambda x: x.get("path", "")):
            doc += self.generate_endpoint_doc(endpoint)
        
        return doc
    
    def generate_endpoint_doc(self, endpoint: Dict) -> str:
        """Generate documentation for a single endpoint."""
        
        method = endpoint.get("method", "").upper()
        path = endpoint.get("path", "")
        description = endpoint.get("description", "No description available")
        status_code = endpoint.get("status_code")
        success = endpoint.get("success", False)
        duration = endpoint.get("duration_ms", 0)
        
        # Status indicator
        status_icon = "✅" if success else "❌"
        
        doc = f"### {status_icon} `{method} {path}`\n\n"
        doc += f"**Description:** {description}\n\n"
        
        # Request information
        if endpoint.get("request_data"):
            doc += "**Request Body:**\n```json\n"
            doc += json.dumps(endpoint["request_data"], indent=2)
            doc += "\n```\n\n"
        
        if endpoint.get("request_params"):
            doc += "**Query Parameters:**\n```json\n"
            doc += json.dumps(endpoint["request_params"], indent=2)
            doc += "\n```\n\n"
        
        # Response information
        doc += f"**Response Status:** `{status_code}`\n"
        doc += f"**Response Time:** {duration}ms\n\n"
        
        if endpoint.get("response_data"):
            doc += "**Response Example:**\n```json\n"
            response_data = endpoint["response_data"]

            truncated = False

            def _truncate(text: str) -> str:
                nonlocal truncated
                if len(text) <= 500:
                    return text
                truncated = True
                truncated_text = text[:500]
                last_newline = truncated_text.rfind("\n")
                if last_newline > 0:
                    truncated_text = truncated_text[:last_newline]
                return truncated_text

            try:
                if isinstance(response_data, str):
                    try:
                        parsed = json.loads(response_data)
                    except (json.JSONDecodeError, TypeError):
                        doc += _truncate(response_data)
                    else:
                        pretty_json = json.dumps(parsed, indent=2)
                        doc += _truncate(pretty_json)
                else:
                    pretty_json = json.dumps(response_data, indent=2)
                    doc += _truncate(pretty_json)
            except (TypeError, ValueError):
                doc += _truncate(str(response_data))

            doc += "\n```\n"
            if truncated:
                doc += "*(Response truncated for brevity - full response available in test results)*\n"
            doc += "\n"
        
        # Usage examples
        doc += self.generate_usage_example(endpoint)
        
        doc += "---\n\n"
        
        return doc
    
    def generate_usage_example(self, endpoint: Dict) -> str:
        """Generate usage examples for an endpoint."""
        
        method = endpoint.get("method", "").upper()
        path = endpoint.get("path", "")
        
        doc = "**Usage Examples:**\n\n"
        
        # cURL example
        curl_cmd = f"curl -X {method}"
        
        if endpoint.get("request_data"):
            curl_cmd += f" \\\n  -H 'Content-Type: application/json' \\\n"
            curl_cmd += f"  -d '{json.dumps(endpoint['request_data'])}' \\\n"
        
        if "auth_required" in endpoint.get("description", "").lower():
            curl_cmd += "  -H 'Authorization: Bearer YOUR_JWT_TOKEN' \\\n"
        
        curl_cmd += f"  http://localhost:8080{path}"
        
        if endpoint.get("request_params"):
            params = "&".join([f"{k}={v}" for k, v in endpoint["request_params"].items()])
            curl_cmd += f"?{params}"
        
        doc += f"```bash\n{curl_cmd}\n```\n\n"
        
        # Python example
        python_example = self.generate_python_example(endpoint)
        if python_example:
            doc += f"```python\n{python_example}\n```\n\n"
        
        return doc
    
    def generate_python_example(self, endpoint: Dict) -> str:
        """Generate Python usage example."""

        method = endpoint.get("method", "").lower()
        path = endpoint.get("path", "")

        example = "import httpx\n\n"
        example += "async with httpx.AsyncClient() as client:\n"

        if endpoint.get("request_data"):
            example += f"    data = {json.dumps(endpoint['request_data'], indent=4)}\n"
            example += f"    response = await client.{method}(\n"
            example += f"        'http://localhost:8080{path}',\n"
            example += f"        json=data\n"
            example += f"    )\n"
        else:
            params_str = ""
            if endpoint.get("request_params"):
                params_str = f", params={json.dumps(endpoint['request_params'])}"

            example += f"    response = await client.{method}(\n"
            example += f"        'http://localhost:8080{path}'{params_str}\n"
            example += f"    )\n"

        example += "    print(response.json())"

        return example

    def _infer_json_schema(self, data: Any, schema_name: str) -> Dict:
        """
        Infer JSON Schema from example data.

        Args:
            data: Example data to infer schema from
            schema_name: Name for the schema (used for complex types)

        Returns:
            JSON Schema object or reference
        """
        if data is None:
            return {"type": "null"}

        if isinstance(data, bool):
            return {"type": "boolean"}

        if isinstance(data, int):
            return {"type": "integer"}

        if isinstance(data, float):
            return {"type": "number"}

        if isinstance(data, str):
            return {"type": "string"}

        if isinstance(data, list):
            if not data:
                return {"type": "array", "items": {}}
            # Infer from first element
            item_schema = self._infer_json_schema(data[0], f"{schema_name}_item")
            return {"type": "array", "items": item_schema}

        if isinstance(data, dict):
            properties = {}
            required = []
            for key, value in data.items():
                properties[key] = self._infer_json_schema(value, f"{schema_name}_{key}")
                required.append(key)

            # Register complex schema
            schema_obj = {
                "type": "object",
                "properties": properties,
                "required": required
            }

            # Store in components.schemas if not already registered
            if not hasattr(self, '_schemas'):
                self._schemas = {}

            self._schemas[schema_name] = schema_obj

            # Return reference
            return {"$ref": f"#/components/schemas/{schema_name}"}

        # Fallback
        return {"type": "string"}

    def _extract_path_parameters(self, path: str) -> List[Dict]:
        """
        Extract path parameters from a path string.

        Supports both {param} and :param syntaxes.

        Args:
            path: The path string (e.g., "/users/{user_id}/posts/{post_id}" or "/users/:user_id")

        Returns:
            List of unique parameter objects
        """
        import re
        params: List[Dict] = []
        seen = set()

        # Existing brace-based parameters
        for match in re.finditer(r'\{([^}]+)\}', path):
            param_name = match.group(1)
            if param_name in seen:
                continue
            seen.add(param_name)

            # Infer type from parameter name
            param_type = "string"
            if param_name.endswith("_id") or param_name == "id":
                param_type = "string"
            elif "limit" in param_name or "count" in param_name or "offset" in param_name:
                param_type = "integer"

            params.append({
                "name": param_name,
                "in": "path",
                "required": True,
                "schema": {"type": param_type}
            })

        # Colon-prefixed parameters (e.g., /users/:user_id)
        for segment in [s for s in path.split('/') if s.startswith(':') and len(s) > 1]:
            param_name = segment[1:]
            if param_name in seen:
                continue
            seen.add(param_name)

            param_type = "string"
            if param_name.endswith("_id") or param_name == "id":
                param_type = "string"
            elif "limit" in param_name or "count" in param_name or "offset" in param_name:
                param_type = "integer"

            params.append({
                "name": param_name,
                "in": "path",
                "required": True,
                "schema": {"type": param_type}
            })

        return params
    
    def generate_openapi_schema(self) -> Dict:
        """Generate OpenAPI 3.0 schema from test results."""

        # Initialize schemas storage
        self._schemas = {}

        schema = {
            "openapi": "3.1.0",
            "info": {
                "title": "Ontologic API",
                "description": "Semantic knowledge retrieval API for philosophical texts",
                "version": "1.0.0",
                "contact": {
                    "name": "Ontologic AI",
                    "url": "https://ontologicai.com"
                }
            },
            "servers": [
                {
                    "url": "http://localhost:8080",
                    "description": "Development server"
                }
            ],
            "paths": {},
            "components": {
                "schemas": {},
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "bearerFormat": "JWT"
                    }
                }
            }
        }

        # Add paths from test results
        for endpoint in self.test_results:
            path = endpoint.get("path", "")
            method = endpoint.get("method", "").lower()
            status_code = endpoint.get("status_code", 200)
            description = endpoint.get("description", "")

            if path not in schema["paths"]:
                schema["paths"][path] = {}

            operation = {
                "summary": description,
                "responses": {
                    str(status_code): {
                        "description": "Response",
                        "content": {
                            "application/json": {
                                "example": endpoint.get("response_data")
                            }
                        }
                    }
                }
            }

            # Add security requirements for protected endpoints
            if status_code == 401 or "auth" in description.lower() or "unauthorized" in str(endpoint.get("response_data", "")).lower():
                operation["security"] = [{"bearerAuth": []}]

            # Add request body schema
            if endpoint.get("request_data"):
                try:
                    request_schema_name = f"{path.replace('/', '_')}_{method}_request"
                    request_schema = self._infer_json_schema(endpoint["request_data"], request_schema_name)

                    operation["requestBody"] = {
                        "content": {
                            "application/json": {
                                "schema": request_schema,
                                "example": endpoint["request_data"]
                            }
                        }
                    }
                except Exception as e:
                    # Log schema generation failure for visibility
                    print(f"⚠️  Failed to generate request schema for {method.upper()} {path}: {type(e).__name__}: {e}")
                    # Fallback to just example
                    operation["requestBody"] = {
                        "content": {
                            "application/json": {
                                "example": endpoint["request_data"]
                            }
                        }
                    }

            # Add response schema
            if endpoint.get("response_data"):
                try:
                    response_schema_name = f"{path.replace('/', '_')}_{method}_response_{status_code}"
                    response_schema = self._infer_json_schema(endpoint["response_data"], response_schema_name)

                    operation["responses"][str(status_code)]["content"]["application/json"]["schema"] = response_schema
                except Exception as e:
                    # Log schema generation failure for visibility
                    print(f"⚠️  Failed to generate response schema for {method.upper()} {path} (status {status_code}): {type(e).__name__}: {e}")
                    # Keep only example on error
                    pass

            # Add path parameters
            path_params = self._extract_path_parameters(path)
            if path_params:
                operation["parameters"] = path_params

            schema["paths"][path][method] = operation

        # Add collected schemas to components
        schema["components"]["schemas"] = self._schemas

        return schema
    
    def generate_all_documentation(self):
        """Generate all documentation formats."""
        
        self.load_test_results()
        
        # Generate markdown documentation
        markdown_doc = self.generate_endpoint_documentation()
        with open("API_DOCUMENTATION.md", "w") as f:
            f.write(markdown_doc)
        print("✅ Generated API_DOCUMENTATION.md")
        
        # Generate OpenAPI schema
        openapi_schema = self.generate_openapi_schema()
        save_openapi_schema(openapi_schema, "docs/openapi_schema.json")
        print("✅ Generated docs/openapi_schema.json")
        
        # Generate summary statistics
        self.generate_summary_stats()
    
    def generate_summary_stats(self):
        """Generate summary statistics."""
        
        total_endpoints = len(self.test_results)
        successful = len([r for r in self.test_results if r.get("success", False)])
        failed = total_endpoints - successful
        
        avg_response_time = sum([r.get("duration_ms", 0) for r in self.test_results]) / total_endpoints if total_endpoints > 0 else 0
        
        stats = {
            "total_endpoints": total_endpoints,
            "successful_tests": successful,
            "failed_tests": failed,
            "success_rate": f"{(successful/total_endpoints*100):.1f}%" if total_endpoints > 0 else "0%",
            "average_response_time_ms": round(avg_response_time, 2),
            "generated_at": datetime.now().isoformat()
        }
        
        with open("api_test_summary.json", "w") as f:
            json.dump(stats, f, indent=2)
        
        print("✅ Generated api_test_summary.json")
        print(f"📊 Summary: {successful}/{total_endpoints} endpoints successful ({stats['success_rate']})")

async def fetch_openapi_from_app(base_url: str = "http://localhost:8080") -> Dict:
    """
    Fetch OpenAPI schema from running FastAPI app.

    Args:
        base_url: Base URL of the running app

    Returns:
        OpenAPI schema dictionary

    Raises:
        Exception: If app is not running or fetching fails
    """
    async with httpx.AsyncClient() as client:
        try:
            # First check if app is healthy
            print(f"🏥 Checking if FastAPI app is running at {base_url}...")
            health_response = await client.get(f"{base_url}/health", timeout=5.0)
            health_response.raise_for_status()
            print("✅ FastAPI app is running")

            # Fetch OpenAPI schema
            print("📡 Fetching OpenAPI schema...")
            response = await client.get(f"{base_url}/openapi.json", timeout=10.0)
            response.raise_for_status()

            schema = response.json()

            # Validate basic OpenAPI structure
            required_fields = ["openapi", "info", "paths"]
            missing_fields = [f for f in required_fields if f not in schema]
            if missing_fields:
                raise ValueError(f"Invalid OpenAPI schema: missing required fields {missing_fields}")

            # Validate OpenAPI version
            openapi_version = schema.get("openapi", "")
            if not openapi_version.startswith("3."):
                print(f"⚠️  Warning: Expected OpenAPI 3.x, got {openapi_version}")

            print(f"✅ Fetched valid OpenAPI {openapi_version} schema with {len(schema.get('paths', {}))} endpoints")

            return schema
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                print(f"❌ Endpoint not found: {e.request.url}")
                print("   This might not be a FastAPI application")
            else:
                print(f"❌ Failed to fetch OpenAPI schema: HTTP {e.response.status_code}")
            raise
        except httpx.ConnectError:
            print(f"❌ Cannot connect to {base_url}")
            print("   Make sure the FastAPI app is running:")
            print(f"   curl {base_url}/health")
            raise
        except httpx.TimeoutException:
            print(f"❌ Request timed out connecting to {base_url}")
            print("   The application might be overloaded or unresponsive")
            raise
        except httpx.RequestError as e:
            print(f"❌ Failed to connect to {base_url}: {e}")
            raise
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON response from {base_url}/openapi.json: {e}")
            raise
        except Exception as e:
            print(f"❌ Unexpected error fetching OpenAPI schema: {e}")
            raise

def save_openapi_schema(schema: Dict, output_path: str = "docs/openapi_schema.json"):
    """Save OpenAPI schema to file."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump(schema, f, indent=2)

    print(f"✅ Saved OpenAPI schema to {output_path}")

async def main_async():
    """Main documentation generation function (async version)."""
    print("📡 Fetching OpenAPI schema from running app...")

    try:
        # Fetch OpenAPI schema from running app
        openapi_schema = await fetch_openapi_from_app()

        # Save to docs/openapi_schema.json
        save_openapi_schema(openapi_schema, "docs/openapi_schema.json")

        print("✅ OpenAPI schema generation complete")
        return 0

    except Exception as e:
        print(f"❌ Schema generation failed: {e}")
        return 1

def main():
    """Main documentation generation function."""
    # Try async version first (fetch from running app)
    try:
        exit_code = asyncio.run(main_async())
        if exit_code != 0:
            print("⚠️  Async version failed, falling back to test results generation...")
            # Fallback to original implementation
            generator = APIDocumentationGenerator()
            generator.generate_all_documentation()
            # Fallback succeeded, set exit code to 0
            exit_code = 0
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to run async version: {e}")
        print("⚠️  Falling back to test results generation...")
        try:
            # Fallback to original implementation
            generator = APIDocumentationGenerator()
            generator.generate_all_documentation()
            sys.exit(0)
        except Exception as fallback_error:
            print(f"❌ Fallback also failed: {fallback_error}")
            sys.exit(1)

if __name__ == "__main__":
    main()
