"""
Test utilities for dynamic philosopher selection.

This module provides utilities to help tests dynamically select appropriate philosophers
based on test categories, requirements, and scenarios.
"""

from typing import Dict, List, Optional, Any
from .philosopher_test_mapper import philosopher_mapper


def select_test_philosopher(prompt_data: Dict[str, Any], 
                          test_variant: Optional[Dict[str, Any]] = None) -> str:
    """
    Select the most appropriate philosopher for a test based on prompt data.
    
    Args:
        prompt_data: The prompt data from test catalog
        test_variant: Optional test variant configuration
        
    Returns:
        The philosopher name to use for the test
    """
    return philosopher_mapper.select_philosopher_for_test_scenario(prompt_data, test_variant)


def get_philosophers_for_category(category: str) -> List[str]:
    """
    Get all philosophers that are appropriate for a given category.
    
    Args:
        category: The philosophical category
        
    Returns:
        List of philosopher names suitable for the category
    """
    return philosopher_mapper.suggest_alternative_philosophers(category)


def validate_test_philosopher(philosopher_name: str) -> bool:
    """
    Validate that a philosopher name is available in the system.
    
    Args:
        philosopher_name: The philosopher name to validate
        
    Returns:
        True if the philosopher is available, False otherwise
    """
    return philosopher_mapper.validate_philosopher_availability(philosopher_name)


def normalize_test_collection(collection_name: str) -> str:
    """
    Normalize a collection name to a valid philosopher name.
    
    Args:
        collection_name: The collection name from test data
        
    Returns:
        The normalized philosopher name
    """
    return philosopher_mapper.normalize_philosopher_name(collection_name)


def create_test_collection_mapping() -> Dict[str, str]:
    """
    Create a mapping of test collection names to system philosopher names.
    
    Returns:
        Dictionary mapping test names to system names
    """
    return philosopher_mapper.test_to_system_mapping.copy()


def get_fallback_philosopher(preferred: str) -> str:
    """
    Get a fallback philosopher if the preferred one is not available.
    
    Args:
        preferred: The preferred philosopher name
        
    Returns:
        A valid philosopher name (preferred or fallback)
    """
    return philosopher_mapper.get_fallback_philosopher(preferred)


def update_test_data_with_philosophers(test_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update test data to use valid philosopher names.
    
    Args:
        test_data: Test data that may contain philosopher references
        
    Returns:
        Updated test data with normalized philosopher names
    """
    return philosopher_mapper.update_test_data_philosophers(test_data)


class TestPhilosopherSelector:
    """Helper class for selecting philosophers in test scenarios."""
    
    def __init__(self):
        self.mapper = philosopher_mapper
    
    def for_ethics_test(self) -> str:
        """Get philosopher for ethics-related tests."""
        return self.mapper.get_philosopher_for_category("ethics")
    
    def for_political_test(self) -> str:
        """Get philosopher for political philosophy tests."""
        return self.mapper.get_philosopher_for_category("political_philosophy")
    
    def for_epistemology_test(self) -> str:
        """Get philosopher for epistemology tests."""
        return self.mapper.get_philosopher_for_category("epistemology")
    
    def for_metaphysics_test(self) -> str:
        """Get philosopher for metaphysics tests."""
        return self.mapper.get_philosopher_for_category("metaphysics")
    
    def for_logic_test(self) -> str:
        """Get philosopher for logic and reasoning tests."""
        return self.mapper.get_philosopher_for_category("logic_reasoning")
    
    def for_aesthetics_test(self) -> str:
        """Get philosopher for aesthetics tests."""
        return self.mapper.get_philosopher_for_category("aesthetics")
    
    def for_immersive_test(self, philosopher_name: Optional[str] = None) -> str:
        """Get philosopher for immersive mode tests."""
        if philosopher_name:
            return self.mapper.normalize_philosopher_name(philosopher_name)
        return self.mapper.default_philosopher
    
    def for_category(self, category: str) -> str:
        """Get philosopher for any category."""
        return self.mapper.get_philosopher_for_category(category)


# Global selector instance
test_philosopher_selector = TestPhilosopherSelector()