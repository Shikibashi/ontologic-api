#!/usr/bin/env python3
"""
Comprehensive endpoint testing script for ontologic-api
Tests all 64 endpoints systematically
"""

import requests
import json
import time
import sys
from typing import Dict, Any, List, Tuple
import uuid

BASE_URL = "http://localhost:8080"

class EndpointTester:
    def __init__(self):
        self.session = requests.Session()
        self.results = []
        self.auth_token = None
        self.session_id = None
        
    def test_endpoint(self, method: str, path: str, data: Dict = None, 
                     files: Dict = None, headers: Dict = None, 
                     expected_status: List[int] = None) -> Tuple[bool, Dict]:
        """Test a single endpoint and return success status and response info"""
        if expected_status is None:
            expected_status = [200, 201, 202]
            
        url = f"{BASE_URL}{path}"
        
        # Add auth header if we have a token
        if self.auth_token and headers is None:
            headers = {"Authorization": f"Bearer {self.auth_token}"}
        elif self.auth_token and headers:
            headers["Authorization"] = f"Bearer {self.auth_token}"
            
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
                return False, {"error": f"Unsupported method: {method}"}
                
            success = response.status_code in expected_status
            
            try:
                response_data = response.json()
            except:
                response_data = {"text": response.text[:200]}
                
            result = {
                "method": method,
                "path": path,
                "status_code": response.status_code,
                "success": success,
                "response": response_data,
                "headers": dict(response.headers)
            }
            
            return success, result
            
        except Exception as e:
            return False, {
                "method": method,
                "path": path,
                "error": str(e),
                "success": False
            }
    
    def run_all_tests(self):
        """Run tests for all endpoints"""
        print("🚀 Starting comprehensive endpoint testing...")
        print(f"📍 Base URL: {BASE_URL}")
        print("=" * 80)
        
        # 1. Health Endpoints
        self.test_health_endpoints()
        
        # 2. Authentication Endpoints  
        self.test_auth_endpoints()
        
        # 3. Core Ontologic Endpoints
        self.test_ontologic_endpoints()
        
        # 4. Document Management
        self.test_document_endpoints()
        
        # 5. Chat & History
        self.test_chat_endpoints()
        
        # 6. Workflows
        self.test_workflow_endpoints()
        
        # 7. Admin & Backup
        self.test_admin_endpoints()
        
        # 8. User Management
        self.test_user_endpoints()
        
        # Print summary
        self.print_summary()
        
    def test_health_endpoints(self):
        """Test health check endpoints"""
        print("\n🏥 Testing Health Endpoints")
        print("-" * 40)
        
        endpoints = [
            ("GET", "/health"),
            ("GET", "/health/live"),
            ("GET", "/health/ready"),
        ]
        
        for method, path in endpoints:
            success, result = self.test_endpoint(method, path)
            self.results.append(result)
            status = "✅" if success else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')}")
            
    def test_auth_endpoints(self):
        """Test authentication endpoints"""
        print("\n🔐 Testing Authentication Endpoints")
        print("-" * 40)
        
        # Test auth providers first
        success, result = self.test_endpoint("GET", "/auth/providers")
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /auth/providers - {result.get('status_code', 'ERROR')}")
        
        # Test JWT login (expect 422 for missing data)
        success, result = self.test_endpoint("POST", "/auth/jwt/login", 
                                           expected_status=[422, 400, 401])
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} POST /auth/jwt/login - {result.get('status_code', 'ERROR')}")
        
        # Test register (expect 422 for missing data)
        success, result = self.test_endpoint("POST", "/auth/register",
                                           expected_status=[422, 400, 201])
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} POST /auth/register - {result.get('status_code', 'ERROR')}")
        
        # Other auth endpoints
        auth_endpoints = [
            ("GET", "/auth/"),
            ("POST", "/auth/forgot-password", [422, 400, 200]),
            ("POST", "/auth/request-verify-token", [422, 400, 200]),
            ("POST", "/auth/reset-password", [422, 400, 200]),
            ("POST", "/auth/verify", [422, 400, 200]),
            ("GET", "/auth/session", [401, 404, 200]),
        ]
        
        for method, path, *expected in auth_endpoints:
            exp_status = expected[0] if expected else None
            success, result = self.test_endpoint(method, path, expected_status=exp_status)
            self.results.append(result)
            status = "✅" if success else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')}")
            
    def test_ontologic_endpoints(self):
        """Test core ontologic endpoints"""
        print("\n🧠 Testing Core Ontologic Endpoints")
        print("-" * 40)
        
        # Test get philosophers
        success, result = self.test_endpoint("GET", "/get_philosophers")
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /get_philosophers - {result.get('status_code', 'ERROR')}")
        
        # Test ask endpoint with sample question
        ask_data = {
            "question": "What is the meaning of life?",
            "philosopher": "Aristotle"
        }
        success, result = self.test_endpoint("POST", "/ask", data=ask_data)
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} POST /ask - {result.get('status_code', 'ERROR')}")
        
        # Test ask philosophy
        success, result = self.test_endpoint("POST", "/ask_philosophy", data=ask_data)
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} POST /ask_philosophy - {result.get('status_code', 'ERROR')}")
        
        # Test streaming endpoints (expect different status codes)
        success, result = self.test_endpoint("POST", "/ask/stream", data=ask_data,
                                           expected_status=[200, 422, 400])
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} POST /ask/stream - {result.get('status_code', 'ERROR')}")
        
        success, result = self.test_endpoint("POST", "/ask_philosophy/stream", data=ask_data,
                                           expected_status=[200, 422, 400])
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} POST /ask_philosophy/stream - {result.get('status_code', 'ERROR')}")
        
        # Test hybrid query
        hybrid_data = {
            "query": "ethics and morality",
            "limit": 5
        }
        success, result = self.test_endpoint("POST", "/query_hybrid", data=hybrid_data)
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} POST /query_hybrid - {result.get('status_code', 'ERROR')}")
        
    def test_document_endpoints(self):
        """Test document management endpoints"""
        print("\n📄 Testing Document Endpoints")
        print("-" * 40)
        
        # Test list documents
        success, result = self.test_endpoint("GET", "/documents/list")
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /documents/list - {result.get('status_code', 'ERROR')}")
        
        # Test upload (expect 422 for missing file)
        success, result = self.test_endpoint("POST", "/documents/upload",
                                           expected_status=[422, 400, 201])
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} POST /documents/upload - {result.get('status_code', 'ERROR')}")
        
        # Test get document (expect 404 for non-existent)
        success, result = self.test_endpoint("GET", "/documents/test-file-id",
                                           expected_status=[404, 200])
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /documents/{{file_id}} - {result.get('status_code', 'ERROR')}")
        
    def test_chat_endpoints(self):
        """Test chat and history endpoints"""
        print("\n💬 Testing Chat & History Endpoints")
        print("-" * 40)
        
        # Generate a test session ID
        test_session_id = str(uuid.uuid4())
        
        # Chat health endpoints
        chat_health_endpoints = [
            ("GET", "/chat/health/status"),
            ("GET", "/chat/health/database"),
            ("GET", "/chat/health/qdrant"),
            ("GET", "/chat/health/metrics"),
            ("GET", "/chat/health/errors"),
            ("GET", "/chat/health/monitoring"),
            ("GET", "/chat/health/privacy"),
            ("GET", "/chat/health/cleanup"),
        ]
        
        for method, path in chat_health_endpoints:
            success, result = self.test_endpoint(method, path)
            self.results.append(result)
            status = "✅" if success else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')}")
        
        # Chat config endpoints
        config_endpoints = [
            ("GET", "/chat/config/environment"),
            ("GET", "/chat/config/status"),
            ("GET", "/chat/config/cleanup/stats"),
            ("POST", "/chat/config/cleanup/run", [200, 422]),
        ]
        
        for method, path, *expected in config_endpoints:
            exp_status = expected[0] if expected else None
            success, result = self.test_endpoint(method, path, expected_status=exp_status)
            self.results.append(result)
            status = "✅" if success else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')}")
        
        # Chat message endpoint
        message_data = {
            "message": "Hello, this is a test message",
            "session_id": test_session_id
        }
        success, result = self.test_endpoint("POST", "/chat/message", data=message_data)
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} POST /chat/message - {result.get('status_code', 'ERROR')}")
        
        # Chat search
        search_data = {
            "query": "test search",
            "session_id": test_session_id
        }
        success, result = self.test_endpoint("POST", "/chat/search", data=search_data)
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} POST /chat/search - {result.get('status_code', 'ERROR')}")
        
        # History endpoints
        success, result = self.test_endpoint("GET", f"/chat/history/{test_session_id}")
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /chat/history/{{session_id}} - {result.get('status_code', 'ERROR')}")
        
        success, result = self.test_endpoint("GET", f"/chat/conversations/{test_session_id}")
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /chat/conversations/{{session_id}} - {result.get('status_code', 'ERROR')}")
        
        success, result = self.test_endpoint("GET", f"/chat/config/session/{test_session_id}")
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /chat/config/session/{{session_id}} - {result.get('status_code', 'ERROR')}")
        
    def test_workflow_endpoints(self):
        """Test workflow endpoints"""
        print("\n⚙️ Testing Workflow Endpoints")
        print("-" * 40)
        
        # Workflow health
        success, result = self.test_endpoint("GET", "/workflows/health")
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /workflows/health - {result.get('status_code', 'ERROR')}")
        
        # List workflows
        success, result = self.test_endpoint("GET", "/workflows/")
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /workflows/ - {result.get('status_code', 'ERROR')}")
        
        # Create workflow
        workflow_data = {
            "title": "Test Philosophical Paper",
            "topic": "The nature of consciousness",
            "philosopher": "Aristotle"
        }
        success, result = self.test_endpoint("POST", "/workflows/create", data=workflow_data)
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} POST /workflows/create - {result.get('status_code', 'ERROR')}")
        
        # Test workflow operations with dummy ID (expect 404)
        test_draft_id = "test-draft-id"
        workflow_ops = [
            ("GET", f"/workflows/{test_draft_id}/status", [404, 200]),
            ("POST", f"/workflows/{test_draft_id}/generate", [404, 200, 422]),
            ("POST", f"/workflows/{test_draft_id}/review", [404, 200, 422]),
            ("POST", f"/workflows/{test_draft_id}/ai-review", [404, 200, 422]),
            ("POST", f"/workflows/{test_draft_id}/apply", [404, 200, 422]),
        ]
        
        for method, path, expected_status in workflow_ops:
            success, result = self.test_endpoint(method, path, expected_status=expected_status)
            self.results.append(result)
            status = "✅" if success else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')}")
            
    def test_admin_endpoints(self):
        """Test admin and backup endpoints"""
        print("\n🔧 Testing Admin & Backup Endpoints")
        print("-" * 40)
        
        # Backup health
        success, result = self.test_endpoint("GET", "/admin/backup/health")
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /admin/backup/health - {result.get('status_code', 'ERROR')}")
        
        # Backup validation
        success, result = self.test_endpoint("GET", "/admin/backup/validate")
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /admin/backup/validate - {result.get('status_code', 'ERROR')}")
        
        # Collections endpoints
        collections_endpoints = [
            ("GET", "/admin/backup/collections/local"),
            ("GET", "/admin/backup/collections/production"),
        ]
        
        for method, path in collections_endpoints:
            success, result = self.test_endpoint(method, path)
            self.results.append(result)
            status = "✅" if success else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')}")
        
        # Test collection info (expect 404 for non-existent)
        test_collection = "test-collection"
        info_endpoints = [
            ("GET", f"/admin/backup/collections/local/{test_collection}", [404, 200]),
            ("GET", f"/admin/backup/collections/local/{test_collection}/info", [404, 200]),
            ("GET", f"/admin/backup/collections/production/{test_collection}/info", [404, 200]),
        ]
        
        for method, path, expected_status in info_endpoints:
            success, result = self.test_endpoint(method, path, expected_status=expected_status)
            self.results.append(result)
            status = "✅" if success else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')}")
        
        # Backup operations (expect 422 for missing data)
        backup_ops = [
            ("POST", "/admin/backup/start", [422, 400, 200]),
            ("POST", "/admin/backup/repair", [422, 400, 200]),
        ]
        
        for method, path, expected_status in backup_ops:
            success, result = self.test_endpoint(method, path, expected_status=expected_status)
            self.results.append(result)
            status = "✅" if success else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')}")
        
        # Test backup status (expect 404 for non-existent)
        success, result = self.test_endpoint("GET", "/admin/backup/status/test-backup-id",
                                           expected_status=[404, 200])
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /admin/backup/status/{{backup_id}} - {result.get('status_code', 'ERROR')}")
        
    def test_user_endpoints(self):
        """Test user management endpoints"""
        print("\n👤 Testing User Management Endpoints")
        print("-" * 40)
        
        # Test get current user (expect 401 without auth)
        success, result = self.test_endpoint("GET", "/users/me", expected_status=[401, 200])
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /users/me - {result.get('status_code', 'ERROR')}")
        
        # Test get user by ID (expect 401/404)
        success, result = self.test_endpoint("GET", "/users/test-user-id", 
                                           expected_status=[401, 404, 200])
        self.results.append(result)
        status = "✅" if success else "❌"
        print(f"{status} GET /users/{{id}} - {result.get('status_code', 'ERROR')}")
        
    def print_summary(self):
        """Print test results summary"""
        print("\n" + "=" * 80)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 80)
        
        total_tests = len(self.results)
        successful_tests = sum(1 for r in self.results if r.get('success', False))
        failed_tests = total_tests - successful_tests
        
        print(f"Total Endpoints Tested: {total_tests}")
        print(f"✅ Successful: {successful_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"Success Rate: {(successful_tests/total_tests)*100:.1f}%")
        
        if failed_tests > 0:
            print(f"\n❌ Failed Tests:")
            for result in self.results:
                if not result.get('success', False):
                    method = result.get('method', 'UNKNOWN')
                    path = result.get('path', 'UNKNOWN')
                    status = result.get('status_code', 'ERROR')
                    error = result.get('error', 'No error message')
                    print(f"   {method} {path} - Status: {status} - {error}")
        
        print("\n🎉 Endpoint testing complete!")

if __name__ == "__main__":
    tester = EndpointTester()
    tester.run_all_tests()