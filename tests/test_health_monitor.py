#!/usr/bin/env python3
"""
Test Health Monitoring Script

This script provides automated monitoring and reporting for the ontologic-api test suite.
It tracks test success rates, identifies regressions, and provides actionable insights.

Usage:
    python tests/test_health_monitor.py [--category CATEGORY] [--report]
"""

import subprocess
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import argparse


class TestHealthMonitor:
    """Monitor and report on test suite health."""
    
    def __init__(self):
        self.test_categories = {
            'philosophy_prompts': 'tests/test_ask_philosophy_prompts.py',
            'api_endpoints': 'tests/test_ask_and_query_endpoints.py',
            'authentication': 'tests/test_auth_router.py',
            'chat_models': 'tests/test_chat_models.py',
            'collection_normalization': 'tests/test_collection_normalization.py',
            'expansion_service': 'tests/test_expansion_service.py',
            'health_router': 'tests/test_health_router.py',
            'payment_system': 'tests/test_payment_*.py',
            'chat_integration': 'tests/test_chat_*.py',
            'document_endpoints': 'tests/test_document_endpoints.py',
            'e2e_tests': 'tests/test_e2e_*.py'
        }
        
        self.critical_categories = [
            'philosophy_prompts',
            'api_endpoints', 
            'authentication',
            'chat_models',
            'collection_normalization'
        ]
        
        self.baseline_metrics = {
            'total_tests': 675,
            'expected_passing': 467,
            'critical_success_rate': 100.0,
            'overall_success_rate': 69.2
        }

    def run_tests(self, test_path: str, timeout: int = 60) -> Dict:
        """Run tests and return results."""
        cmd = ['uv', 'run', 'python', '-m', 'pytest', test_path, '--tb=no', '-q']
        
        start_time = time.time()
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=timeout
            )
            execution_time = time.time() - start_time
            
            # Parse pytest output
            output_lines = result.stdout.strip().split('\n')
            summary_line = output_lines[-1] if output_lines else ""
            
            # Extract test counts from summary
            passed = failed = skipped = errors = 0
            if '=' in summary_line and ('passed' in summary_line or 'failed' in summary_line):
                parts = summary_line.split()
                for i, part in enumerate(parts):
                    if part.isdigit():
                        if i + 1 < len(parts):
                            if 'passed' in parts[i + 1]:
                                passed = int(part)
                            elif 'failed' in parts[i + 1]:
                                failed = int(part)
                            elif 'skipped' in parts[i + 1]:
                                skipped = int(part)
                            elif 'error' in parts[i + 1]:
                                errors = int(part)
            
            total = passed + failed + skipped + errors
            success_rate = (passed / total * 100) if total > 0 else 0
            
            return {
                'passed': passed,
                'failed': failed,
                'skipped': skipped,
                'errors': errors,
                'total': total,
                'success_rate': success_rate,
                'execution_time': execution_time,
                'exit_code': result.returncode,
                'output': result.stdout,
                'stderr': result.stderr
            }
            
        except subprocess.TimeoutExpired:
            return {
                'passed': 0,
                'failed': 0,
                'skipped': 0,
                'errors': 0,
                'total': 0,
                'success_rate': 0,
                'execution_time': timeout,
                'exit_code': -1,
                'output': '',
                'stderr': 'Test execution timed out'
            }
        except Exception as e:
            return {
                'passed': 0,
                'failed': 0,
                'skipped': 0,
                'errors': 0,
                'total': 0,
                'success_rate': 0,
                'execution_time': 0,
                'exit_code': -1,
                'output': '',
                'stderr': str(e)
            }

    def check_category_health(self, category: str) -> Dict:
        """Check health of a specific test category."""
        if category not in self.test_categories:
            raise ValueError(f"Unknown category: {category}")
        
        test_path = self.test_categories[category]
        results = self.run_tests(test_path)
        
        # Determine health status
        if category in self.critical_categories:
            if results['success_rate'] < 95:
                status = 'CRITICAL'
            elif results['success_rate'] < 100:
                status = 'WARNING'
            else:
                status = 'HEALTHY'
        else:
            if results['success_rate'] < 50:
                status = 'CRITICAL'
            elif results['success_rate'] < 75:
                status = 'WARNING'
            else:
                status = 'HEALTHY'
        
        results['category'] = category
        results['status'] = status
        results['is_critical'] = category in self.critical_categories
        results['timestamp'] = datetime.now(timezone.utc).isoformat()
        
        return results

    def check_full_suite_health(self) -> Dict:
        """Check health of the entire test suite."""
        results = self.run_tests('tests/', timeout=120)
        
        # Determine overall health
        if results['success_rate'] < 60:
            status = 'CRITICAL'
        elif results['success_rate'] < 70:
            status = 'WARNING'
        else:
            status = 'HEALTHY'
        
        results['status'] = status
        results['timestamp'] = datetime.now(timezone.utc).isoformat()
        results['baseline_comparison'] = {
            'expected_passing': self.baseline_metrics['expected_passing'],
            'actual_passing': results['passed'],
            'difference': results['passed'] - self.baseline_metrics['expected_passing'],
            'expected_success_rate': self.baseline_metrics['overall_success_rate'],
            'actual_success_rate': results['success_rate'],
            'rate_difference': results['success_rate'] - self.baseline_metrics['overall_success_rate']
        }
        
        return results

    def generate_health_report(self) -> Dict:
        """Generate comprehensive health report."""
        report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'full_suite': self.check_full_suite_health(),
            'categories': {},
            'summary': {
                'critical_issues': [],
                'warnings': [],
                'healthy_categories': [],
                'recommendations': []
            }
        }
        
        # Check each category
        for category in self.test_categories:
            try:
                category_results = self.check_category_health(category)
                report['categories'][category] = category_results
                
                if category_results['status'] == 'CRITICAL':
                    report['summary']['critical_issues'].append({
                        'category': category,
                        'success_rate': category_results['success_rate'],
                        'failed_tests': category_results['failed'],
                        'is_critical_category': category_results['is_critical']
                    })
                elif category_results['status'] == 'WARNING':
                    report['summary']['warnings'].append({
                        'category': category,
                        'success_rate': category_results['success_rate'],
                        'failed_tests': category_results['failed']
                    })
                else:
                    report['summary']['healthy_categories'].append(category)
                    
            except Exception as e:
                report['categories'][category] = {
                    'error': str(e),
                    'status': 'ERROR',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
        
        # Generate recommendations
        if report['summary']['critical_issues']:
            report['summary']['recommendations'].append(
                "URGENT: Address critical issues in failing test categories"
            )
        
        if report['full_suite']['success_rate'] < self.baseline_metrics['overall_success_rate']:
            report['summary']['recommendations'].append(
                "Test suite has regressed below baseline. Investigate recent changes."
            )
        
        if len(report['summary']['healthy_categories']) == len(self.critical_categories):
            report['summary']['recommendations'].append(
                "All critical categories healthy. Focus on improving non-critical categories."
            )
        
        return report

    def print_summary_report(self, report: Dict):
        """Print a human-readable summary report."""
        print("=" * 60)
        print("TEST SUITE HEALTH REPORT")
        print("=" * 60)
        print(f"Generated: {report['timestamp']}")
        print()
        
        # Full suite summary
        full_suite = report['full_suite']
        print(f"OVERALL STATUS: {full_suite['status']}")
        print(f"Success Rate: {full_suite['success_rate']:.1f}%")
        print(f"Tests: {full_suite['passed']} passed, {full_suite['failed']} failed, {full_suite['errors']} errors")
        print(f"Execution Time: {full_suite['execution_time']:.1f}s")
        
        if 'baseline_comparison' in full_suite:
            baseline = full_suite['baseline_comparison']
            print(f"Baseline Comparison: {baseline['difference']:+d} tests, {baseline['rate_difference']:+.1f}%")
        print()
        
        # Category summary
        print("CATEGORY STATUS:")
        print("-" * 40)
        
        for category, results in report['categories'].items():
            if 'error' in results:
                print(f"{category:20} ERROR: {results['error']}")
            else:
                status_icon = {
                    'HEALTHY': '✅',
                    'WARNING': '⚠️',
                    'CRITICAL': '❌'
                }.get(results['status'], '❓')
                
                critical_marker = " (CRITICAL)" if results.get('is_critical') else ""
                print(f"{category:20} {status_icon} {results['status']} - {results['success_rate']:.1f}%{critical_marker}")
        
        print()
        
        # Issues and recommendations
        if report['summary']['critical_issues']:
            print("CRITICAL ISSUES:")
            for issue in report['summary']['critical_issues']:
                critical_note = " [CRITICAL CATEGORY]" if issue['is_critical_category'] else ""
                print(f"  ❌ {issue['category']}: {issue['success_rate']:.1f}% success rate{critical_note}")
            print()
        
        if report['summary']['warnings']:
            print("WARNINGS:")
            for warning in report['summary']['warnings']:
                print(f"  ⚠️  {warning['category']}: {warning['success_rate']:.1f}% success rate")
            print()
        
        if report['summary']['recommendations']:
            print("RECOMMENDATIONS:")
            for rec in report['summary']['recommendations']:
                print(f"  💡 {rec}")
            print()
        
        print(f"Healthy Categories: {len(report['summary']['healthy_categories'])}/{len(self.test_categories)}")
        print("=" * 60)

    def save_report(self, report: Dict, filename: Optional[str] = None):
        """Save report to JSON file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"test_health_report_{timestamp}.json"
        
        report_path = Path("tests") / filename
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"Report saved to: {report_path}")


def main():
    parser = argparse.ArgumentParser(description='Monitor test suite health')
    parser.add_argument('--category', help='Check specific category only')
    parser.add_argument('--report', action='store_true', help='Generate full health report')
    parser.add_argument('--save', help='Save report to file')
    parser.add_argument('--quick', action='store_true', help='Quick check of critical categories only')
    
    args = parser.parse_args()
    
    monitor = TestHealthMonitor()
    
    if args.category:
        # Check specific category
        try:
            results = monitor.check_category_health(args.category)
            print(f"Category: {results['category']}")
            print(f"Status: {results['status']}")
            print(f"Success Rate: {results['success_rate']:.1f}%")
            print(f"Tests: {results['passed']} passed, {results['failed']} failed")
            print(f"Execution Time: {results['execution_time']:.1f}s")
        except ValueError as e:
            print(f"Error: {e}")
            print(f"Available categories: {', '.join(monitor.test_categories.keys())}")
    
    elif args.quick:
        # Quick check of critical categories
        print("QUICK HEALTH CHECK - Critical Categories")
        print("-" * 40)
        all_healthy = True
        
        for category in monitor.critical_categories:
            results = monitor.check_category_health(category)
            status_icon = {
                'HEALTHY': '✅',
                'WARNING': '⚠️',
                'CRITICAL': '❌'
            }.get(results['status'], '❓')
            
            print(f"{category:20} {status_icon} {results['success_rate']:.1f}%")
            
            if results['status'] != 'HEALTHY':
                all_healthy = False
        
        print("-" * 40)
        if all_healthy:
            print("✅ All critical categories healthy!")
        else:
            print("⚠️  Some critical categories need attention")
    
    elif args.report:
        # Generate full report
        report = monitor.generate_health_report()
        monitor.print_summary_report(report)
        
        if args.save:
            monitor.save_report(report, args.save)
    
    else:
        # Default: quick suite check
        results = monitor.check_full_suite_health()
        print(f"Test Suite Status: {results['status']}")
        print(f"Success Rate: {results['success_rate']:.1f}%")
        print(f"Tests: {results['passed']} passed, {results['failed']} failed, {results['errors']} errors")
        print(f"Execution Time: {results['execution_time']:.1f}s")
        
        if 'baseline_comparison' in results:
            baseline = results['baseline_comparison']
            if baseline['difference'] != 0:
                print(f"Baseline Change: {baseline['difference']:+d} tests ({baseline['rate_difference']:+.1f}%)")


if __name__ == '__main__':
    main()