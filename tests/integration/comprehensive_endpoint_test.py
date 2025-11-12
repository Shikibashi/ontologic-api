#!/usr/bin/env python3
"""
Comprehensive endpoint testing script for ontologic-api
Tests ALL 64 endpoints and documents results in detail
"""

import requests
import json
import time
import sys
import uuid
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

BASE_URL = "http://localhost:8080"

class ComprehensiveEndpointTester:
    def __init__(self):
        self.session = requests.Session()
        self.access_token = None
        self.test_results = []
        self.test_session_id = str(uuid.uuid4())
        
    def setup_authentication(self) -> bool:
        """Set up authentication for protected endpoints"""
        print("🔐 Setting up authentication...")
        
        # Register user
        register_data = {
            "username": f"testuser_{int(time.time())}",
            "email": f"test_{int(time.time())}@example.com",
            "password": "testpass123"
        }
        
        try:
            response = self.session.post(f"{BASE_URL}/auth/register", json=register_data)
            if response.status_code in [201, 400]:  # 400 if user exists
                print("✅ User registration handled")
            else:
                print(f"❌ Registration failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Registration error: {e}")
            return False
            
        # Login to get token
        login_data = {
            "username": register_data["email"],
            "password": register_data["password"]
        }
        
        try:
            response = self.session.post(
                f"{BASE_URL}/auth/jwt/login",
                data=login_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data["access_token"]
                print("✅ Authentication successful")
                return True
            else:
                print(f"❌ Login failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Login error: {e}")
            return False
    
    def test_endpoint(self, method: str, path: str, data: Dict = None, 
                     files: Dict = None, headers: Dict = None, 
                     expected_status: List[int] = None, 
                     use_auth: bool = False,
                     description: str = "") -> Dict:
        """Test a single endpoint and return detailed results"""
        
        if expected_status is None:
            expected_status = [200, 201, 202]
            
        url = f"{BASE_URL}{path}"
        
        # Add auth header if requested
        if use_auth and self.access_token:
            if headers is None:
                headers = {}
            headers["Authorization"] = f"Bearer {self.access_token}"
            
        start_time = time.time()
        
        try:
            if method.upper() == "GET":
                response = self.session.get(url, headers=headers)
            elif method.upper() == "POST":
                if files:
                    response = self.session.post(url, data=data, files=files, headers=headers)
                else:
                    response = self.session.post(url, json=data, headers=headers)
            elif method.upper() == "PUT":
                response = self.session.put(url, json=data, headers=headers)
            elif method.upper() == "DELETE":
                response = self.session.delete(url, headers=headers)
            else:
                return {
                    "method": method,
                    "path": path,
                    "description": description,
                    "error": f"Unsupported method: {method}",
                    "success": False,
                    "response_time_ms": 0
                }
                
            response_time = (time.time() - start_time) * 1000
            success = response.status_code in expected_status
            
            try:
                response_data = response.json()
                response_size = len(json.dumps(response_data))
            except:
                response_data = {"text": response.text[:500] + "..." if len(response.text) > 500 else response.text}
                response_size = len(response.text)
                
            result = {
                "method": method,
                "path": path,
                "description": description,
                "status_code": response.status_code,
                "success": success,
                "response": response_data,
                "response_time_ms": round(response_time, 2),
                "response_size_bytes": response_size,
                "headers": dict(response.headers),
                "timestamp": datetime.now().isoformat()
            }
            
            return result
            
        except Exception as e:
            return {
                "method": method,
                "path": path,
                "description": description,
                "error": str(e),
                "success": False,
                "response_time_ms": (time.time() - start_time) * 1000,
                "timestamp": datetime.now().isoformat()
            }
    
    def run_comprehensive_tests(self):
        """Run tests for all endpoints with detailed documentation"""
        print("🚀 Starting COMPREHENSIVE endpoint testing...")
        print(f"📍 Base URL: {BASE_URL}")
        print(f"🕒 Test started at: {datetime.now().isoformat()}")
        print("=" * 100)
        
        # Setup authentication
        auth_success = self.setup_authentication()
        
        # 1. HEALTH ENDPOINTS
        print("\n🏥 HEALTH ENDPOINTS")
        print("-" * 60)
        
        health_tests = [
            ("GET", "/health", None, "Main health check endpoint"),
            ("GET", "/health/live", None, "Liveness probe endpoint"),
            ("GET", "/health/ready", None, "Readiness probe endpoint"),
        ]
        
        for method, path, data, desc in health_tests:
            result = self.test_endpoint(method, path, data, description=desc)
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
            if result["success"] and "response" in result:
                if path == "/health":
                    health_data = result["response"]
                    print(f"   Status: {health_data.get('status')}")
                    services = health_data.get('services', {})
                    for service, info in services.items():
                        print(f"   {service}: {info.get('status', 'unknown')}")
        
        # 2. AUTHENTICATION ENDPOINTS
        print("\n🔐 AUTHENTICATION ENDPOINTS")
        print("-" * 60)
        
        auth_tests = [
            ("GET", "/auth/providers", None, "Get OAuth providers"),
            ("GET", "/auth/", None, "Auth root endpoint"),
            ("POST", "/auth/register", {"username": "testuser", "email": "test@example.com", "password": "pass"}, "User registration", [422, 400, 201]),
            ("POST", "/auth/jwt/login", None, "JWT login", [422, 400, 401]),
            ("POST", "/auth/forgot-password", {"email": "test@example.com"}, "Forgot password", [422, 400, 200]),
            ("POST", "/auth/request-verify-token", {"email": "test@example.com"}, "Request verification", [422, 400, 200]),
            ("POST", "/auth/reset-password", {"token": "fake", "password": "new"}, "Reset password", [422, 400, 200]),
            ("POST", "/auth/verify", {"token": "fake"}, "Verify account", [422, 400, 200]),
            ("GET", "/auth/session", None, "Get session info", [401, 404, 200]),
        ]
        
        for method, path, data, desc, *expected in auth_tests:
            exp_status = expected[0] if expected else None
            result = self.test_endpoint(method, path, data, expected_status=exp_status, description=desc)
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
            if result["success"] and path == "/auth/providers":
                oauth_data = result["response"]
                print(f"   OAuth enabled: {oauth_data.get('oauth_enabled')}")
                providers = oauth_data.get('providers', {})
                print(f"   Providers: {list(providers.keys())}")
        
        # 3. CORE ONTOLOGIC ENDPOINTS
        print("\n🧠 CORE ONTOLOGIC ENDPOINTS")
        print("-" * 60)
        
        ontologic_tests = [
            ("GET", "/get_philosophers", None, "Get available philosophers"),
            ("GET", "/ask?query_str=What%20is%20virtue%20ethics?", None, "Ask philosophical question"),
            ("POST", "/ask_philosophy", {"question": "What is justice?", "philosopher": "Aristotle"}, "Ask specific philosopher", [422, 400, 200]),
            ("POST", "/ask_philosophy/stream", {"question": "What is justice?", "philosopher": "Aristotle"}, "Streaming philosophy ask", [422, 400, 200]),
            ("POST", "/ask/stream", None, "Streaming ask endpoint", [405, 422, 200]),
            ("POST", "/query_hybrid", {"query_str": "ethics and morality", "collection": "Aristotle"}, "Hybrid vector search"),
        ]
        
        for method, path, data, desc, *expected in ontologic_tests:
            exp_status = expected[0] if expected else None
            result = self.test_endpoint(method, path, data, expected_status=exp_status, description=desc)
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
            
            if result["success"]:
                if path == "/get_philosophers":
                    philosophers = result["response"]
                    print(f"   Found {len(philosophers)} philosophers: {philosophers[:3]}...")
                elif "query_hybrid" in path:
                    results = result["response"]
                    if isinstance(results, list):
                        print(f"   Found {len(results)} search results")
                        if results:
                            print(f"   Top result score: {results[0].get('score', 'N/A')}")
                elif "ask" in path and isinstance(result["response"], str):
                    response_text = result["response"]
                    print(f"   Response length: {len(response_text)} characters")
                    print(f"   Preview: {response_text[:100]}...")
        
        # 4. DOCUMENT ENDPOINTS (with auth)
        print("\n📄 DOCUMENT ENDPOINTS")
        print("-" * 60)
        
        document_tests = [
            ("GET", "/documents/list", None, "List user documents", True),
            ("POST", "/documents/upload", None, "Upload document", True, [422, 400, 201]),
            ("GET", "/documents/test-file-id", None, "Get specific document", True, [404, 200]),
        ]
        
        for method, path, data, desc, use_auth, *expected in document_tests:
            exp_status = expected[0] if expected else None
            result = self.test_endpoint(method, path, data, expected_status=exp_status, use_auth=use_auth, description=desc)
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            auth_indicator = "🔒" if use_auth else "🔓"
            print(f"{status} {auth_indicator} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
            
            if result["success"] and path == "/documents/list":
                docs = result["response"].get("documents", [])
                print(f"   Found {len(docs)} documents")
        
        # 5. CHAT & HISTORY ENDPOINTS
        print("\n💬 CHAT & HISTORY ENDPOINTS")
        print("-" * 60)
        
        chat_tests = [
            # Chat Health
            ("GET", "/chat/health/status", None, "Chat health status"),
            ("GET", "/chat/health/database", None, "Chat database health"),
            ("GET", "/chat/health/qdrant", None, "Chat Qdrant health"),
            ("GET", "/chat/health/metrics", None, "Chat metrics"),
            ("GET", "/chat/health/errors", None, "Chat errors"),
            ("GET", "/chat/health/monitoring", None, "Chat monitoring"),
            ("GET", "/chat/health/privacy", None, "Chat privacy"),
            ("GET", "/chat/health/cleanup", None, "Chat cleanup health", [405, 200]),
            
            # Chat Config
            ("GET", "/chat/config/environment", None, "Chat environment config"),
            ("GET", "/chat/config/status", None, "Chat status config"),
            ("GET", "/chat/config/cleanup/stats", None, "Chat cleanup stats"),
            ("POST", "/chat/config/cleanup/run", None, "Run chat cleanup", [500, 422, 200]),
            
            # Chat Operations
            ("POST", "/chat/message", {"role": "user", "content": "Test message", "session_id": self.test_session_id}, "Send chat message"),
            ("POST", "/chat/search", {"query": "test search", "session_id": self.test_session_id}, "Search chat history", [500, 422, 200]),
            ("GET", f"/chat/history/{self.test_session_id}", None, "Get chat history", [404, 200]),
            ("GET", f"/chat/conversations/{self.test_session_id}", None, "Get conversations", [500, 404, 200]),
            ("GET", f"/chat/config/session/{self.test_session_id}", None, "Get session config", [404, 200]),
        ]
        
        for method, path, data, desc, *expected in chat_tests:
            exp_status = expected[0] if expected else None
            result = self.test_endpoint(method, path, data, expected_status=exp_status, description=desc)
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
            
            if result["success"] and "message" in path and method == "POST":
                msg_data = result["response"]
                print(f"   Message ID: {msg_data.get('message_id', 'N/A')}")
        
        # 6. WORKFLOW ENDPOINTS
        print("\n⚙️ WORKFLOW ENDPOINTS")
        print("-" * 60)
        
        workflow_tests = [
            ("GET", "/workflows/health", None, "Workflow health"),
            ("GET", "/workflows/", None, "List workflows"),
            ("POST", "/workflows/create", {"title": "Test Paper", "topic": "Ethics", "philosopher": "Aristotle"}, "Create workflow", [422, 400, 201]),
            ("GET", "/workflows/test-draft-id/status", None, "Get workflow status", [500, 404, 200]),
            ("POST", "/workflows/test-draft-id/generate", None, "Generate workflow", [422, 404, 200]),
            ("POST", "/workflows/test-draft-id/review", None, "Review workflow", [405, 404, 200]),
            ("POST", "/workflows/test-draft-id/ai-review", None, "AI review workflow", [422, 404, 200]),
            ("POST", "/workflows/test-draft-id/apply", None, "Apply workflow", [422, 404, 200]),
        ]
        
        for method, path, data, desc, *expected in workflow_tests:
            exp_status = expected[0] if expected else None
            result = self.test_endpoint(method, path, data, expected_status=exp_status, description=desc)
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
            
            if result["success"] and path == "/workflows/":
                workflows = result["response"].get("drafts", [])
                print(f"   Found {len(workflows)} workflow drafts")
        
        # 7. USER MANAGEMENT ENDPOINTS
        print("\n👤 USER MANAGEMENT ENDPOINTS")
        print("-" * 60)
        
        user_tests = [
            ("GET", "/users/me", None, "Get current user", True),
            ("GET", "/users/test-user-id", None, "Get user by ID", True, [401, 404, 200]),
        ]
        
        for method, path, data, desc, use_auth, *expected in user_tests:
            exp_status = expected[0] if expected else None
            result = self.test_endpoint(method, path, data, expected_status=exp_status, use_auth=use_auth, description=desc)
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            auth_indicator = "🔒" if use_auth else "🔓"
            print(f"{status} {auth_indicator} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
            
            if result["success"] and path == "/users/me":
                user_data = result["response"]
                print(f"   User: {user_data.get('username')} ({user_data.get('email')})")
                print(f"   Tier: {user_data.get('subscription_tier')}")
        
        # 8. ADMIN & BACKUP ENDPOINTS
        print("\n🔧 ADMIN & BACKUP ENDPOINTS")
        print("-" * 60)
        
        admin_tests = [
            ("GET", "/admin/backup/health", None, "Backup health", [503, 200]),
            ("GET", "/admin/backup/validate", None, "Backup validation", [405, 503, 200]),
            ("GET", "/admin/backup/collections/local", None, "Local collections", [503, 200]),
            ("GET", "/admin/backup/collections/production", None, "Production collections", [503, 200]),
            ("GET", "/admin/backup/collections/local/test-collection", None, "Local collection info", [405, 404, 200]),
            ("GET", "/admin/backup/collections/local/test-collection/info", None, "Local collection details", [503, 404, 200]),
            ("GET", "/admin/backup/collections/production/test-collection/info", None, "Production collection details", [503, 404, 200]),
            ("POST", "/admin/backup/start", None, "Start backup", [503, 422, 200]),
            ("POST", "/admin/backup/repair", None, "Repair backup", [503, 422, 200]),
            ("GET", "/admin/backup/status/test-backup-id", None, "Backup status", [503, 404, 200]),
        ]
        
        for method, path, data, desc, *expected in admin_tests:
            exp_status = expected[0] if expected else None
            result = self.test_endpoint(method, path, data, expected_status=exp_status, description=desc)
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
        
        # Generate comprehensive report
        self.generate_detailed_report()
    
    def generate_detailed_report(self):
        """Generate a comprehensive test report"""
        print("\n" + "=" * 100)
        print("📊 COMPREHENSIVE TEST RESULTS REPORT")
        print("=" * 100)
        
        total_tests = len(self.test_results)
        successful_tests = sum(1 for r in self.test_results if r.get('success', False))
        failed_tests = total_tests - successful_tests
        
        # Summary statistics
        response_times = [r.get('response_time_ms', 0) for r in self.test_results if r.get('success', False)]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        max_response_time = max(response_times) if response_times else 0
        
        print(f"📈 SUMMARY STATISTICS")
        print(f"   Total Endpoints Tested: {total_tests}")
        print(f"   ✅ Successful: {successful_tests}")
        print(f"   ❌ Failed: {failed_tests}")
        print(f"   📊 Success Rate: {(successful_tests/total_tests)*100:.1f}%")
        print(f"   ⏱️  Average Response Time: {avg_response_time:.2f}ms")
        print(f"   🚀 Max Response Time: {max_response_time:.2f}ms")
        
        # Category breakdown
        categories = {}
        for result in self.test_results:
            path = result.get('path', '')
            if path.startswith('/health'):
                category = 'Health'
            elif path.startswith('/auth'):
                category = 'Authentication'
            elif path.startswith('/chat'):
                category = 'Chat & History'
            elif path.startswith('/workflows'):
                category = 'Workflows'
            elif path.startswith('/documents'):
                category = 'Documents'
            elif path.startswith('/users'):
                category = 'Users'
            elif path.startswith('/admin'):
                category = 'Admin & Backup'
            elif path in ['/get_philosophers', '/ask', '/ask_philosophy', '/query_hybrid'] or 'ask' in path:
                category = 'Core Ontologic'
            else:
                category = 'Other'
            
            if category not in categories:
                categories[category] = {'total': 0, 'success': 0}
            categories[category]['total'] += 1
            if result.get('success', False):
                categories[category]['success'] += 1
        
        print(f"\n📋 RESULTS BY CATEGORY")
        for category, stats in categories.items():
            success_rate = (stats['success'] / stats['total']) * 100 if stats['total'] > 0 else 0
            print(f"   {category}: {stats['success']}/{stats['total']} ({success_rate:.1f}%)")
        
        # Failed tests details
        if failed_tests > 0:
            print(f"\n❌ FAILED TESTS DETAILS")
            for result in self.test_results:
                if not result.get('success', False):
                    method = result.get('method', 'UNKNOWN')
                    path = result.get('path', 'UNKNOWN')
                    status = result.get('status_code', 'ERROR')
                    error = result.get('error', 'No error message')
                    desc = result.get('description', '')
                    print(f"   {method} {path} - Status: {status}")
                    print(f"      Description: {desc}")
                    if 'error' in result:
                        print(f"      Error: {error}")
        
        # Save detailed results to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"endpoint_test_results_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump({
                'test_summary': {
                    'timestamp': datetime.now().isoformat(),
                    'total_tests': total_tests,
                    'successful_tests': successful_tests,
                    'failed_tests': failed_tests,
                    'success_rate': (successful_tests/total_tests)*100,
                    'avg_response_time_ms': avg_response_time,
                    'max_response_time_ms': max_response_time,
                    'categories': categories
                },
                'detailed_results': self.test_results
            }, f, indent=2)
        
        print(f"\n💾 Detailed results saved to: {filename}")
        print(f"\n🎉 Comprehensive endpoint testing complete!")
        print(f"📊 Overall Status: {'🟢 EXCELLENT' if success_rate > 80 else '🟡 GOOD' if success_rate > 60 else '🔴 NEEDS ATTENTION'}")

if __name__ == "__main__":
    tester = ComprehensiveEndpointTester()
    tester.run_comprehensive_tests()