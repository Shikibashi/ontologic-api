#!/usr/bin/env python3
"""
Final perfect endpoint tests with correct payloads for all endpoints
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

class PerfectEndpointTester:
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
        
        # Register user
        register_data = {
            "username": self.test_username,
            "email": self.test_user_email,
            "password": "TestPass123!"
        }
        
        try:
            response = self.session.post(f"{BASE_URL}/auth/register", json=register_data)
            if response.status_code in [201, 400]:
                print("✅ User registration handled")
            else:
                print(f"❌ Registration failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Registration error: {e}")
            return False
            
        # Login with correct form data
        try:
            response = self.session.post(
                f"{BASE_URL}/auth/jwt/login",
                data=f"username={self.test_user_email}&password=TestPass123!",
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
    
    def test_streaming_endpoint(self, url: str, data: Dict, headers: Dict = None) -> Dict:
        """Test streaming endpoints properly"""
        try:
            response = self.session.post(url, json=data, headers=headers, stream=True)
            
            if response.status_code == 200:
                # Read streaming content
                chunks = []
                chunk_count = 0
                total_content = ""
                
                for chunk in response.iter_content(chunk_size=1024, decode_unicode=True):
                    if chunk:
                        chunks.append(chunk)
                        total_content += chunk
                        chunk_count += 1
                        if chunk_count >= 5:  # Read first 5 chunks
                            break
                
                return {
                    "status_code": 200,
                    "success": True,
                    "streaming": True,
                    "chunks_received": chunk_count,
                    "total_content_length": len(total_content),
                    "sample_content": total_content[:300] + "..." if len(total_content) > 300 else total_content
                }
            else:
                try:
                    error_data = response.json()
                except:
                    error_data = {"text": response.text}
                
                return {
                    "status_code": response.status_code,
                    "success": False,
                    "response": error_data
                }
                
        except Exception as e:
            return {
                "status_code": 0,
                "success": False,
                "error": str(e)
            }
    
    def run_perfect_tests(self):
        """Run perfect tests with all correct payloads"""
        print("🎯 Starting PERFECT endpoint testing...")
        print(f"📍 Base URL: {BASE_URL}")
        print("=" * 80)
        
        # Setup authentication
        auth_success = self.setup_authentication()
        
        # Test results summary
        results = {
            "health": [],
            "auth": [],
            "core": [],
            "streaming": [],
            "documents": [],
            "chat": [],
            "workflows": [],
            "users": []
        }
        
        # 1. HEALTH ENDPOINTS
        print("\n🏥 HEALTH ENDPOINTS")
        print("-" * 40)
        
        health_endpoints = [
            ("GET", "/health"),
            ("GET", "/health/live"),
            ("GET", "/health/ready")
        ]
        
        for method, path in health_endpoints:
            try:
                response = self.session.get(f"{BASE_URL}{path}")
                success = response.status_code == 200
                results["health"].append({
                    "endpoint": f"{method} {path}",
                    "status": response.status_code,
                    "success": success,
                    "response_time": 0
                })
                status = "✅" if success else "❌"
                print(f"{status} {method} {path} - {response.status_code}")
            except Exception as e:
                print(f"❌ {method} {path} - ERROR: {e}")
        
        # 2. AUTHENTICATION ENDPOINTS
        print("\n🔐 AUTHENTICATION ENDPOINTS")
        print("-" * 40)
        
        # Test OAuth providers
        try:
            response = self.session.get(f"{BASE_URL}/auth/providers")
            success = response.status_code == 200
            results["auth"].append({
                "endpoint": "GET /auth/providers",
                "status": response.status_code,
                "success": success
            })
            status = "✅" if success else "❌"
            print(f"{status} GET /auth/providers - {response.status_code}")
            if success:
                data = response.json()
                print(f"   OAuth enabled: {data.get('oauth_enabled')}")
                print(f"   Providers: {list(data.get('providers', {}).keys())}")
        except Exception as e:
            print(f"❌ GET /auth/providers - ERROR: {e}")
        
        # Test JWT login with correct format
        if auth_success:
            print("✅ JWT Login - 200 (already tested during setup)")
            results["auth"].append({
                "endpoint": "POST /auth/jwt/login",
                "status": 200,
                "success": True
            })
        
        # Test forgot password
        try:
            response = self.session.post(f"{BASE_URL}/auth/forgot-password", 
                                       json={"email": self.test_user_email})
            success = response.status_code in [200, 202]
            results["auth"].append({
                "endpoint": "POST /auth/forgot-password",
                "status": response.status_code,
                "success": success
            })
            status = "✅" if success else "❌"
            print(f"{status} POST /auth/forgot-password - {response.status_code}")
        except Exception as e:
            print(f"❌ POST /auth/forgot-password - ERROR: {e}")
        
        # 3. CORE ONTOLOGIC ENDPOINTS
        print("\n🧠 CORE ONTOLOGIC ENDPOINTS")
        print("-" * 40)
        
        # Get philosophers
        try:
            response = self.session.get(f"{BASE_URL}/get_philosophers")
            success = response.status_code == 200
            results["core"].append({
                "endpoint": "GET /get_philosophers",
                "status": response.status_code,
                "success": success
            })
            status = "✅" if success else "❌"
            print(f"{status} GET /get_philosophers - {response.status_code}")
            if success:
                philosophers = response.json()
                print(f"   Found {len(philosophers)} philosophers")
        except Exception as e:
            print(f"❌ GET /get_philosophers - ERROR: {e}")
        
        # Ask question
        try:
            response = self.session.get(f"{BASE_URL}/ask?query_str=What%20is%20virtue%20ethics?")
            success = response.status_code == 200
            results["core"].append({
                "endpoint": "GET /ask",
                "status": response.status_code,
                "success": success
            })
            status = "✅" if success else "❌"
            print(f"{status} GET /ask - {response.status_code}")
            if success:
                answer = response.text
                print(f"   Response length: {len(answer)} characters")
        except Exception as e:
            print(f"❌ GET /ask - ERROR: {e}")
        
        # Hybrid query
        try:
            hybrid_data = {
                "query_str": "virtue ethics and moral character",
                "collection": "Aristotle"
            }
            response = self.session.post(f"{BASE_URL}/query_hybrid", json=hybrid_data)
            success = response.status_code == 200
            results["core"].append({
                "endpoint": "POST /query_hybrid",
                "status": response.status_code,
                "success": success
            })
            status = "✅" if success else "❌"
            print(f"{status} POST /query_hybrid - {response.status_code}")
            if success:
                results_data = response.json()
                print(f"   Found {len(results_data)} search results")
        except Exception as e:
            print(f"❌ POST /query_hybrid - ERROR: {e}")
        
        # 4. STREAMING ENDPOINTS
        print("\n🌊 STREAMING ENDPOINTS")
        print("-" * 40)
        
        # Test ask_philosophy/stream with correct HybridQueryRequest format
        try:
            stream_data = {
                "query_str": "What is eudaimonia in Aristotelian ethics?",
                "collection": "Aristotle"
            }
            result = self.test_streaming_endpoint(f"{BASE_URL}/ask_philosophy/stream", stream_data)
            results["streaming"].append({
                "endpoint": "POST /ask_philosophy/stream",
                "status": result["status_code"],
                "success": result["success"],
                "streaming": result.get("streaming", False)
            })
            status = "✅" if result["success"] else "❌"
            print(f"{status} POST /ask_philosophy/stream - {result['status_code']}")
            if result["success"]:
                print(f"   Streaming: {result.get('chunks_received', 0)} chunks received")
                print(f"   Content length: {result.get('total_content_length', 0)} characters")
            elif "response" in result:
                print(f"   Error: {result['response']}")
        except Exception as e:
            print(f"❌ POST /ask_philosophy/stream - ERROR: {e}")
        
        # Test ask/stream
        try:
            stream_data = {
                "query_str": "What is the meaning of life?",
                "temperature": 0.7
            }
            result = self.test_streaming_endpoint(f"{BASE_URL}/ask/stream", stream_data)
            results["streaming"].append({
                "endpoint": "POST /ask/stream",
                "status": result["status_code"],
                "success": result.get("success", False)
            })
            status = "✅" if result.get("success", False) else "❌"
            print(f"{status} POST /ask/stream - {result['status_code']}")
            if result.get("success", False):
                print(f"   Streaming: {result.get('chunks_received', 0)} chunks received")
            elif result["status_code"] == 405:
                print("   Method not allowed (endpoint may not support streaming)")
        except Exception as e:
            print(f"❌ POST /ask/stream - ERROR: {e}")
        
        # 5. DOCUMENT ENDPOINTS (with auth)
        print("\n📄 DOCUMENT ENDPOINTS")
        print("-" * 40)
        
        if auth_success:
            headers = {"Authorization": f"Bearer {self.access_token}"}
            
            # List documents
            try:
                response = self.session.get(f"{BASE_URL}/documents/list", headers=headers)
                success = response.status_code == 200
                results["documents"].append({
                    "endpoint": "GET /documents/list",
                    "status": response.status_code,
                    "success": success
                })
                status = "✅" if success else "❌"
                print(f"{status} 🔒 GET /documents/list - {response.status_code}")
                if success:
                    docs = response.json()
                    print(f"   Found {len(docs.get('documents', []))} documents")
            except Exception as e:
                print(f"❌ 🔒 GET /documents/list - ERROR: {e}")
            
            # Upload document
            try:
                files = {
                    'file': ('test_philosophy.txt', 
                           'This is a test document about Aristotelian virtue ethics.\n\nVirtue ethics focuses on character rather than actions.',
                           'text/plain')
                }
                data = {
                    'title': 'Test Philosophy Document',
                    'author': 'Test Author'
                }
                response = self.session.post(f"{BASE_URL}/documents/upload", 
                                           files=files, data=data, headers=headers)
                success = response.status_code in [200, 201]
                results["documents"].append({
                    "endpoint": "POST /documents/upload",
                    "status": response.status_code,
                    "success": success
                })
                status = "✅" if success else "❌"
                print(f"{status} 🔒 POST /documents/upload - {response.status_code}")
                if success:
                    upload_result = response.json()
                    print(f"   Uploaded file ID: {upload_result.get('file_id', 'N/A')}")
            except Exception as e:
                print(f"❌ 🔒 POST /documents/upload - ERROR: {e}")
        
        # 6. CHAT ENDPOINTS
        print("\n💬 CHAT ENDPOINTS")
        print("-" * 40)
        
        # Send chat message
        try:
            chat_data = {
                "role": "user",
                "content": "Hello! I'd like to learn about Aristotelian virtue ethics.",
                "session_id": self.test_session_id
            }
            response = self.session.post(f"{BASE_URL}/chat/message", json=chat_data)
            success = response.status_code in [200, 201]
            results["chat"].append({
                "endpoint": "POST /chat/message",
                "status": response.status_code,
                "success": success
            })
            status = "✅" if success else "❌"
            print(f"{status} POST /chat/message - {response.status_code}")
            if success:
                msg_result = response.json()
                print(f"   Message ID: {msg_result.get('message_id', 'N/A')}")
        except Exception as e:
            print(f"❌ POST /chat/message - ERROR: {e}")
        
        # Get chat history
        try:
            response = self.session.get(f"{BASE_URL}/chat/history/{self.test_session_id}")
            success = response.status_code == 200
            results["chat"].append({
                "endpoint": "GET /chat/history/{session_id}",
                "status": response.status_code,
                "success": success
            })
            status = "✅" if success else "❌"
            print(f"{status} GET /chat/history/{{session_id}} - {response.status_code}")
        except Exception as e:
            print(f"❌ GET /chat/history/{{session_id}} - ERROR: {e}")
        
        # 7. WORKFLOW ENDPOINTS
        print("\n⚙️ WORKFLOW ENDPOINTS")
        print("-" * 40)
        
        # List workflows
        try:
            response = self.session.get(f"{BASE_URL}/workflows/")
            success = response.status_code == 200
            results["workflows"].append({
                "endpoint": "GET /workflows/",
                "status": response.status_code,
                "success": success
            })
            status = "✅" if success else "❌"
            print(f"{status} GET /workflows/ - {response.status_code}")
            if success:
                workflows = response.json()
                print(f"   Found {len(workflows.get('drafts', []))} workflow drafts")
        except Exception as e:
            print(f"❌ GET /workflows/ - ERROR: {e}")
        
        # Create workflow
        try:
            workflow_data = {
                "title": "Virtue Ethics in Modern Context",
                "topic": "Exploring how Aristotelian virtue ethics applies to contemporary moral dilemmas",
                "philosopher": "Aristotle"
            }
            response = self.session.post(f"{BASE_URL}/workflows/create", json=workflow_data)
            success = response.status_code in [200, 201]
            results["workflows"].append({
                "endpoint": "POST /workflows/create",
                "status": response.status_code,
                "success": success
            })
            status = "✅" if success else "❌"
            print(f"{status} POST /workflows/create - {response.status_code}")
            if success:
                workflow_result = response.json()
                print(f"   Created workflow ID: {workflow_result.get('draft_id', 'N/A')}")
        except Exception as e:
            print(f"❌ POST /workflows/create - ERROR: {e}")
        
        # 8. USER ENDPOINTS
        print("\n👤 USER ENDPOINTS")
        print("-" * 40)
        
        if auth_success:
            try:
                headers = {"Authorization": f"Bearer {self.access_token}"}
                response = self.session.get(f"{BASE_URL}/users/me", headers=headers)
                success = response.status_code == 200
                results["users"].append({
                    "endpoint": "GET /users/me",
                    "status": response.status_code,
                    "success": success
                })
                status = "✅" if success else "❌"
                print(f"{status} 🔒 GET /users/me - {response.status_code}")
                if success:
                    user_data = response.json()
                    print(f"   User: {user_data.get('username')} ({user_data.get('email')})")
                    print(f"   Tier: {user_data.get('subscription_tier')}")
            except Exception as e:
                print(f"❌ 🔒 GET /users/me - ERROR: {e}")
        
        # GENERATE FINAL REPORT
        self.generate_final_report(results)
    
    def generate_final_report(self, results: Dict):
        """Generate final comprehensive report"""
        print("\n" + "=" * 80)
        print("🎯 FINAL PERFECT TEST RESULTS")
        print("=" * 80)
        
        total_tests = 0
        successful_tests = 0
        
        for category, tests in results.items():
            category_success = sum(1 for test in tests if test["success"])
            category_total = len(tests)
            total_tests += category_total
            successful_tests += category_success
            
            if category_total > 0:
                success_rate = (category_success / category_total) * 100
                print(f"\n📊 {category.upper()}: {category_success}/{category_total} ({success_rate:.1f}%)")
                
                for test in tests:
                    status = "✅" if test["success"] else "❌"
                    print(f"   {status} {test['endpoint']} - {test['status']}")
        
        overall_success_rate = (successful_tests / total_tests) * 100 if total_tests > 0 else 0
        
        print(f"\n🏆 OVERALL RESULTS")
        print(f"   Total Tests: {total_tests}")
        print(f"   Successful: {successful_tests}")
        print(f"   Failed: {total_tests - successful_tests}")
        print(f"   Success Rate: {overall_success_rate:.1f}%")
        
        # Streaming results
        streaming_tests = results.get("streaming", [])
        streaming_success = sum(1 for test in streaming_tests if test["success"])
        
        print(f"\n🌊 STREAMING ENDPOINTS")
        print(f"   Streaming Tests: {len(streaming_tests)}")
        print(f"   Streaming Success: {streaming_success}")
        
        if streaming_success > 0:
            print("   ✅ Streaming endpoints are working!")
        else:
            print("   ❌ Streaming endpoints need investigation")
        
        # Final assessment
        if overall_success_rate >= 90:
            print(f"\n🟢 EXCELLENT: {overall_success_rate:.1f}% success rate")
        elif overall_success_rate >= 75:
            print(f"\n🟡 GOOD: {overall_success_rate:.1f}% success rate")
        else:
            print(f"\n🔴 NEEDS WORK: {overall_success_rate:.1f}% success rate")
        
        print("\n🎉 Perfect endpoint testing complete!")

if __name__ == "__main__":
    tester = PerfectEndpointTester()
    tester.run_perfect_tests()