from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, Union, List
from app.core.db_models import MessageRole

class ConversationMessage(BaseModel):
    id: str
    role: str  # Keep as str for backward compatibility, but validate against MessageRole values
    text: str
    
    def validate_role(self) -> bool:
        """Validate that role is a valid MessageRole value."""
        try:
            MessageRole(self.role)
            return True
        except ValueError:
            return False

class HybridQueryRequest(BaseModel):
    """
    Request model for hybrid vector search with filtering capabilities.
    
    This model supports querying multiple vector types (sparse and dense) across different
    content representations (original, summary, conjecture) with payload-based filtering.
    
    Examples:
        Basic search:
        ```python
        request = HybridQueryRequest(
            query_str="What is virtue ethics?",
            collection="Aristotle"
        )
        ```
        
        Filtered search:
        ```python
        request = HybridQueryRequest(
            query_str="theories of justice",
            collection="Philosophy",
            filter={
                "author": ["Aristotle", "Plato"],
                "topic": "ethics"
            }
        )
        ```
        
        Specific vector types:
        ```python
        request = HybridQueryRequest(
            query_str="categorical syllogism",
            collection="Aristotle",
            vector_types=["sparse_original", "dense_original"],
            filter={"document_type": "treatise"}
        )
        ```
    """
    
    query_str: str = Field(
        ...,
        description="The search query text",
        example="What is practical wisdom in Aristotelian ethics?"
    )
    
    collection: str = Field(
        ...,
        description="Name of the Qdrant collection to search",
        example="Aristotle"
    )
    
    vector_types: List[str] = Field(
        default=None,
        description="""
        List of vector types to query. If None, searches all available types.
        
        Available vector types:
        - sparse_original: SPLADE vectors of original text
        - sparse_summary: SPLADE vectors of summarized text  
        - sparse_conjecture: SPLADE vectors of conjectural content
        - dense_original: Dense embeddings of original text
        - dense_summary: Dense embeddings of summarized text
        - dense_conjecture: Dense embeddings of conjectural content
        
        Note: conjecture types only available for non-"Meta Collection" collections
        """,
        example=["sparse_original", "dense_summary"]
    )
    
    filter: Dict[str, Union[str, List[str]]] = Field(
        default=None,
        description="""
        Payload-based filters to apply to search results.
        
        Filter Structure:
        - Keys: Payload field names
        - Values: Either a single string/value OR a list of strings/values
        
        Logic:
        - Multiple fields are combined with AND logic
        - List values within a field use OR logic
        - Single values use exact match
        
        Common payload fields:
        - author: Document author
        - topic: Subject matter tags
        - node_hierarchy: Content organization level ("Papa Bear", "Mama Bear", "Baby Bear")
        - document_type: Type of document ("treatise", "commentary", "primary source")
        - text_type: Content classification ("original", "summary", "detailed")
        - work: Specific work title
        - language: Document language
        - period/era: Historical time period
        
        Examples:
        - Single author: {"author": "Aristotle"}
        - Multiple authors: {"author": ["Aristotle", "Plato"]}
        - Complex filter: {
            "author": "Aristotle",
            "topic": ["ethics", "politics"],
            "node_hierarchy": ["Papa Bear", "Mama Bear"]
          }
        """,
        example={
            "author": "Aristotle",
            "topic": ["ethics", "virtue"],
            "document_type": "treatise"
        }
    )
    
    payload: List[str] = Field(
        default=None,
        description="""
        List of payload fields to return in results. If None, returns all payload fields.
        
        This can be used to limit response size and focus on specific metadata.
        
        Common useful fields:
        - text: Full document text
        - summary: Text summary
        - author: Document author
        - title: Document title
        - topic: Subject tags
        - node_hierarchy: Organization level
        - document_type: Document classification
        
        Example: ["author", "title", "summary", "topic"]
        """,
        example=["text", "summary", "author", "topic"]
    )
    
    conversation_history: Optional[List[ConversationMessage]] = None

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "query_str": "What is virtue ethics?",
                    "collection": "Meta Collection",
                    "vector_types": None,
                    "filter": {"philosopher": "Aristotle"},
                    "payload": ["text", "summary"]
                },
                {
                    "query_str": "theories of political philosophy",
                    "collection": "Philosophy",
                    "vector_types": ["sparse_summary", "dense_summary"],
                    "filter": {
                        "author": ["Aristotle", "Plato"],
                        "topic": "politics"
                    },
                    "payload": ["author", "title", "summary"]
                },
                {
                    "query_str": "syllogistic reasoning",
                    "collection": "Aristotle",
                    "vector_types": ["sparse_original"],
                    "filter": {
                        "work": "Prior Analytics",
                        "node_hierarchy": "Papa Bear"
                    },
                    "payload": ["text", "summary"]
                }
            ]
        }

class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class Raw(BaseModel):
    model: str
    created_at: str
    done: bool
    done_reason: str
    total_duration: int
    load_duration: int
    prompt_eval_count: int
    prompt_eval_duration: int
    eval_count: int
    eval_duration: int
    usage: Usage

class AskPhilosophyResponse(BaseModel):
    text: str
    raw: Raw


    @property
    def usage(self) -> Optional[Usage]:
        return self.raw.usage if self.raw else None
    
    @property
    def eval_duration(self) -> Optional[int]:
        return self.raw.eval_duration if self.raw else None

class AskPhilosophyRequest(BaseModel):
    """
    Request model for asking a question about a specific philosopher.
    
    This model is used to query the LLM for information related to a particular philosopher.
    
    Attributes:
        query_str (str): The question to ask about the philosopher.
        philosopher (str): The name of the philosopher to focus the question on.
    """
    
    query_str: str = Field(
        ...,
        description="The question to ask about the philosopher",
        example="What is Aristotle's view on virtue ethics?"
    )
    
    collection: str = Field(
        ...,
        description="The name of the philosopher to focus the question on",
        example="Aristotle"
    )
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "query_str": "How does Aristotle’s virtue ethics in the Nicomachean Ethics arise from, and depend upon, his teleological metaphysics as outlined in his broader philosophical system (e.g., Physics, Metaphysics)? In your answer, explain the role of the telos in both ethical and metaphysical contexts, and analyze how Aristotle’s conception of human function (ergon) and the good (eudaimonia) are grounded in his theory of form, purpose, and natural ends. Clarify how this metaphysical foundation differentiates Aristotelian virtue ethics from modern moral theories that lack a teleological structure.",
                    "collection": "Aristotle"
                }
            ]
        }