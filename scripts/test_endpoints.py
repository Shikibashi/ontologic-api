#!/usr/bin/env python3
"""
Simple script to test endpoint accessibility without importing the full app.
"""

import requests
import json
from typing import List, Dict

# Assume API is running on localhost:8080
BASE_URL = "http://localhost:8080"

def test_endpoint(method: str, path: str, data: dict = None) -> Dict:
    """Test a single endpoint and return result."""
    url = f"{BASE_URL}{path}"
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, timeout=5)
        elif method.upper() == "POST":
            response = requests.post(url, json=data, timeout=5)
        elif method.upper() == "DELETE":
            response = requests.delete(url, timeout=5)
        else:
            return {"status": "unsupported_method", "method": method}
        
        # Endpoint is accessible if it returns success (2xx) or client error except 404
        is_success = 200 <= response.status_code < 300

        return {
            "status": "success" if is_success else "error",
            "status_code": response.status_code,
            "accessible": (is_success or
                          (400 <= response.status_code < 500 and response.status_code != 404))
        }
    except requests.exceptions.ConnectionError:
        return {"status": "connection_error", "accessible": False}
    except requests.exceptions.Timeout:
        return {"status": "timeout", "accessible": True}  # Timeout means endpoint exists
    except Exception as e:
        return {"status": "error", "error": str(e), "accessible": False}

def main():
    """Test key endpoints to see what's accessible."""
    
    print("=== Testing Ontologic API Endpoint Accessibility ===\n")
    print(f"Base URL: {BASE_URL}")
    print("Note: This tests if endpoints exist, not if they work correctly.\n")
    
    # Define endpoints to test
    endpoints_to_test = [
        # Core API
        ("GET", "/health"),
        ("GET", "/ask"),
        ("GET", "/get_philosophers"),
        
        # Documents
        ("GET", "/documents/list"),
        
        # Chat History (should be enabled)
        ("GET", "/chat/config/status"),
        ("GET", "/chat/health/status"),
        
        # Auth Sessions (should be enabled)
        ("GET", "/auth/providers"),
        ("GET", "/auth/"),
        
        # Workflows
        ("GET", "/workflows/health"),
        ("GET", "/workflows/"),
        
        # Admin/Backup
        ("GET", "/admin/backup/health"),
        
        # OAuth (should be disabled/404)
        ("GET", "/auth/google"),
    ]
    
    results = []
    for method, path in endpoints_to_test:
        print(f"Testing {method:6} {path:30} ... ", end="")
        result = test_endpoint(method, path)
        results.append((method, path, result))
        
        if result["status"] == "connection_error":
            print("❌ API not running")
        elif result.get("accessible", False):
            print(f"✅ Accessible ({result.get('status_code', 'N/A')})")
        else:
            print(f"❌ Not found ({result.get('status_code', 'N/A')})")
    
    print("\n=== Summary ===")
    accessible = [r for r in results if r[2].get("accessible", False)]
    not_accessible = [r for r in results if not r[2].get("accessible", False)]
    
    print(f"Accessible endpoints: {len(accessible)}")
    print(f"Not accessible: {len(not_accessible)}")
    
    if not_accessible:
        print("\nEndpoints that should be checked:")
        for method, path, result in not_accessible:
            if result["status"] != "connection_error":
                print(f"  {method} {path} - {result.get('status_code', 'N/A')}")

if __name__ == "__main__":
    main()