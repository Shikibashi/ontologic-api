#!/usr/bin/env python3
"""
Script to check which endpoints are currently exposed in the ontologic-api.
"""

import sys
sys.path.append('app')

from app.router import router
from fastapi.routing import APIRoute

def get_all_routes():
    """Extract all routes from the main router."""
    routes = []
    
    def extract_routes(router_obj, prefix=""):
        for route in router_obj.routes:
            if isinstance(route, APIRoute):
                path = prefix + route.path
                methods = list(route.methods)
                routes.append({
                    'path': path,
                    'methods': methods,
                    'name': route.name,
                    'tags': getattr(route, 'tags', [])
                })
            elif hasattr(route, 'routes'):  # Sub-router
                sub_prefix = prefix + getattr(route, 'prefix', '')
                extract_routes(route, sub_prefix)
    
    extract_routes(router)
    return routes

def main():
    print("=== Currently Exposed API Endpoints ===\n")
    
    routes = get_all_routes()
    
    # Group by tags/category
    categories = {}
    for route in routes:
        tags = route['tags'] if route['tags'] else ['uncategorized']
        for tag in tags:
            if tag not in categories:
                categories[tag] = []
            categories[tag].append(route)
    
    # Print organized by category
    for category, category_routes in sorted(categories.items()):
        print(f"## {category.upper()}")
        for route in sorted(category_routes, key=lambda x: x['path']):
            methods_str = ', '.join(sorted(route['methods']))
            print(f"  {methods_str:12} {route['path']}")
        print()
    
    print(f"Total endpoints: {len(routes)}")

if __name__ == "__main__":
    main()