"""
Script to update test data files with correct philosopher names.

This script updates the prompt catalog and canned responses to use valid philosopher names
that match the system configuration.
"""

import json
from pathlib import Path
from typing import Dict, Any
from philosopher_test_mapper import philosopher_mapper


def update_prompt_catalog():
    """Update the prompt catalog with correct philosopher names."""
    catalog_path = Path("fixtures/prompt_catalog.json")
    
    if not catalog_path.exists():
        print(f"Prompt catalog not found at {catalog_path}")
        return
    
    with open(catalog_path, 'r') as f:
        catalog = json.load(f)
    
    updated_count = 0
    
    # Update prompts
    if "prompts" in catalog:
        for prompt in catalog["prompts"]:
            original_prompt = prompt.copy()
            
            # Update requires_philosopher field
            if "requires_philosopher" in prompt and prompt["requires_philosopher"]:
                old_philosopher = prompt["requires_philosopher"]
                new_philosopher = philosopher_mapper.normalize_philosopher_name(old_philosopher)
                if old_philosopher != new_philosopher:
                    prompt["requires_philosopher"] = new_philosopher
                    print(f"Updated prompt {prompt['id']}: requires_philosopher '{old_philosopher}' -> '{new_philosopher}'")
                    updated_count += 1
            
            # Update test variants
            if "test_variants" in prompt:
                for variant in prompt["test_variants"]:
                    if "payload" in variant and isinstance(variant["payload"], dict):
                        if "persona" in variant["payload"]:
                            old_persona = variant["payload"]["persona"]
                            new_persona = philosopher_mapper.normalize_philosopher_name(old_persona)
                            if old_persona != new_persona:
                                variant["payload"]["persona"] = new_persona
                                print(f"Updated prompt {prompt['id']}: persona '{old_persona}' -> '{new_persona}'")
                                updated_count += 1
    
    # Save updated catalog
    if updated_count > 0:
        with open(catalog_path, 'w') as f:
            json.dump(catalog, f, indent=2)
        print(f"Updated prompt catalog with {updated_count} changes")
    else:
        print("No updates needed for prompt catalog")


def update_canned_responses():
    """Update canned responses with correct philosopher names."""
    responses_path = Path("fixtures/canned_responses.json")
    
    if not responses_path.exists():
        print(f"Canned responses not found at {responses_path}")
        return
    
    with open(responses_path, 'r') as f:
        responses = json.load(f)
    
    updated_count = 0
    
    # Update each response
    for prompt_id, response_data in responses.items():
        if "input" in response_data and isinstance(response_data["input"], dict):
            input_data = response_data["input"]
            
            # Update collection field
            if "collection" in input_data:
                old_collection = input_data["collection"]
                new_collection = philosopher_mapper.normalize_philosopher_name(old_collection)
                if old_collection != new_collection:
                    input_data["collection"] = new_collection
                    print(f"Updated {prompt_id}: collection '{old_collection}' -> '{new_collection}'")
                    updated_count += 1
            
            # Update philosopher field if present
            if "philosopher" in input_data:
                old_philosopher = input_data["philosopher"]
                new_philosopher = philosopher_mapper.normalize_philosopher_name(old_philosopher)
                if old_philosopher != new_philosopher:
                    input_data["philosopher"] = new_philosopher
                    print(f"Updated {prompt_id}: philosopher '{old_philosopher}' -> '{new_philosopher}'")
                    updated_count += 1
    
    # Save updated responses
    if updated_count > 0:
        with open(responses_path, 'w') as f:
            json.dump(responses, f, indent=2)
        print(f"Updated canned responses with {updated_count} changes")
    else:
        print("No updates needed for canned responses")


def validate_test_data():
    """Validate that all philosopher names in test data are valid."""
    print("\nValidating test data...")
    
    # Check prompt catalog
    catalog_path = Path("fixtures/prompt_catalog.json")
    if catalog_path.exists():
        with open(catalog_path, 'r') as f:
            catalog = json.load(f)
        
        invalid_philosophers = []
        
        if "prompts" in catalog:
            for prompt in catalog["prompts"]:
                if "requires_philosopher" in prompt and prompt["requires_philosopher"]:
                    philosopher = prompt["requires_philosopher"]
                    if not philosopher_mapper.validate_philosopher_availability(philosopher):
                        invalid_philosophers.append(f"Prompt {prompt['id']}: requires_philosopher '{philosopher}'")
                
                if "test_variants" in prompt:
                    for variant in prompt["test_variants"]:
                        if "payload" in variant and isinstance(variant["payload"], dict):
                            if "persona" in variant["payload"]:
                                persona = variant["payload"]["persona"]
                                if not philosopher_mapper.validate_philosopher_availability(persona):
                                    invalid_philosophers.append(f"Prompt {prompt['id']}: persona '{persona}'")
        
        if invalid_philosophers:
            print("Invalid philosophers found in prompt catalog:")
            for invalid in invalid_philosophers:
                print(f"  - {invalid}")
        else:
            print("✓ All philosophers in prompt catalog are valid")
    
    # Check canned responses
    responses_path = Path("fixtures/canned_responses.json")
    if responses_path.exists():
        with open(responses_path, 'r') as f:
            responses = json.load(f)
        
        invalid_collections = []
        
        for prompt_id, response_data in responses.items():
            if "input" in response_data and isinstance(response_data["input"], dict):
                input_data = response_data["input"]
                
                if "collection" in input_data:
                    collection = input_data["collection"]
                    if not philosopher_mapper.validate_philosopher_availability(collection):
                        invalid_collections.append(f"{prompt_id}: collection '{collection}'")
                
                if "philosopher" in input_data:
                    philosopher = input_data["philosopher"]
                    if not philosopher_mapper.validate_philosopher_availability(philosopher):
                        invalid_collections.append(f"{prompt_id}: philosopher '{philosopher}'")
        
        if invalid_collections:
            print("Invalid collections/philosophers found in canned responses:")
            for invalid in invalid_collections:
                print(f"  - {invalid}")
        else:
            print("✓ All collections/philosophers in canned responses are valid")


if __name__ == "__main__":
    print("Updating test data files with correct philosopher names...")
    print("=" * 60)
    
    # Change to tests directory
    import os
    os.chdir(Path(__file__).parent.parent)
    
    update_prompt_catalog()
    print()
    update_canned_responses()
    
    validate_test_data()
    
    print("\nTest data update complete!")