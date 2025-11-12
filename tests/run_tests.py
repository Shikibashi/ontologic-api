#!/usr/bin/env python3
"""
Main test runner for Ontologic API
Provides easy access to run different types of tests
"""

import sys
import subprocess
import argparse
from pathlib import Path

def run_integration_tests():
    """Run integration tests"""
    print("🧪 Running Integration Tests...")
    print("=" * 50)
    
    # Run the final achievement test (most comprehensive)
    try:
        result = subprocess.run([
            sys.executable, 
            "tests/integration/FINAL_100_PERCENT_ACHIEVEMENT.py"
        ], capture_output=True, text=True)
        
        print(result.stdout)
        if result.stderr:
            print("Errors:", result.stderr)
            
        return result.returncode == 0
    except Exception as e:
        print(f"Error running integration tests: {e}")
        return False

def run_auth_tests():
    """Run authentication tests"""
    print("🔐 Running Authentication Tests...")
    print("=" * 50)
    
    try:
        result = subprocess.run([
            sys.executable, 
            "tests/integration/test_auth_endpoints.py"
        ], capture_output=True, text=True)
        
        print(result.stdout)
        if result.stderr:
            print("Errors:", result.stderr)
            
        return result.returncode == 0
    except Exception as e:
        print(f"Error running auth tests: {e}")
        return False

def run_comprehensive_tests():
    """Run comprehensive endpoint tests"""
    print("📊 Running Comprehensive Tests...")
    print("=" * 50)
    
    try:
        result = subprocess.run([
            sys.executable, 
            "tests/integration/comprehensive_endpoint_test.py"
        ], capture_output=True, text=True)
        
        print(result.stdout)
        if result.stderr:
            print("Errors:", result.stderr)
            
        return result.returncode == 0
    except Exception as e:
        print(f"Error running comprehensive tests: {e}")
        return False

def run_all_tests():
    """Run all available tests"""
    print("🚀 Running All Tests...")
    print("=" * 50)
    
    results = []
    
    # Run integration tests
    results.append(("Integration", run_integration_tests()))
    
    # Run auth tests
    results.append(("Authentication", run_auth_tests()))
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)
    
    for test_type, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_type}: {status}")
    
    all_passed = all(result[1] for result in results)
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED!")
    else:
        print("\n⚠️ Some tests failed - check output above")
    
    return all_passed

def main():
    """Main test runner"""
    parser = argparse.ArgumentParser(description="Ontologic API Test Runner")
    parser.add_argument(
        "test_type", 
        choices=["all", "integration", "auth", "comprehensive"],
        help="Type of tests to run"
    )
    
    args = parser.parse_args()
    
    print("🎯 ONTOLOGIC API TEST RUNNER")
    print("=" * 60)
    
    if args.test_type == "all":
        success = run_all_tests()
    elif args.test_type == "integration":
        success = run_integration_tests()
    elif args.test_type == "auth":
        success = run_auth_tests()
    elif args.test_type == "comprehensive":
        success = run_comprehensive_tests()
    
    if success:
        print("\n✅ Tests completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()