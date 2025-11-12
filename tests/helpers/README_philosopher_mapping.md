# Philosopher Data Mapping and Validation System

This system provides comprehensive mapping and validation for philosopher names used in the test suite, ensuring tests use valid philosopher references that match the actual system configuration.

## Components

### 1. PhilosopherTestMapper (`philosopher_test_mapper.py`)

The core mapping class that handles:
- **Name Normalization**: Maps test philosopher names to system names
- **Category-based Selection**: Selects appropriate philosophers for philosophical categories
- **Validation**: Ensures philosopher names are available in the system
- **Fallback Logic**: Provides fallbacks for unmapped categories

#### Key Mappings

**Test Names → System Names:**
- `"Ethics Core"` → `"Aristotle"`
- `"Business Ethics"` → `"Aristotle"`
- `"Global Ethics"` → `"Immanuel Kant"`
- `"Bioethics"` → `"Immanuel Kant"`
- `"Civic Ethics"` → `"John Locke"`
- `"Political Philosophy"` → `"John Locke"`

**Categories → Philosophers:**
- `"ethical_dilemmas"` → `"Aristotle"`
- `"epistemology"` → `"David Hume"`
- `"political_philosophy"` → `"John Locke"`
- `"logic_reasoning"` → `"Aristotle"`
- `"bioethics"` → `"Immanuel Kant"`
- `"aesthetics"` → `"Immanuel Kant"`

### 2. Test Philosopher Selection (`test_philosopher_selection.py`)

Utility functions and classes for dynamic philosopher selection:
- **Dynamic Selection**: Choose philosophers based on test scenarios
- **Category Helpers**: Get philosophers for specific categories
- **Validation Utilities**: Validate philosopher availability
- **TestPhilosopherSelector**: Helper class with category-specific methods

### 3. Updated Test Data

**Prompt Catalog (`fixtures/prompt_catalog.json`):**
- Updated `requires_philosopher` fields with valid names
- Updated test variant personas with normalized names

**Canned Responses (`fixtures/canned_responses.json`):**
- Updated 38 entries with correct philosopher/collection names
- All collection references now use valid system philosopher names

### 4. Integration with conftest.py

Added helper functions to conftest.py:
- `normalize_test_philosopher_name()`
- `get_philosopher_for_category()`
- `select_philosopher_for_test()`
- `get_test_philosopher_selector()`

## Usage Examples

### Basic Name Normalization
```python
from tests.helpers.philosopher_test_mapper import philosopher_mapper

# Normalize test names to system names
philosopher = philosopher_mapper.normalize_philosopher_name("Ethics Core")
# Returns: "Aristotle"
```

### Category-based Selection
```python
# Get philosopher for a category
philosopher = philosopher_mapper.get_philosopher_for_category("epistemology")
# Returns: "David Hume"
```

### Test Scenario Selection
```python
from tests.helpers.test_philosopher_selection import select_test_philosopher

prompt_data = {
    "category": "ethical_dilemmas",
    "subcategory": "applied_ethics"
}
philosopher = select_test_philosopher(prompt_data)
# Returns: "Aristotle"
```

### Using the Selector Class
```python
from tests.helpers.test_philosopher_selection import test_philosopher_selector

# Get philosophers for specific test types
ethics_philosopher = test_philosopher_selector.for_ethics_test()
political_philosopher = test_philosopher_selector.for_political_test()
logic_philosopher = test_philosopher_selector.for_logic_test()
```

### Validation
```python
# Check if a philosopher is available
is_valid = philosopher_mapper.validate_philosopher_availability("Aristotle")
# Returns: True

# Get fallback if preferred philosopher is not available
fallback = philosopher_mapper.get_fallback_philosopher("Unknown Philosopher")
# Returns: "Aristotle" (default fallback)
```

## Available System Philosophers

- **Aristotle**: Ethics, Logic, Metaphysics, Ancient Philosophy
- **Immanuel Kant**: Ethics, Political Philosophy, Epistemology, Aesthetics
- **David Hume**: Epistemology, Empiricism, Metaethics
- **John Locke**: Political Philosophy, Empiricism, Social Contract Theory
- **Friedrich Nietzsche**: Existentialism, Contemporary Philosophy

## Benefits

1. **Consistency**: All tests now use valid philosopher names
2. **Maintainability**: Centralized mapping makes updates easy
3. **Flexibility**: Dynamic selection based on test categories
4. **Validation**: Prevents tests from using invalid philosopher names
5. **Fallbacks**: Graceful handling of unmapped categories
6. **Documentation**: Clear mapping of test concepts to philosophers

## Integration Points

- **Test Fixtures**: Updated to use normalized names
- **Canned Responses**: All collection references updated
- **conftest.py**: Helper functions available globally
- **Test Files**: Can import and use mapping utilities

This system ensures that all philosopher-related test failures due to name mismatches are resolved while providing a robust foundation for future test development.