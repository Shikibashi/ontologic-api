#!/usr/bin/env python3
"""
Script to check which endpoints are currently exposed in the ontologic-api.
Uses uv run to ensure proper environment.
"""

import sys
sys.path.append('app')

def main():
    try:
        from app.router import router
        from fastapi.routing import APIRoute
        from app.config import get_chat_history_enabled, get_oauth_enabled
        
        print("=== Ontologic API Endpoint Analysis ===\n")
        
        # Show configuration status
        print("Configuration Status:")
        print(f"  Chat History Enabled: {get_chat_history_enabled()}")
        print(f"  OAuth Enabled: {get_oauth_enabled()}")
        print()
        
        def extract_routes(router_obj, prefix=""):
            """Extract all routes from router recursively."""
            routes = []
            
            for route in router_obj.routes:
                if isinstance(route, APIRoute):
                    path = prefix + route.path
                    methods = list(route.methods - {'HEAD', 'OPTIONS'})  # Remove HTTP methods we don't care about
                    if methods:  # Only include if there are actual methods
                        routes.append({
                            'path': path,
                            'methods': methods,
                            'name': route.name,
                            'tags': getattr(route, 'tags', [])
                        })
                elif hasattr(route, 'routes'):  # Sub-router
                    sub_prefix = prefix + getattr(route, 'prefix', '')
                    routes.extend(extract_routes(route, sub_prefix))
            
            return routes
        
        # Get all routes
        all_routes = extract_routes(router)
        
        # Group by category/tags
        categories = {}
        for route in all_routes:
            tags = route['tags'] if route['tags'] else ['uncategorized']
            for tag in tags:
                if tag not in categories:
                    categories[tag] = []
                categories[tag].append(route)
        
        # Print organized by category
        total_endpoints = 0
        for category, category_routes in sorted(categories.items()):
            print(f"## {category.upper()}")
            
            # Sort routes by path for better readability
            sorted_routes = sorted(category_routes, key=lambda x: x['path'])
            
            for route in sorted_routes:
                methods_str = ', '.join(sorted(route['methods']))
                print(f"  {methods_str:15} {route['path']}")
                total_endpoints += len(route['methods'])
            print()
        
        print(f"Total unique endpoints: {len(all_routes)}")
        print(f"Total method-endpoint combinations: {total_endpoints}")
        
        # Check for expected chat endpoints
        chat_endpoints = [r for r in all_routes if r['path'].startswith('/chat')]
        auth_endpoints = [r for r in all_routes if r['path'].startswith('/auth')]
        
        print(f"\nChat endpoints found: {len(chat_endpoints)}")
        print(f"Auth endpoints found: {len(auth_endpoints)}")
        
        if get_chat_history_enabled() and len(chat_endpoints) == 0:
            print("⚠️  WARNING: Chat history is enabled but no /chat endpoints found!")
        
        if len(auth_endpoints) == 0:
            print("⚠️  WARNING: No /auth endpoints found!")
        
        # Show some key endpoints that should be available
        key_endpoints = [
            '/health',
            '/ask',
            '/documents/upload',
            '/chat/config/status',
            '/auth/providers'
        ]
        
        print("\nKey Endpoint Status:")
        for endpoint in key_endpoints:
            found = any(r['path'] == endpoint for r in all_routes)
            status = "✅" if found else "❌"
            print(f"  {status} {endpoint}")
        
    except Exception as e:
        print(f"❌ Error analyzing endpoints: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()