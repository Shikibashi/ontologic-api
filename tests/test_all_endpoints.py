#!/usr/bin/env python3
"""
Comprehensive endpoint testing suite for ontologic-api
Tests all endpoints based on OpenAPI specification
"""

import requests
from requests.exceptions import Timeout as RequestsTimeout, ConnectionError as RequestsConnectionError
import time
import sys
import os
from typing import Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum

class TestResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    ERROR = "ERROR"

@dataclass
class EndpointTest:
    method: str
    path: str
    description: str
    requires_auth: bool = False
    requires_data: bool = False
    test_data: Optional[Dict] = None
    expected_status: int = 200
    skip_reason: Optional[str] = None
    timeout: Optional[float] = None  # Optional per-endpoint timeout override (seconds)

class APITester:
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.session = requests.Session()
        self.auth_token = None
        self.results = []
        
    def log_result(self, test: EndpointTest, result: TestResult, 
                   status_code: Optional[int] = None, response_data: Any = None, 
                   error: Optional[str] = None):
        """Log test result"""
        result_data = {
            'method': test.method,
            'path': test.path,
            'description': test.description,
            'result': result.value,
            'status_code': status_code,
            'error': error,
            'timestamp': time.time()
        }
        self.results.append(result_data)
        
        # Print result
        status_str = f"[{status_code}]" if status_code else ""
        if result == TestResult.PASS:
            print(f"✅ {test.method} {test.path} {status_str} - {test.description}")
        elif result == TestResult.SKIP:
            print(f"⏭️  {test.method} {test.path} - SKIPPED: {test.skip_reason}")
        elif result == TestResult.FAIL:
            print(f"❌ {test.method} {test.path} {status_str} - FAILED: {error}")
        else:
            print(f"🔥 {test.method} {test.path} {status_str} - ERROR: {error}")
    
    def test_endpoint(self, test: EndpointTest) -> TestResult:
        """Test a single endpoint"""
        if test.skip_reason:
            self.log_result(test, TestResult.SKIP)
            return TestResult.SKIP
            
        try:
            url = f"{self.base_url}{test.path}"
            headers = {'Content-Type': 'application/json'}
            # Determine timeout (default 30s, can be overridden per test)
            default_timeout = float(os.getenv("API_TEST_DEFAULT_TIMEOUT", "30"))
            timeout = test.timeout if test.timeout is not None else default_timeout
            
            # Add auth if required and available
            if test.requires_auth and self.auth_token:
                headers['Authorization'] = f'Bearer {self.auth_token}'
            
            # Make request
            if test.method == 'GET':
                response = self.session.get(url, headers=headers, timeout=timeout)
            elif test.method == 'POST':
                data = test.test_data or {}
                response = self.session.post(url, json=data, headers=headers, timeout=timeout)
            elif test.method == 'PUT':
                data = test.test_data or {}
                response = self.session.put(url, json=data, headers=headers, timeout=timeout)
            elif test.method == 'DELETE':
                response = self.session.delete(url, headers=headers, timeout=timeout)
            elif test.method == 'PATCH':
                data = test.test_data or {}
                response = self.session.patch(url, json=data, headers=headers, timeout=timeout)
            else:
                self.log_result(test, TestResult.ERROR, error=f"Unsupported method: {test.method}")
                return TestResult.ERROR
            
            # Check result
            if response.status_code == test.expected_status:
                self.log_result(test, TestResult.PASS, response.status_code)
                return TestResult.PASS
            elif response.status_code == 401 and test.requires_auth and not self.auth_token:
                # Expected auth failure
                self.log_result(test, TestResult.PASS, response.status_code,
                              error="Expected auth failure (no token)")
                return TestResult.PASS
            elif response.status_code == 422:
                if test.expected_status == 422:
                    # Expected validation error
                    self.log_result(test, TestResult.PASS, response.status_code,
                                  error="Validation error (expected)")
                    return TestResult.PASS
                else:
                    # Unexpected validation error
                    try:
                        error_detail = response.json().get('detail', 'Unknown error')
                    except Exception:
                        error_detail = response.text[:200]
                    self.log_result(test, TestResult.FAIL, response.status_code,
                                  error=f"Unexpected validation error: {error_detail}")
                    return TestResult.FAIL
            else:
                try:
                    error_detail = response.json().get('detail', 'Unknown error')
                except Exception:
                    error_detail = response.text[:200]
                self.log_result(test, TestResult.FAIL, response.status_code, 
                              error=error_detail)
                return TestResult.FAIL
                
        except RequestsTimeout:
            self.log_result(test, TestResult.ERROR, error="Request timeout")
            return TestResult.ERROR
        except RequestsConnectionError:
            self.log_result(test, TestResult.ERROR, error="Connection error")
            return TestResult.ERROR
        except Exception as e:
            self.log_result(test, TestResult.ERROR, error=str(e))
            return TestResult.ERROR
    
    def run_all_tests(self):
        """Run all endpoint tests"""
        print("🚀 Starting comprehensive API endpoint testing...")
        print(f"📍 Base URL: {self.base_url}")
        print("=" * 80)
        
        # Environment-aware flags
        HAS_QDRANT_API_KEY = bool(os.getenv("QDRANT_API_KEY"))

        # Define all tests based on OpenAPI spec
        tests = [
            # Health endpoints
            EndpointTest("GET", "/health", "Comprehensive health check"),
            EndpointTest("GET", "/health/ready", "Readiness probe"),
            EndpointTest("GET", "/health/live", "Liveness probe"),
            
            # Core API endpoints
            EndpointTest("GET", "/get_philosophers", "Get available philosophers"),
            EndpointTest("GET", "/ask", "Ask base model (GET)", 
                        skip_reason="Requires query parameter"),
            
            # Philosophy endpoints
            EndpointTest("POST", "/ask_philosophy", "Ask philosophy question",
                        requires_auth=True, requires_data=True,
                        test_data={
                            "query_str": "What is the nature of reality?",
                            "collection": "Aristotle"
                        },
                        timeout=120.0),
            EndpointTest("POST", "/ask_philosophy/stream", "Ask philosophy question (stream)",
                        requires_auth=True, requires_data=True,
                        test_data={
                            "query_str": "What is ethics?",
                            "collection": "Aristotle"
                        }),
            
            # Hybrid query endpoint
            EndpointTest("POST", "/query_hybrid", "Hybrid query endpoint",
                        requires_data=True,
                        test_data={
                            "query_str": "What is knowledge?",
                            "collection": "Aristotle"
                        }),
            
            # Auth endpoints (will fail without proper setup, but should respond)
            EndpointTest("POST", "/auth/jwt/login", "JWT login",
                        expected_status=422,  # Expect validation error without data
                        test_data={}),
            EndpointTest("POST", "/auth/jwt/logout", "JWT logout",
                        requires_auth=True, expected_status=401),
            EndpointTest("POST", "/auth/register", "User registration",
                        expected_status=422,  # Expect validation error without proper data
                        test_data={}),
            EndpointTest("POST", "/auth/forgot-password", "Forgot password",
                        expected_status=422,  # Expect validation error
                        test_data={}),
            EndpointTest("POST", "/auth/reset-password", "Reset password",
                        expected_status=422,  # Expect validation error
                        test_data={}),
            EndpointTest("POST", "/auth/request-verify-token", "Request verify token",
                        expected_status=422,  # Expect validation error
                        test_data={}),
            EndpointTest("POST", "/auth/verify", "Verify user",
                        expected_status=422,  # Expect validation error
                        test_data={}),
            
            # User endpoints
            EndpointTest("GET", "/users/me", "Get current user",
                        requires_auth=True, expected_status=401),
            EndpointTest("PATCH", "/users/me", "Update current user",
                        requires_auth=True, expected_status=401),
            EndpointTest("GET", "/users/test-id", "Get user by ID",
                        requires_auth=True, expected_status=401),
            
            # Document endpoints
            EndpointTest("GET", "/documents/list", "List documents",
                        requires_auth=True, expected_status=401),
            EndpointTest("POST", "/documents/upload", "Upload document",
                        requires_auth=True, expected_status=401),
            
            # Chat endpoints
            # With auth optional in dev, validation will trigger 422 for empty payloads
            EndpointTest("POST", "/chat/message", "Send chat message",
                        requires_auth=False, expected_status=422),
            EndpointTest("GET", "/chat/history/test-session", "Get chat history",
                        requires_auth=False, expected_status=200),
            EndpointTest("POST", "/chat/search", "Search chat history",
                        requires_auth=False, expected_status=422),
            EndpointTest("GET", "/chat/health/status", "Chat health status"),
            EndpointTest("GET", "/chat/config/status", "Chat config status"),
            
            # Workflow endpoints
            EndpointTest("GET", "/workflows/", "List workflows"),
            EndpointTest("POST", "/workflows/create", "Create workflow",
                        expected_status=422,  # Expect validation error
                        test_data={}),
            EndpointTest("GET", "/workflows/health", "Workflow health check"),
            
            # Payment endpoints
            EndpointTest("GET", "/payments/subscription", "Get subscription",
                        requires_auth=True, expected_status=401),
            EndpointTest("POST", "/payments/checkout", "Create checkout",
                        requires_auth=True, expected_status=401),
            EndpointTest("GET", "/payments/usage", "Get usage stats",
                        requires_auth=True, expected_status=401),
            
        ]

        # Admin backup endpoints (conditionally include based on env)
        if HAS_QDRANT_API_KEY:
            tests.extend([
                EndpointTest("GET", "/admin/backup/health", "Backup health check"),
                EndpointTest("GET", "/admin/backup/collections/production", "List production collections"),
                EndpointTest("GET", "/admin/backup/collections/local", "List local collections"),
            ])
        else:
            tests.extend([
                EndpointTest("GET", "/admin/backup/health", "Backup health check",
                             skip_reason="Requires QDRANT_API_KEY"),
                EndpointTest("GET", "/admin/backup/collections/production", "List production collections",
                             skip_reason="Requires QDRANT_API_KEY"),
                EndpointTest("GET", "/admin/backup/collections/local", "List local collections",
                             skip_reason="Requires QDRANT_API_KEY"),
            ])
        
        # Run tests
        total_tests = len(tests)
        passed = 0
        failed = 0
        skipped = 0
        errors = 0
        
        for i, test in enumerate(tests, 1):
            print(f"\n[{i}/{total_tests}] Testing {test.method} {test.path}")
            result = self.test_endpoint(test)
            
            if result == TestResult.PASS:
                passed += 1
            elif result == TestResult.FAIL:
                failed += 1
            elif result == TestResult.SKIP:
                skipped += 1
            else:
                errors += 1
        
        # Print summary
        print("\n" + "=" * 80)
        print("📊 TEST SUMMARY")
        print("=" * 80)
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"⏭️  Skipped: {skipped}")
        print(f"🔥 Errors: {errors}")
        
        success_rate = (passed / (total_tests - skipped)) * 100 if (total_tests - skipped) > 0 else 0
        print(f"📈 Success Rate: {success_rate:.1f}%")
        
        if failed > 0 or errors > 0:
            print("\n❗ Failed/Error Tests:")
            for result in self.results:
                if result['result'] in ['FAIL', 'ERROR']:
                    print(f"  - {result['method']} {result['path']}: {result['error']}")
        
        return {
            'total': total_tests,
            'passed': passed,
            'failed': failed,
            'skipped': skipped,
            'errors': errors,
            'success_rate': success_rate
        }

def main():
    """Main test runner"""
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    else:
        base_url = "http://localhost:8080"
    
    tester = APITester(base_url)
    
    # Check if server is running
    try:
        requests.get(f"{base_url}/health", timeout=5)
        print(f"🟢 Server is running at {base_url}")
    except RequestsConnectionError:
        print(f"🔴 Server is not running at {base_url}")
        print("Please start the server first with: uv run python app/main.py --env dev --host 0.0.0.0 --port 8080")
        sys.exit(1)
    except Exception as e:
        print(f"🔴 Error connecting to server: {e}")
        sys.exit(1)
    
    # Run tests
    results = tester.run_all_tests()
    
    # Exit with appropriate code
    if results['failed'] > 0 or results['errors'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()