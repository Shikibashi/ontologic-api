"""Input validation for the ontologic API."""

import re
from typing import List, Optional, Dict, Any
from app.core.exceptions import ValidationError
from app.core.logger import log


class WorkflowValidator:
    """Validator for workflow-related inputs."""

    # Valid philosophers/collections
    VALID_COLLECTIONS = {
        "Aristotle", "Plato", "Socrates", "Kant", "Hume", "Descartes",
        "Nietzsche", "Aquinas", "Augustine", "Wittgenstein", "Russell",
        "Heidegger", "Sartre", "Camus", "Spinoza", "Locke", "Berkeley",
        "Mill", "Bentham", "Marx", "Foucault", "Derrida", "Rawls"
    }

    # Valid sections for papers
    VALID_SECTIONS = {
        "abstract", "introduction", "argument", "counterarguments", "conclusion"
    }

    # Valid expansion methods
    VALID_EXPANSION_METHODS = {
        "hyde", "rag_fusion", "self_ask", "prf"
    }

    # Valid review criteria
    VALID_REVIEW_CRITERIA = {
        "accuracy", "argument", "coherence", "citations", "style", "structure", "clarity"
    }

    # Valid severity gates
    VALID_SEVERITY_GATES = {"low", "medium", "high"}

    @staticmethod
    def validate_paper_creation(
        title: str,
        topic: str,
        collection: str,
        immersive_mode: bool = False,
        temperature: float = 0.3,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Validate paper creation inputs."""

        # Title validation
        if not title or not isinstance(title, str):
            raise ValidationError("Title is required and must be a string")

        title = title.strip()
        if len(title) < 5:
            raise ValidationError("Title must be at least 5 characters long")
        if len(title) > 200:
            raise ValidationError("Title must be less than 200 characters")

        # Check for inappropriate content patterns
        inappropriate_patterns = [
            r'\b(hack|crack|exploit|malware|virus)\b',
            r'\b(illegal|criminal|fraud|scam)\b',
            r'\b(offensive|hate|discrimination)\b'
        ]
        for pattern in inappropriate_patterns:
            if re.search(pattern, title, re.IGNORECASE):
                raise ValidationError("Title contains inappropriate content")

        # Topic validation
        if not topic or not isinstance(topic, str):
            raise ValidationError("Topic is required and must be a string")

        topic = topic.strip()
        if len(topic) < 10:
            raise ValidationError("Topic must be at least 10 characters long")
        if len(topic) > 500:
            raise ValidationError("Topic must be less than 500 characters")

        # Collection validation
        if not collection or not isinstance(collection, str):
            raise ValidationError("Collection is required and must be a string")

        if collection not in WorkflowValidator.VALID_COLLECTIONS:
            raise ValidationError(
                f"Invalid collection '{collection}'. Valid collections: {', '.join(sorted(WorkflowValidator.VALID_COLLECTIONS))}"
            )

        # Temperature validation
        if not isinstance(temperature, (int, float)):
            raise ValidationError("Temperature must be a number")
        if not (0.0 <= temperature <= 1.0):
            raise ValidationError("Temperature must be between 0.0 and 1.0")

        # Immersive mode validation
        if not isinstance(immersive_mode, bool):
            raise ValidationError("Immersive mode must be a boolean")

        # Metadata validation
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise ValidationError("Metadata must be a dictionary")
            if len(str(metadata)) > 1000:  # Prevent oversized metadata
                raise ValidationError("Metadata is too large")

        log.info(f"Paper creation validation passed for title: '{title[:50]}...'")

    @staticmethod
    def validate_section_generation(
        sections: List[str],
        use_expansion: bool = True,
        expansion_methods: Optional[List[str]] = None
    ) -> None:
        """Validate section generation inputs."""

        # Sections validation
        if not sections or not isinstance(sections, list):
            raise ValidationError("Sections must be a non-empty list")

        if len(sections) > 10:
            raise ValidationError("Too many sections requested (maximum 10)")

        for section in sections:
            if not isinstance(section, str):
                raise ValidationError("All sections must be strings")
            if section not in WorkflowValidator.VALID_SECTIONS:
                raise ValidationError(
                    f"Invalid section '{section}'. Valid sections: {', '.join(sorted(WorkflowValidator.VALID_SECTIONS))}"
                )

        # Expansion validation
        if not isinstance(use_expansion, bool):
            raise ValidationError("use_expansion must be a boolean")

        if expansion_methods is not None:
            if not isinstance(expansion_methods, list):
                raise ValidationError("expansion_methods must be a list")

            if len(expansion_methods) > 5:
                raise ValidationError("Too many expansion methods (maximum 5)")

            for method in expansion_methods:
                if not isinstance(method, str):
                    raise ValidationError("All expansion methods must be strings")
                if method not in WorkflowValidator.VALID_EXPANSION_METHODS:
                    raise ValidationError(
                        f"Invalid expansion method '{method}'. Valid methods: {', '.join(sorted(WorkflowValidator.VALID_EXPANSION_METHODS))}"
                    )

        log.info(f"Section generation validation passed for {len(sections)} sections")

    @staticmethod
    def validate_review_request(
        rubric: Optional[List[str]] = None,
        severity_gate: str = "medium",
        max_evidence_per_question: int = 5
    ) -> None:
        """Validate review request inputs."""

        # Rubric validation
        if rubric is not None:
            if not isinstance(rubric, list):
                raise ValidationError("Rubric must be a list")

            if len(rubric) > 10:
                raise ValidationError("Too many rubric criteria (maximum 10)")

            for criterion in rubric:
                if not isinstance(criterion, str):
                    raise ValidationError("All rubric criteria must be strings")
                if criterion not in WorkflowValidator.VALID_REVIEW_CRITERIA:
                    raise ValidationError(
                        f"Invalid rubric criterion '{criterion}'. Valid criteria: {', '.join(sorted(WorkflowValidator.VALID_REVIEW_CRITERIA))}"
                    )

        # Severity gate validation
        if not isinstance(severity_gate, str):
            raise ValidationError("Severity gate must be a string")
        if severity_gate not in WorkflowValidator.VALID_SEVERITY_GATES:
            raise ValidationError(
                f"Invalid severity gate '{severity_gate}'. Valid gates: {', '.join(sorted(WorkflowValidator.VALID_SEVERITY_GATES))}"
            )

        # Evidence limit validation
        if not isinstance(max_evidence_per_question, int):
            raise ValidationError("max_evidence_per_question must be an integer")
        if not (1 <= max_evidence_per_question <= 20):
            raise ValidationError("max_evidence_per_question must be between 1 and 20")

        log.info(f"Review request validation passed with {len(rubric or [])} criteria")

    @staticmethod
    def validate_draft_id(draft_id: str) -> None:
        """Validate draft ID format."""
        if not draft_id or not isinstance(draft_id, str):
            raise ValidationError("Draft ID is required and must be a string")

        # Check if it's a valid UUID format
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        if not re.match(uuid_pattern, draft_id, re.IGNORECASE):
            raise ValidationError("Draft ID must be a valid UUID format")

    @staticmethod
    def validate_content_quality(content: str, section_type: str) -> None:
        """Validate generated content quality."""
        if not content or not isinstance(content, str):
            raise ValidationError("Content is required and must be a string")

        content = content.strip()

        # Minimum length requirements by section type
        min_lengths = {
            "abstract": 100,
            "introduction": 150,
            "argument": 200,
            "counterarguments": 150,
            "conclusion": 100
        }

        min_length = min_lengths.get(section_type, 50)
        if len(content) < min_length:
            raise ValidationError(f"Content too short for {section_type} section (minimum {min_length} characters)")

        # Maximum length check
        if len(content) > 5000:
            raise ValidationError(f"Content too long for {section_type} section (maximum 5000 characters)")

        # Check for minimal philosophical content
        philosophical_indicators = [
            'argument', 'premise', 'conclusion', 'logic', 'reasoning',
            'philosophy', 'ethics', 'metaphysics', 'epistemology',
            'therefore', 'because', 'thus', 'hence', 'consequently'
        ]

        content_lower = content.lower()
        indicator_count = sum(1 for indicator in philosophical_indicators if indicator in content_lower)

        if indicator_count < 2:
            raise ValidationError(f"Content appears to lack philosophical substance for {section_type} section")

        log.info(f"Content quality validation passed for {section_type} ({len(content)} chars)")


# Global validator instance
workflow_validator = WorkflowValidator()