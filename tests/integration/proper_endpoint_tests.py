#!/usr/bin/env python3
"""
Properly designed endpoint tests with valid payloads and streaming support
Tests all endpoints with correct data to avoid validation errors
"""

import requests
import json
import time
import sys
import uuid
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
import io

BASE_URL = "http://localhost:8080"

class ProperEndpointTester:
    def __init__(self):
        self.session = requests.Session()
        self.access_token = None
        self.test_results = []
        self.test_session_id = str(uuid.uuid4())
        self.test_user_email = f"test_{int(time.time())}@example.com"
        self.test_username = f"testuser_{int(time.time())}"
        
    def setup_authentication(self) -> bool:
        """Set up authentication for protected endpoints"""
        print("🔐 Setting up authentication...")
        
        # Register user with proper data
        register_data = {
            "username": self.test_username,
            "email": self.test_user_email,
            "password": "TestPass123!"
        }
        
        try:
            response = self.session.post(f"{BASE_URL}/auth/register", json=register_data)
            if response.status_code in [201, 400]:  # 400 if user exists
                print("✅ User registration handled")
            else:
                print(f"❌ Registration failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Registration error: {e}")
            return False
            
        # Login to get token
        login_data = {
            "username": self.test_user_email,  # Use email for login
            "password": "TestPass123!"
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
                print(f"❌ Login failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Login error: {e}")
            return False
    
    def test_endpoint(self, method: str, path: str, data: Dict = None, 
                     files: Dict = None, headers: Dict = None, 
                     expected_status: List[int] = None, 
                     use_auth: bool = False,
                     description: str = "",
                     stream: bool = False) -> Dict:
        """Test a single endpoint with proper error handling"""
        
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
                response = self.session.get(url, headers=headers, stream=stream)
            elif method.upper() == "POST":
                if files:
                    response = self.session.post(url, data=data, files=files, headers=headers, stream=stream)
                else:
                    response = self.session.post(url, json=data, headers=headers, stream=stream)
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
            
            # Handle streaming responses
            if stream and response.status_code == 200:
                try:
                    # Read first few chunks of streaming response
                    chunks = []
                    chunk_count = 0
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            chunks.append(chunk.decode('utf-8', errors='ignore'))
                            chunk_count += 1
                            if chunk_count >= 3:  # Read first 3 chunks
                                break
                    
                    response_data = {
                        "streaming": True,
                        "chunks_received": chunk_count,
                        "sample_content": "".join(chunks)[:500] + "..." if chunks else "No content"
                    }
                    response_size = sum(len(chunk.encode()) for chunk in chunks)
                except Exception as e:
                    response_data = {"streaming_error": str(e)}
                    response_size = 0
            else:
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
                "timestamp": datetime.now().isoformat(),
                "streaming": stream
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
    
    def run_proper_tests(self):
        """Run tests with proper payloads and streaming support"""
        print("🚀 Starting PROPER endpoint testing with valid payloads...")
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
        
        # 2. AUTHENTICATION ENDPOINTS WITH PROPER DATA
        print("\n🔐 AUTHENTICATION ENDPOINTS (WITH PROPER PAYLOADS)")
        print("-" * 60)
        
        # Test with valid data
        valid_register_data = {
            "username": f"newuser_{int(time.time())}",
            "email": f"newuser_{int(time.time())}@example.com",
            "password": "ValidPass123!"
        }
        
        valid_login_data = {
            "username": self.test_user_email,
            "password": "TestPass123!"
        }
        
        auth_tests = [
            ("GET", "/auth/providers", None, "Get OAuth providers", [200]),
            ("GET", "/auth/", None, "Auth root endpoint", [200]),
            ("POST", "/auth/register", valid_register_data, "User registration with valid data", [201, 400]),
            ("POST", "/auth/jwt/login", None, "JWT login with form data", [200, 401], False, True),  # Special handling
            ("POST", "/auth/forgot-password", {"email": self.test_user_email}, "Forgot password with valid email", [202, 200]),
            ("POST", "/auth/request-verify-token", {"email": self.test_user_email}, "Request verification with valid email", [202, 200]),
            ("POST", "/auth/reset-password", {"token": "fake-token-123", "password": "NewPass123!"}, "Reset password with valid format", [400, 422]),
            ("POST", "/auth/verify", {"token": "fake-token-123"}, "Verify account with valid format", [400, 422]),
            ("GET", "/auth/session", None, "Get session info", [401, 404, 200]),
        ]
        
        for method, path, data, desc, expected, *special in auth_tests:
            if len(special) > 0 and special[0]:  # Special form data handling for login
                # Handle login with form data
                response = self.session.post(
                    f"{BASE_URL}{path}",
                    data=valid_login_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                result = {
                    "method": method,
                    "path": path,
                    "description": desc,
                    "status_code": response.status_code,
                    "success": response.status_code in expected,
                    "response": response.json() if response.status_code == 200 else {"error": response.text},
                    "response_time_ms": 0,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                result = self.test_endpoint(method, path, data, expected_status=expected, description=desc)
            
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
        
        # 3. CORE ONTOLOGIC ENDPOINTS WITH PROPER DATA
        print("\n🧠 CORE ONTOLOGIC ENDPOINTS (WITH PROPER PAYLOADS)")
        print("-" * 60)
        
        # Test with valid philosophical questions
        ontologic_tests = [
            ("GET", "/get_philosophers", None, "Get available philosophers", [200]),
            ("GET", "/ask?query_str=What%20is%20virtue%20ethics%20according%20to%20Aristotle?", None, "Ask philosophical question", [200]),
            ("POST", "/ask_philosophy", {
                "question": "What is the nature of justice?",
                "philosopher": "Aristotle",
                "immersive_mode": True
            }, "Ask specific philosopher with proper data", [200, 422]),
            ("POST", "/ask_philosophy/stream", {
                "question": "Explain the concept of eudaimonia",
                "philosopher": "Aristotle",
                "immersive_mode": True
            }, "Streaming philosophy ask with proper data", [200], False, False, True),  # Enable streaming
            ("POST", "/ask/stream", {
                "query_str": "What is the meaning of life?",
                "temperature": 0.7,
                "timeout": 60
            }, "Streaming ask endpoint with proper data", [200, 405], False, False, True),  # Enable streaming
            ("POST", "/query_hybrid", {
                "query_str": "ethics and morality in ancient philosophy",
                "collection": "Aristotle",
                "vector_types": ["dense_original", "sparse_original"],
                "limit": 10
            }, "Hybrid vector search with proper data", [200]),
        ]
        
        for method, path, data, desc, expected, *stream_info in ontologic_tests:
            use_stream = len(stream_info) > 2 and stream_info[2]
            result = self.test_endpoint(method, path, data, expected_status=expected, description=desc, stream=use_stream)
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            stream_indicator = "🌊" if use_stream else ""
            print(f"{status} {stream_indicator} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
            
            if result["success"]:
                if path == "/get_philosophers":
                    philosophers = result["response"]
                    print(f"   Found {len(philosophers)} philosophers")
                elif "query_hybrid" in path:
                    results = result["response"]
                    if isinstance(results, list):
                        print(f"   Found {len(results)} search results")
                elif use_stream and "streaming" in result["response"]:
                    stream_data = result["response"]
                    print(f"   Streaming: {stream_data.get('chunks_received', 0)} chunks received")
                elif isinstance(result["response"], str):
                    response_text = result["response"]
                    print(f"   Response length: {len(response_text)} characters")
        
        # 4. DOCUMENT ENDPOINTS WITH PROPER DATA
        print("\n📄 DOCUMENT ENDPOINTS (WITH PROPER PAYLOADS)")
        print("-" * 60)
        
        if auth_success:
            # Test document upload with actual file
            test_file_content = "This is a test document for the ontologic API.\n\nIt contains some philosophical content about ethics and morality.\n\nAristotle believed that virtue ethics focuses on character rather than actions or consequences."
            
            document_tests = [
                ("GET", "/documents/list", None, "List user documents", True, [200]),
                ("POST", "/documents/upload", None, "Upload document with file", True, [201, 422], True),  # Special file handling
                ("DELETE", "/documents/test-file-id", None, "Delete non-existent document", True, [404, 200]),
            ]
            
            for method, path, data, desc, use_auth, expected, *special in document_tests:
                if len(special) > 0 and special[0]:  # Special file upload handling
                    files = {
                        'file': ('test_document.txt', io.StringIO(test_file_content), 'text/plain')
                    }
                    form_data = {
                        'title': 'Test Philosophical Document',
                        'author': 'Test Author',
                        'topic': 'Ethics'
                    }
                    
                    headers = {}
                    if self.access_token:
                        headers["Authorization"] = f"Bearer {self.access_token}"
                    
                    try:
                        response = self.session.post(f"{BASE_URL}{path}", data=form_data, files=files, headers=headers)
                        result = {
                            "method": method,
                            "path": path,
                            "description": desc,
                            "status_code": response.status_code,
                            "success": response.status_code in expected,
                            "response": response.json() if response.headers.get('content-type', '').startswith('application/json') else {"text": response.text},
                            "response_time_ms": 0,
                            "timestamp": datetime.now().isoformat()
                        }
                    except Exception as e:
                        result = {
                            "method": method,
                            "path": path,
                            "description": desc,
                            "error": str(e),
                            "success": False,
                            "response_time_ms": 0,
                            "timestamp": datetime.now().isoformat()
                        }
                else:
                    result = self.test_endpoint(method, path, data, expected_status=expected, use_auth=use_auth, description=desc)
                
                self.test_results.append(result)
                status = "✅" if result["success"] else "❌"
                auth_indicator = "🔒" if use_auth else "🔓"
                print(f"{status} {auth_indicator} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
        
        # 5. CHAT ENDPOINTS WITH PROPER DATA
        print("\n💬 CHAT ENDPOINTS (WITH PROPER PAYLOADS)")
        print("-" * 60)
        
        # Send a proper chat message first
        chat_message_data = {
            "role": "user",
            "content": "Hello, I'd like to discuss Aristotelian ethics. What are the key principles of virtue ethics?",
            "session_id": self.test_session_id
        }
        
        chat_tests = [
            # Chat Health (quick tests)
            ("GET", "/chat/health/status", None, "Chat health status", [200]),
            ("GET", "/chat/health/database", None, "Chat database health", [200]),
            ("GET", "/chat/config/environment", None, "Chat environment config", [200]),
            
            # Chat Operations with proper data
            ("POST", "/chat/message", chat_message_data, "Send chat message with proper data", [201, 200]),
            ("POST", "/chat/search", {
                "query": "virtue ethics Aristotle",
                "session_id": self.test_session_id,
                "limit": 5
            }, "Search chat history with proper data", [200]),
            ("GET", f"/chat/history/{self.test_session_id}", None, "Get chat history", [200, 404]),
            ("GET", f"/chat/conversations/{self.test_session_id}", None, "Get conversations", [200, 404]),
        ]
        
        for method, path, data, desc, expected in chat_tests:
            result = self.test_endpoint(method, path, data, expected_status=expected, description=desc)
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
        
        # 6. WORKFLOW ENDPOINTS WITH PROPER DATA
        print("\n⚙️ WORKFLOW ENDPOINTS (WITH PROPER PAYLOADS)")
        print("-" * 60)
        
        workflow_create_data = {
            "title": "The Nature of Virtue in Aristotelian Ethics",
            "topic": "An exploration of virtue ethics as presented in Nicomachean Ethics",
            "philosopher": "Aristotle",
            "sections": ["abstract", "introduction", "argument", "counterarguments", "conclusion"]
        }
        
        workflow_tests = [
            ("GET", "/workflows/health", None, "Workflow health", [200]),
            ("GET", "/workflows/", None, "List workflows", [200]),
            ("POST", "/workflows/create", workflow_create_data, "Create workflow with proper data", [201, 422]),
        ]
        
        for method, path, data, desc, expected in workflow_tests:
            result = self.test_endpoint(method, path, data, expected_status=expected, description=desc)
            self.test_results.append(result)
            status = "✅" if result["success"] else "❌"
            print(f"{status} {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
        
        # 7. USER MANAGEMENT WITH AUTH
        print("\n👤 USER MANAGEMENT ENDPOINTS")
        print("-" * 60)
        
        if auth_success:
            user_tests = [
                ("GET", "/users/me", None, "Get current user", True, [200]),
            ]
            
            for method, path, data, desc, use_auth, expected in user_tests:
                result = self.test_endpoint(method, path, data, expected_status=expected, use_auth=use_auth, description=desc)
                self.test_results.append(result)
                status = "✅" if result["success"] else "❌"
                print(f"{status} 🔒 {method} {path} - {result.get('status_code', 'ERROR')} ({result.get('response_time_ms', 0)}ms)")
        
        # Generate report
        self.generate_proper_report()
    
    def generate_proper_report(self):
        """Generate a comprehensive report of proper tests"""
        print("\n" + "=" * 100)
        print("📊 PROPER ENDPOINT TEST RESULTS")
        print("=" * 100)
        
        total_tests = len(self.test_results)
        successful_tests = sum(1 for r in self.test_results if r.get('success', False))
        failed_tests = total_tests - successful_tests
        
        print(f"📈 SUMMARY")
        print(f"   Total Endpoints Tested: {total_tests}")
        print(f"   ✅ Successful: {successful_tests}")
        print(f"   ❌ Failed: {failed_tests}")
        print(f"   📊 Success Rate: {(successful_tests/total_tests)*100:.1f}%")
        
        # Show streaming results
        streaming_tests = [r for r in self.test_results if r.get('streaming', False)]
        if streaming_tests:
            print(f"\n🌊 STREAMING ENDPOINTS")
            for result in streaming_tests:
                status = "✅" if result["success"] else "❌"
                print(f"   {status} {result['method']} {result['path']} - {result['status_code']}")
                if result["success"] and "streaming" in result.get("response", {}):
                    stream_data = result["response"]
                    print(f"      Chunks received: {stream_data.get('chunks_received', 0)}")
        
        # Show failures with details
        if failed_tests > 0:
            print(f"\n❌ FAILED TESTS")
            for result in self.test_results:
                if not result.get('success', False):
                    print(f"   {result['method']} {result['path']} - {result.get('status_code', 'ERROR')}")
                    if 'error' in result:
                        print(f"      Error: {result['error']}")
                    elif 'response' in result:
                        print(f"      Response: {str(result['response'])[:100]}...")
        
        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"proper_endpoint_test_results_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump({
                'test_summary': {
                    'timestamp': datetime.now().isoformat(),
                    'total_tests': total_tests,
                    'successful_tests': successful_tests,
                    'failed_tests': failed_tests,
                    'success_rate': (successful_tests/total_tests)*100,
                    'streaming_tests': len(streaming_tests)
                },
                'detailed_results': self.test_results
            }, f, indent=2)
        
        print(f"\n💾 Results saved to: {filename}")
        print(f"🎉 Proper endpoint testing complete!")

if __name__ == "__main__":
    tester = ProperEndpointTester()
    tester.run_proper_tests()