"""
Philosopher name mapping and validation for test suite.

This module provides mapping between test philosopher names and system philosopher names,
ensuring tests use valid philosopher references that match the actual system configuration.
"""

from typing import Dict, List, Optional, Set
from app.core.philosopher_loader import PhilosopherLoader


class PhilosopherTestMapper:
    """Maps test philosopher names to system philosopher names and provides validation."""
    
    def __init__(self):
        self.philosopher_loader = PhilosopherLoader()
        
        # Available philosophers from the system
        self.system_philosophers = set(self.philosopher_loader.available_philosophers)
        
        # Mapping from test names to system names
        self.test_to_system_mapping = {
            # Direct matches (already correct)
            "Aristotle": "Aristotle",
            "Immanuel Kant": "Immanuel Kant", 
            "David Hume": "David Hume",
            "John Locke": "John Locke",
            "Friedrich Nietzsche": "Friedrich Nietzsche",
            
            # Case variations
            "aristotle": "Aristotle",
            "kant": "Immanuel Kant",
            "hume": "David Hume", 
            "locke": "John Locke",
            "nietzsche": "Friedrich Nietzsche",
            
            # Common test names that need mapping
            "Ethics Core": "Aristotle",  # Virtue ethics focus
            "Business Ethics": "Aristotle",  # Practical ethics
            "Global Ethics": "Immanuel Kant",  # Categorical imperative
            "Bioethics": "Immanuel Kant",  # Duty-based ethics
            "Civic Ethics": "John Locke",  # Social contract theory
            "Political Philosophy": "John Locke",  # Government theory
            "Philosopher Profiles": "Aristotle",  # Default for profiles
            "Meta Collection": "Meta Collection",  # Special collection, no mapping needed
            
            # Category-based mappings for generic test categories
            "ancient_philosophy": "Aristotle",
            "modern_philosophy": "Immanuel Kant", 
            "empiricism": "David Hume",
            "rationalism": "Immanuel Kant",
            "existentialism": "Friedrich Nietzsche",
            "political_theory": "John Locke",
            "epistemology": "David Hume",
            "metaphysics": "Aristotle",
            "ethics": "Aristotle",
            "virtue_ethics": "Aristotle",
            "deontology": "Immanuel Kant",
            "utilitarianism": "David Hume",  # Empirical approach to ethics
        }
        
        # Category to philosopher mapping for dynamic selection
        self.category_mappings = {
            "ethical_dilemmas": "Aristotle",
            "epistemology": "David Hume", 
            "metaphysics": "Aristotle",
            "political_philosophy": "John Locke",
            "logic_reasoning": "Aristotle",
            "bioethics": "Immanuel Kant",
            "aesthetics": "Immanuel Kant",
            "metaethics": "David Hume",
            "philosopher_impersonation": "Aristotle",  # Default, should be overridden
        }
        
        # Fallback philosopher for unmapped categories
        self.default_philosopher = "Aristotle"
    
    def normalize_philosopher_name(self, test_name: str) -> str:
        """
        Map test philosopher names to system names.
        
        Args:
            test_name: The philosopher name used in tests
            
        Returns:
            The corresponding system philosopher name
        """
        if not test_name:
            return self.default_philosopher
            
        # Handle special case for Meta Collection
        if test_name == "Meta Collection":
            return "Meta Collection"
            
        # Try direct mapping first
        if test_name in self.test_to_system_mapping:
            return self.test_to_system_mapping[test_name]
        
        # Try case-insensitive lookup
        test_name_lower = test_name.lower()
        for test_key, system_name in self.test_to_system_mapping.items():
            if test_key.lower() == test_name_lower:
                return system_name
        
        # If no mapping found, return default
        return self.default_philosopher
    
    def get_philosopher_for_category(self, category: str) -> str:
        """
        Get appropriate philosopher for a philosophical category.
        
        Args:
            category: The philosophical category or domain
            
        Returns:
            The most appropriate philosopher for that category
        """
        if not category:
            return self.default_philosopher
            
        # Direct category mapping
        if category in self.category_mappings:
            return self.category_mappings[category]
        
        # Try case-insensitive lookup
        category_lower = category.lower()
        for cat_key, philosopher in self.category_mappings.items():
            if cat_key.lower() == category_lower:
                return philosopher
        
        # Try partial matching for subcategories
        for cat_key, philosopher in self.category_mappings.items():
            if cat_key.lower() in category_lower or category_lower in cat_key.lower():
                return philosopher
        
        # Fallback to default
        return self.default_philosopher
    
    def validate_philosopher_availability(self, philosopher_name: str) -> bool:
        """
        Check if a philosopher is available in the system.
        
        Args:
            philosopher_name: The philosopher name to validate
            
        Returns:
            True if the philosopher is available, False otherwise
        """
        special_collections = {"Meta Collection", "Combined Collection"}
        if philosopher_name in special_collections:
            return True
            
        return philosopher_name in self.system_philosophers
    
    def get_available_philosophers(self) -> Set[str]:
        """
        Get all available philosophers in the system.
        
        Returns:
            Set of available philosopher names
        """
        # Include both philosopher collections and special collections
        available = self.system_philosophers.copy()
        special_collections = {"Meta Collection", "Combined Collection"}
        return available.union(special_collections)
    
    def get_fallback_philosopher(self, preferred_philosopher: str) -> str:
        """
        Get a fallback philosopher if the preferred one is not available.
        
        Args:
            preferred_philosopher: The preferred philosopher name
            
        Returns:
            A valid philosopher name (either the preferred one or a fallback)
        """
        if self.validate_philosopher_availability(preferred_philosopher):
            return preferred_philosopher
        
        # Try to normalize first
        normalized = self.normalize_philosopher_name(preferred_philosopher)
        if self.validate_philosopher_availability(normalized):
            return normalized
        
        # Return default fallback
        return self.default_philosopher
    
    def update_test_data_philosophers(self, test_data: Dict) -> Dict:
        """
        Update test data to use valid philosopher names.
        
        Args:
            test_data: Test data dictionary that may contain philosopher references
            
        Returns:
            Updated test data with normalized philosopher names
        """
        updated_data = test_data.copy()
        
        # Update collection field if present
        if "collection" in updated_data:
            updated_data["collection"] = self.normalize_philosopher_name(updated_data["collection"])
        
        # Update philosopher field if present
        if "philosopher" in updated_data:
            updated_data["philosopher"] = self.normalize_philosopher_name(updated_data["philosopher"])
        
        # Update requires_philosopher field if present
        if "requires_philosopher" in updated_data:
            if updated_data["requires_philosopher"]:
                updated_data["requires_philosopher"] = self.normalize_philosopher_name(
                    updated_data["requires_philosopher"]
                )
        
        # Handle nested structures
        if "input" in updated_data and isinstance(updated_data["input"], dict):
            if "collection" in updated_data["input"]:
                updated_data["input"]["collection"] = self.normalize_philosopher_name(
                    updated_data["input"]["collection"]
                )
            if "philosopher" in updated_data["input"]:
                updated_data["input"]["philosopher"] = self.normalize_philosopher_name(
                    updated_data["input"]["philosopher"]
                )
        
        return updated_data
    
    def select_philosopher_for_test_scenario(self, 
                                           prompt_data: Dict, 
                                           test_variant: Optional[Dict] = None) -> str:
        """
        Select the most appropriate philosopher for a test scenario.
        
        Args:
            prompt_data: The prompt data from test catalog
            test_variant: Optional test variant data
            
        Returns:
            The most appropriate philosopher for this test scenario
        """
        # Check if philosopher is explicitly required
        if prompt_data.get("requires_philosopher"):
            return self.normalize_philosopher_name(prompt_data["requires_philosopher"])
        
        # Check test variant for persona
        if test_variant and test_variant.get("payload", {}).get("persona"):
            return self.normalize_philosopher_name(test_variant["payload"]["persona"])
        
        # Use category-based selection
        category = prompt_data.get("category", "")
        subcategory = prompt_data.get("subcategory", "")
        
        # Try subcategory first (more specific)
        if subcategory:
            philosopher = self.get_philosopher_for_category(subcategory)
            if philosopher != self.default_philosopher:
                return philosopher
        
        # Try main category
        if category:
            return self.get_philosopher_for_category(category)
        
        # Fallback to default
        return self.default_philosopher
    
    def get_category_philosopher_mapping(self) -> Dict[str, str]:
        """
        Get the complete mapping of categories to philosophers.
        
        Returns:
            Dictionary mapping categories to philosopher names
        """
        return self.category_mappings.copy()
    
    def add_category_mapping(self, category: str, philosopher: str) -> None:
        """
        Add a new category to philosopher mapping.
        
        Args:
            category: The category name
            philosopher: The philosopher name to map to
        """
        if self.validate_philosopher_availability(philosopher):
            self.category_mappings[category] = philosopher
        else:
            normalized = self.normalize_philosopher_name(philosopher)
            if self.validate_philosopher_availability(normalized):
                self.category_mappings[category] = normalized
            else:
                raise ValueError(f"Philosopher '{philosopher}' is not available in the system")
    
    def get_philosophers_by_specialty(self) -> Dict[str, List[str]]:
        """
        Get philosophers grouped by their philosophical specialties.
        
        Returns:
            Dictionary mapping specialties to lists of philosopher names
        """
        specialties = {
            "Ethics": ["Aristotle", "Immanuel Kant"],
            "Political Philosophy": ["John Locke", "Immanuel Kant"],
            "Epistemology": ["David Hume", "John Locke", "Immanuel Kant"],
            "Metaphysics": ["Aristotle", "David Hume", "Immanuel Kant"],
            "Aesthetics": ["Immanuel Kant", "David Hume"],
            "Logic": ["Aristotle"],
            "Existentialism": ["Friedrich Nietzsche"],
            "Empiricism": ["David Hume", "John Locke"],
            "Rationalism": ["Immanuel Kant"],
            "Ancient Philosophy": ["Aristotle"],
            "Modern Philosophy": ["John Locke", "David Hume", "Immanuel Kant"],
            "Contemporary Philosophy": ["Friedrich Nietzsche"]
        }
        return specialties
    
    def suggest_alternative_philosophers(self, category: str) -> List[str]:
        """
        Suggest alternative philosophers for a given category.
        
        Args:
            category: The philosophical category
            
        Returns:
            List of alternative philosopher names
        """
        specialties = self.get_philosophers_by_specialty()
        
        # Find matching specialties
        alternatives = []
        category_lower = category.lower()
        
        for specialty, philosophers in specialties.items():
            if specialty.lower() in category_lower or category_lower in specialty.lower():
                alternatives.extend(philosophers)
        
        # Remove duplicates and return
        return list(set(alternatives)) if alternatives else [self.default_philosopher]


# Global instance for easy access
philosopher_mapper = PhilosopherTestMapper()