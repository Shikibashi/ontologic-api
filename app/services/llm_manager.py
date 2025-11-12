from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.core.base.llms.types import CompletionResponse
import numpy as np
from transformers import AutoModelForMaskedLM, AutoTokenizer
from typing import Dict, List, Any, TYPE_CHECKING
import torch
import ollama
from app.core.philosopher_info import PHILOSOPHER_INFO

from app.config.settings import get_settings
from app.core.logger import log
from app.services.prompt_renderer import PromptRenderer
from app.core.exceptions import LLMError, LLMTimeoutError, LLMResponseError, LLMUnavailableError
from app.core.cache_helpers import with_cache
from app.core.http_error_guard import with_retry
# Removed deprecated cache decorators - using instance-based caching via dependency injection
from app.core.metrics import (
    track_llm_query,
    llm_embedding_duration_seconds,
    llm_splade_duration_seconds,
    llm_query_tokens_total
)
from app.core.tracing import trace_async_operation, set_span_attributes, add_span_event, get_current_span
from app.core.timeout_helpers import calculate_per_attempt_timeout
import time

if TYPE_CHECKING:
    from app.services.cache_service import RedisCacheService
from app.core.constants import (
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_LLM_TOP_P,
    DEFAULT_LLM_TOP_K,
    DEFAULT_LLM_NUM_PREDICT,
    STREAM_INIT_TIMEOUT_SECONDS,
    MIN_CONTEXT_WINDOW,
    MAX_NODES_FOR_CONTEXT,
    EMBEDDING_CACHE_TTL,
)
import asyncio

# Model configuration loaded from Pydantic Settings via TOML files
# These will be accessed within the class initialization


# Note: This class is no longer a singleton. Use dependency injection from app.core.dependencies.get_llm_manager().
class LLMManager:
    def __init__(self, prompt_renderer: 'PromptRenderer' = None, cache_service: 'RedisCacheService' = None):
        """Initialize LLM manager with models and timeouts. Called once per instance."""
        self._llm = None
        self._embed_model = None
        self._splade_tokenizer = None
        self._splade_model = None
        self._prompts = prompt_renderer  # Use injected instance or None
        self._cache_service = cache_service  # Injected cache service for embeddings and vectors

        # Store TTL values locally for safer access (avoid AttributeError if cache_service is None or lacks attributes)
        self._embedding_ttl = getattr(cache_service, '_ttl_embeddings', EMBEDDING_CACHE_TTL) if cache_service else EMBEDDING_CACHE_TTL
        self._splade_ttl = getattr(cache_service, '_ttl_splade_vectors', EMBEDDING_CACHE_TTL) if cache_service else EMBEDDING_CACHE_TTL

        self._timeouts = self._load_timeouts()
        self._initialize_models()

    @classmethod
    async def start(cls, settings=None, prompt_renderer: 'PromptRenderer' = None, cache_service: 'RedisCacheService' = None):
        """
        Async factory method for lifespan-managed initialization.

        Args:
            settings: Optional settings override (unused, kept for compatibility)
            prompt_renderer: Optional PromptRenderer instance for dependency injection
            cache_service: Optional RedisCacheService instance for caching embeddings and vectors

        Returns:
            Initialized LLMManager instance
        """
        instance = cls(prompt_renderer=prompt_renderer, cache_service=cache_service)
        log.info("LLMManager initialized for lifespan management")
        return instance

    async def aclose(self):
        """Async cleanup for lifespan management."""
        # Clean up any async resources if needed
        log.info("LLMManager cleaned up")

    def _load_timeouts(self) -> Dict[str, int]:
        """Load timeout settings from Pydantic Settings."""
        settings = get_settings()
        
        return {
            "request": settings.llm_request_timeout,
            "generation": settings.llm_generation_timeout,
            "chat": settings.llm_chat_timeout,
            "vet": settings.llm_vet_timeout,
        }

    def shutdown(self) -> None:
        """Release model resources. Instance can be garbage collected after this."""

        def _safe_close(resource, resource_name: str) -> None:
            if resource is None:
                return
            try:
                close_method = getattr(resource, "close", None)
                if callable(close_method):
                    close_method()
            except Exception as exc:
                log.warning(f"Failed to close {resource_name}: {exc}")

        _safe_close(self._llm, "LLM client")
        _safe_close(self._embed_model, "embedding model")

        self._llm = None
        self._embed_model = None
        self._splade_model = None
        self._splade_tokenizer = None
        self._prompts = None

        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as exc:
            log.debug(f"Unable to empty CUDA cache: {exc}")

        log.info("LLM resources released successfully")

    def _initialize_models(self):
        """Initialize LLM and embedding models (called only once)."""
        log.info("Initializing LLM and embedding models...")

        try:
            # Get model configuration from Pydantic Settings
            settings = get_settings()
            
            # Load model names from settings (loaded from TOML files + env vars)
            llm_model = settings.llm_model
            embed_model = settings.embed_model
            splade_model = settings.splade_model
            
            # Initialize LLM with performance optimizations
            self._llm = Ollama(
                model=llm_model,
                request_timeout=self._timeouts["request"],
                # Performance optimizations
                temperature=DEFAULT_LLM_TEMPERATURE,
                top_p=DEFAULT_LLM_TOP_P,
                top_k=DEFAULT_LLM_TOP_K,
                num_predict=DEFAULT_LLM_NUM_PREDICT,
            )

            self.set_llm_context_window(settings.default_context_window)

            # Initialize SPLADE model and tokenizer with compilation
            try:
                from app.services.model_compiler import ModelCompiler
                
                self._splade_tokenizer = AutoTokenizer.from_pretrained(splade_model, use_fast=True)
                splade_model_raw = AutoModelForMaskedLM.from_pretrained(splade_model)
                
                # Apply optimizations during startup
                self._splade_model = ModelCompiler.optimize_model(splade_model_raw, "SPLADE")
                
                # Set to evaluation mode after compilation
                self._splade_model.eval()
                
                # Move to device
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self._splade_model = self._splade_model.to(device)
                
                log.info(f"SPLADE model initialized with optimizations on device: {device}")
            except Exception as e:
                log.error(f"Failed to initialize SPLADE model: {e}")
                raise LLMError(f"SPLADE model initialization failed: {e}") from e

            # Initialize embedding model with retry logic
            try:
                self._embed_model = OllamaEmbedding(embed_model)
            except ollama._types.ResponseError:
                log.warning("Embedding model not found, downloading and converting...")
                try:
                    from app.utils.hf_model_to_gguf import HfModelToGGUF

                    embed_retriever = HfModelToGGUF(embed_model)
                    embed_retriever.download_hf_model()
                    embed_retriever.convert_and_install_hf_to_gguf()
                    self._embed_model = OllamaEmbedding(embed_model)
                except Exception as e:
                    log.error(f"Failed to download/convert embedding model: {e}")
                    raise LLMError(f"Embedding model initialization failed: {e}") from e

            # Initialize prompt renderer (use injected instance or create fallback)
            if self._prompts is None:
                try:
                    self._prompts = PromptRenderer()
                    log.warning(
                        "LLMManager creating own PromptRenderer - "
                        "consider using dependency injection via start() method"
                    )
                except Exception as e:
                    log.error(f"Failed to initialize prompt renderer: {e}")
                    raise LLMError(f"Prompt renderer initialization failed: {e}") from e
            else:
                log.debug("LLMManager using injected PromptRenderer")

            log.info("Models initialized successfully")

        except Exception as e:
            log.error(f"Model initialization failed: {e}")
            raise LLMError(f"Failed to initialize models: {e}") from e

    @property
    def llm(self):
        """Get the LLM instance."""
        if self._llm is None:
            raise RuntimeError("LLM not initialized")
        return self._llm

    @property
    def embed_model(self):
        """Get the embedding model instance."""
        if self._embed_model is None:
            raise RuntimeError("Embedding model not initialized")
        return self._embed_model

    @property
    def splade_model(self):
        """Get the splade model instance."""
        if self._splade_model is None:
            raise RuntimeError("Splade model not initialized")
        return self._splade_model

    @property
    def splade_tokenizer(self):
        """Get the splade model instance."""
        if self._splade_tokenizer is None:
            raise RuntimeError("Splade model not initialized")
        return self._splade_tokenizer

    def set_temperature(self, temperature: float) -> None:
        """Set model temperature safely."""
        self.llm.temperature = temperature

    @track_llm_query(model=lambda self: get_settings().llm_model, operation_type='query')
    @with_retry(max_retries=2, retryable_exceptions=(ConnectionError, LLMTimeoutError))
    @trace_async_operation("llm.query", {"operation": "completion"})
    async def aquery(
        self,
        question: str,
        temperature=0.30,
        timeout: int | None = None
    ) -> CompletionResponse:
        """
        Query the LLM with retry protection and total timeout enforcement.

        Args:
            question: The question to ask the LLM
            temperature: Sampling temperature (0.0-1.0)
            timeout: Total timeout in seconds across all retry attempts.
                     Per-attempt timeout is calculated as timeout // max_attempts.
                     With max_retries=2 (3 total attempts), each attempt gets timeout/3.
                     Default: Loaded from self._timeouts["generation"] (configured via settings).
                     Per-attempt timeout is calculated as total_timeout // max_attempts.
                     Example: With default 120s total and max_retries=2 (3 attempts), each attempt gets 40s.

        Returns:
            CompletionResponse from the LLM

        Raises:
            LLMTimeoutError: If any attempt times out
            LLMResponseError: If LLM returns invalid response
            LLMUnavailableError: If LLM service is unavailable
        """
        if not question or not question.strip():
            raise LLMError("Question cannot be empty")

        try:
            total_timeout = timeout or self._timeouts["generation"]
            # Calculate per-attempt timeout using helper (decorator has max_retries=2)
            max_attempts, per_attempt_timeout = calculate_per_attempt_timeout(
                total_timeout, max_retries=2
            )
            self.set_temperature(temperature)

            # Add span attributes
            settings = get_settings()
            set_span_attributes({
                "llm.model": settings.llm_model,
                "llm.temperature": temperature,
                "llm.timeout_total": total_timeout,
                "llm.timeout_per_attempt": per_attempt_timeout,
                "llm.question_length": len(question)
            })

            # Use per-attempt timeout to ensure total execution time doesn't exceed user-specified timeout
            response = await asyncio.wait_for(
                self.llm.acomplete(question),
                timeout=per_attempt_timeout
            )

            # Validate response
            if not response:
                raise LLMResponseError("LLM returned empty response")

            # Track token usage if available
            try:
                # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
                prompt_tokens = len(question) // 4
                completion_tokens = len(str(response)) // 4

                llm_query_tokens_total.labels(
                    model=settings.llm_model,
                    token_type='prompt'
                ).inc(prompt_tokens)

                llm_query_tokens_total.labels(
                    model=settings.llm_model,
                    token_type='completion'
                ).inc(completion_tokens)

                llm_query_tokens_total.labels(
                    model=settings.llm_model,
                    token_type='total'
                ).inc(prompt_tokens + completion_tokens)

                # Add result span attributes after operation completes
                set_span_attributes({
                    "llm.response_length": len(str(response)),
                    "llm.prompt_tokens": prompt_tokens,
                    "llm.completion_tokens": completion_tokens,
                    "llm.total_tokens": prompt_tokens + completion_tokens
                })

                # Record successful completion
                add_span_event("llm.response_received", {
                    "response_length": len(str(response)),
                    "total_tokens": prompt_tokens + completion_tokens
                })
            except Exception as e:
                log.debug(f"Failed to track token metrics: {e}")

            return response

        except asyncio.TimeoutError as e:
            log.error(f"LLM query timed out after {per_attempt_timeout}s (total timeout: {total_timeout}s): {question[:100]}...")
            # Translate asyncio.TimeoutError to LLMTimeoutError for retry decorator
            raise LLMTimeoutError(f"LLM query timed out after {per_attempt_timeout} seconds per attempt (total: {total_timeout}s)") from e

        except ConnectionError as e:
            log.error(f"LLM connection error: {e}")
            raise LLMUnavailableError("LLM service unavailable") from e

        except Exception as e:
            log.error(f"Unexpected LLM error: {e}")
            raise LLMError(f"LLM query failed: {str(e)}") from e

    # @track_llm_query(model=lambda self: get_settings().llm_model, operation_type='stream')
    # @trace_async_operation("llm.query_stream", {"operation": "streaming_completion"})
    async def aquery_stream(
        self,
        question: str,
        temperature=0.30,
        timeout: int | None = None
    ):
        """Stream LLM query response with comprehensive error handling."""
        if not question or not question.strip():
            raise LLMError("Question cannot be empty")

        effective_timeout = timeout or self._timeouts["generation"]
        self.set_temperature(temperature)

        settings = get_settings()
        set_span_attributes({
            "llm.model": settings.llm_model,
            "llm.temperature": temperature,
            "llm.timeout": effective_timeout,
            "llm.streaming": True
        })

        try:
            # Request async stream without awaiting so we get the generator itself
            stream = self.llm.astream_complete(question)

            # Stream the response with timeout monitoring
            start_time = asyncio.get_event_loop().time()
            async for chunk in stream:
                # Check if we've exceeded the total timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > effective_timeout:
                    raise LLMTimeoutError(f"LLM stream timed out after {effective_timeout} seconds")
                
                yield chunk

        except asyncio.TimeoutError:
            log.error(f"LLM stream timed out: {question[:100]}...")
            raise LLMTimeoutError(f"LLM stream timed out after {effective_timeout} seconds")

        except ConnectionError as e:
            log.error(f"LLM connection error in stream: {e}")
            raise LLMUnavailableError("LLM service unavailable") from e

        except Exception as e:
            log.error(f"Unexpected LLM stream error: {e}")
            raise LLMError(f"LLM stream failed: {str(e)}") from e

    def _build_context_from_nodes(self, context: List) -> str:
        """
        Extract and deduplicate node content from context.
        
        Args:
            context: List of nodes with payload containing text/summary/conjecture
        
        Returns:
            Concatenated string of unique node content
        """
        # Ensure only unique nodes by node.id
        seen_ids = set()
        unique_nodes = []
        for node in context:
            if node.id and node.id not in seen_ids:
                unique_nodes.append(node)
                seen_ids.add(node.id)
        
        # Extract content from nodes
        node_content = ""
        for node in unique_nodes:
            if "text" in node.payload:
                node_content += f"\n{node.payload['text']}"
            elif "summary" in node.payload:
                node_content += f"\n{node.payload['summary']}"
            elif "conjecture" in node.payload:
                node_content += f"\n{node.payload['conjecture']}"
            else:
                log.warning(
                    f"Node {node.id} has no text, summary, or conjecture in payload. Skipping."
                )
                continue
        
        return node_content

    def _build_conversation_messages(self, conversation_history: List) -> List[ChatMessage]:
        """
        Convert conversation history to ChatMessage format.
        
        Args:
            conversation_history: List of messages with role and text attributes
        
        Returns:
            List of ChatMessage objects
        """
        messages = []
        for message in conversation_history or []:
            if message.role == MessageRole.USER:
                messages.append(ChatMessage(role="user", content=message.text))
            elif message.role == MessageRole.ASSISTANT:
                messages.append(ChatMessage(role="assistant", content=message.text))
            else:
                log.warning(f"Unknown message role: {message.role}. Skipping.")
        
        return messages

    def _render_system_prompt(
        self, immersive_mode: str | None, prompt_type: str | None
    ) -> tuple[str, str]:
        """
        Render system prompt based on mode and type.
        
        Args:
            immersive_mode: Philosopher name for immersive mode (e.g., 'aristotle')
            prompt_type: Optional prompt type override ('adaptive', 'writer_academic', 'reviewer')
        
        Returns:
            Tuple of (system_prompt, speaker_name)
        """
        # Handle prompt_type overrides first
        if isinstance(prompt_type, str):
            if prompt_type == "adaptive":
                system_prompt = self._prompts.render(
                    "chat/adaptive_system.j2",
                    {
                        "conversation_mode": "tutorial",
                        "personality": PHILOSOPHER_INFO.get(immersive_mode, {}).get("personality", []) if immersive_mode else [],
                        "expertise_level": "beginner",
                    },
                )
                speaker_name = immersive_mode if immersive_mode else "Sophia"
                return system_prompt, speaker_name
            
            elif prompt_type == "writer_academic":
                system_prompt = self._prompts.render(
                    "workflows/writer/academic_system.j2",
                    {
                        "role_name": "an academic philosophical writer",
                        "role_description": "writing formal, well-structured analyses with evidence grounded in provided context",
                        "philosopher_name": immersive_mode,
                    },
                )
                speaker_name = immersive_mode if immersive_mode else "Sophia"
                return system_prompt, speaker_name
            
            elif prompt_type == "reviewer":
                system_prompt = self._prompts.render(
                    "workflows/reviewer/system.j2",
                    {
                        "criteria": None,
                        "tone": "professional",
                    },
                )
                speaker_name = "Reviewer"
                return system_prompt, speaker_name
        
        # Default: immersive vs neutral mode
        if immersive_mode:
            if immersive_mode not in PHILOSOPHER_INFO:
                raise ValueError(
                    f"Immersive mode '{immersive_mode}' is not recognized. Available modes: {list(PHILOSOPHER_INFO.keys())}"
                )
            character_info = PHILOSOPHER_INFO[immersive_mode]
            system_prompt = self._prompts.render(
                "chat/immersive_system.j2",
                {
                    "name": immersive_mode,
                    "axioms": character_info.get("axioms", []),
                    "personality": character_info.get("personality", []),
                    "rhetorical_tactics": character_info.get("rhetorical_tactics", []),
                    "response_protocol": character_info.get("response_protocol", []),
                    "cognitive_tone": character_info.get("cognitive_tone", []),
                },
            )
            speaker_name = immersive_mode
        else:
            system_prompt = self._prompts.render("chat/neutral_system.j2")
            speaker_name = "Sophia"
        
        return system_prompt, speaker_name

    def _render_user_prompt(
        self,
        prompt_type: str | None,
        speaker_name: str,
        node_content: str,
        query_str: str,
    ) -> str:
        """
        Render user prompt content based on prompt type.
        
        Args:
            prompt_type: Optional prompt type ('reviewer' uses special template)
            speaker_name: Name of the speaker/assistant
            node_content: Extracted context from nodes
            query_str: User's query string
        
        Returns:
            Rendered user content string
        """
        # Reviewer flow uses dedicated template
        if isinstance(prompt_type, str) and prompt_type == "reviewer":
            manuscript = f"Question: {query_str}\n\nContext:\n{node_content}"
            user_content = self._prompts.render(
                "workflows/reviewer/user.j2",
                {
                    "manuscript": manuscript,
                    "rubric": None,
                    "questions": None,
                },
            )
        else:
            # Default user content template
            user_content = self._prompts.render(
                "chat/user.j2",
                {
                    "name": speaker_name,
                    "node_content": node_content,
                    "query_str": query_str,
                },
            )
        
        return user_content

    @trace_async_operation("llm.chat", {"operation": "chat_completion"})
    async def achat(
        self,
        query_str,
        context,
        temperature=0.30,
        conversation_history=None,
        immersive_mode=None,
        prompt_type=None,
        timeout: int | None = None,
    ) -> CompletionResponse:
        """
        Generate chat response using LLM with context and conversation history.

        Args:
            query_str: User's query string
            context: List of nodes with relevant context
            temperature: LLM temperature (0-1)
            conversation_history: Previous conversation messages
            immersive_mode: Philosopher name for immersive mode
            prompt_type: Optional prompt type override
            timeout: Timeout in seconds for LLM response (default: from settings)

        Returns:
            CompletionResponse from LLM

        Raises:
            LLMTimeoutError: If LLM call times out
            LLMUnavailableError: If LLM service is unavailable
            LLMError: For other LLM-related errors
        """
        # Step 1: Extract and deduplicate node content
        node_content = self._build_context_from_nodes(context)
        
        # Validate that we have content to work with
        if not node_content.strip():
            log.warning(
                "No context provided in the payload. Returning default message."
            )
            return "No context provided. Please ensure the payload contains text, summary, or conjecture."
        
        # Step 2: Build conversation history messages
        messages = self._build_conversation_messages(conversation_history)
        
        # Step 3: Render system prompt and get speaker name
        system_prompt, speaker_name = self._render_system_prompt(
            immersive_mode, prompt_type
        )
        
        # Step 4: Render user prompt content
        user_content = self._render_user_prompt(
            prompt_type, speaker_name, node_content, query_str
        )
        
        # Step 5: Assemble final message list
        messages = [ChatMessage(role="system", content=system_prompt), *messages, ChatMessage(role="user", content=user_content)]
        
        # Step 6: Execute LLM call with timeout and error handling
        try:
            chat_timeout = timeout or self._timeouts["chat"]
            self.set_temperature(temperature)

            settings = get_settings()
            set_span_attributes({
                "llm.model": settings.llm_model,
                "llm.temperature": temperature,
                "llm.timeout": chat_timeout,
                "llm.immersive_mode": immersive_mode or "neutral",
                "llm.prompt_type": prompt_type or "default",
                "llm.context_nodes": len(context),
                "llm.conversation_history_length": len(conversation_history or [])
            })
            
            # Use asyncio.wait_for to enforce timeout
            response = await asyncio.wait_for(
                self.llm.achat(messages),
                timeout=chat_timeout
            )
            
            # Validate response
            if not response:
                raise LLMResponseError("LLM returned empty response")
            
            return response
        
        except asyncio.TimeoutError:
            log.error(f"LLM chat timed out after {chat_timeout}s for query: {query_str[:100]}...")
            raise LLMTimeoutError(f"LLM chat timed out after {chat_timeout} seconds")
        
        except ConnectionError as e:
            log.error(f"LLM connection error in chat: {e}")
            raise LLMUnavailableError("LLM service unavailable") from e
        
        except Exception as e:
            log.error(f"Unexpected LLM chat error: {e}")
            raise LLMError(f"LLM chat failed: {str(e)}") from e

    async def achat_stream(
        self,
        query_str,
        context,
        temperature=0.30,
        conversation_history=None,
        immersive_mode=None,
        prompt_type=None,
        timeout: int | None = None,
    ):
        """
        Stream chat response using LLM with context and conversation history.

        Args:
            query_str: User's query string
            context: List of nodes with relevant context
            temperature: LLM temperature (0-1)
            conversation_history: Previous conversation messages
            immersive_mode: Philosopher name for immersive mode
            prompt_type: Optional prompt type override
            timeout: Timeout in seconds for LLM response (default: from settings)

        Yields:
            Streaming response chunks from LLM

        Raises:
            LLMTimeoutError: If LLM call times out
            LLMUnavailableError: If LLM service is unavailable
            LLMError: For other LLM-related errors
        """
        # Step 1: Extract and deduplicate node content
        node_content = self._build_context_from_nodes(context)
        
        # Validate that we have content to work with
        if not node_content.strip():
            log.warning(
                "No context provided in the payload. Returning default message."
            )
            yield "No context provided. Please ensure the payload contains text, summary, or conjecture."
            return
        
        # Step 2: Build conversation history messages
        messages = self._build_conversation_messages(conversation_history)
        
        # Step 3: Render system prompt and get speaker name
        system_prompt, speaker_name = self._render_system_prompt(
            immersive_mode, prompt_type
        )
        
        # Step 4: Render user prompt content
        user_content = self._render_user_prompt(
            prompt_type, speaker_name, node_content, query_str
        )
        
        # Step 5: Assemble final message list
        messages = [ChatMessage(role="system", content=system_prompt), *messages, ChatMessage(role="user", content=user_content)]

        # Step 6: Execute streaming LLM call with timeout and error handling
        chat_timeout = timeout or self._timeouts["chat"]
        self.set_temperature(temperature)

        span = get_current_span()
        if span and span.is_recording():
            settings = get_settings()
            total_message_length = sum(len(msg.content or "") for msg in messages)
            set_span_attributes({
                "llm.call_type": "chat_stream",
                "llm.model": settings.llm_model,
                "llm.temperature": temperature,
                "llm.timeout": chat_timeout,
                "llm.messages_count": len(messages),
                "llm.total_message_length": total_message_length,
                "llm.streaming": True,
            })

        try:
            # Request async stream without awaiting so we get the generator itself
            stream = self.llm.astream_chat(messages)

            # Stream the response with timeout monitoring
            start_time = asyncio.get_event_loop().time()
            async for chunk in stream:
                # Check if we've exceeded the total timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > chat_timeout:
                    raise LLMTimeoutError(f"LLM chat stream timed out after {chat_timeout} seconds")
                
                yield chunk
        
        except asyncio.TimeoutError:
            log.error(f"LLM chat stream timed out for query: {query_str[:100]}...")
            raise LLMTimeoutError(f"LLM chat stream timed out after {chat_timeout} seconds")
        
        except ConnectionError as e:
            log.error(f"LLM connection error in chat stream: {e}")
            raise LLMUnavailableError("LLM service unavailable") from e
        
        except Exception as e:
            log.error(f"Unexpected LLM chat stream error: {e}")
            raise LLMError(f"LLM chat stream failed: {str(e)}") from e

    @trace_async_operation("llm.vet", {"operation": "vet_completion"})
    async def avet(
        self, query_str, context, temperature=0.30, prompt_type=None
    ) -> CompletionResponse:
        # Ensure only unique node_ids are included
        seen_node_ids = set()
        node_texts = []

        log.info(f"Vet mode activated for query: {query_str}")

        for node in context:
            if node.id not in seen_node_ids:
                node_texts.append(
                    f"Node {node.id} from collection '{node.payload['collection_name']}': {node.payload['text'].strip()}"
                )
                seen_node_ids.add(node.id)

        system_prompt = self._prompts.render("vet/system.j2")
        user_content = self._prompts.render(
            "vet/user.j2", {"node_texts": node_texts, "query_str": query_str}
        )

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_content),
        ]
        try:
            vet_timeout = self._timeouts["vet"]
            self.set_temperature(temperature)

            # Use asyncio.wait_for to enforce timeout
            response = await asyncio.wait_for(
                self.llm.achat(messages),
                timeout=vet_timeout
            )

            # Validate response
            if not response:
                raise LLMResponseError("LLM returned empty response")

            return response

        except asyncio.TimeoutError:
            log.error(f"LLM vet timed out after {vet_timeout}s for query: {query_str[:100]}...")
            raise LLMTimeoutError(f"LLM vet timed out after {vet_timeout} seconds")

        except ConnectionError as e:
            log.error(f"LLM connection error in vet: {e}")
            raise LLMUnavailableError("LLM service unavailable") from e

        except Exception as e:
            log.error(f"Unexpected LLM vet error: {e}")
            raise LLMError(f"LLM vet failed: {str(e)}") from e

    @trace_async_operation("llm.embedding", {"operation": "dense_embedding"})
    async def get_embedding(self, text: str, timeout: int | None = None, max_attempts: int = 1):
        """
        Get embedding for given text with error handling, caching, and metrics.

        Args:
            text: Text to generate embedding for
            timeout: Total timeout in seconds (used to calculate per-attempt timeout).
                     Default: Loaded from self._timeouts["request"] (configured via settings).
                     Per-attempt timeout is calculated as total_timeout // max_attempts.
            max_attempts: Total number of attempts (used to calculate per-attempt timeout)
        """
        if not text or not text.strip():
            raise LLMError("Text cannot be empty for embedding generation")

        start_time = time.time()
        status = 'success'
        total_timeout = timeout or self._timeouts.get("request", 300)
        # If max_attempts provided, calculate per-attempt timeout; otherwise use total timeout
        if max_attempts > 1:
            _, per_attempt_timeout = calculate_per_attempt_timeout(
                total_timeout, max_retries=max_attempts - 1
            )
        else:
            per_attempt_timeout = total_timeout

        try:
            log.debug(f"Generating embedding for text (length: {len(text)})")

            settings = get_settings()
            set_span_attributes({
                "llm.model": settings.embed_model,
                "llm.text_length": len(text),
                "llm.operation": "embedding"
            })

            # Use per-attempt timeout to ensure total execution time doesn't exceed configured timeout
            result, was_cached = await asyncio.wait_for(
                with_cache(
                    self._cache_service,
                    'embedding',
                    lambda: asyncio.to_thread(self.embed_model.get_general_text_embedding, text),
                    self._embedding_ttl,
                    text,  # Cache key argument (must be before return_cache_status)
                    return_cache_status=True
                ),
                timeout=per_attempt_timeout
            )

            # Update status for metrics (cache events already emitted by cache_service)
            status = 'cached' if was_cached else 'success'

            return result
        except asyncio.TimeoutError as exc:
            status = 'timeout'
            log.error(
                f"Embedding generation timed out after {per_attempt_timeout}s (total: {total_timeout}s) for text length {len(text)}"
            )
            raise LLMTimeoutError(
                f"Embedding generation timed out after {per_attempt_timeout} seconds per attempt"
            ) from exc
        except LLMError:
            status = 'error'
            raise
        except Exception as e:
            status = 'error'
            log.error(f"Embedding generation failed: {e}")
            raise LLMError(f"Failed to generate embedding: {str(e)}") from e
        finally:
            duration = time.time() - start_time
            llm_embedding_duration_seconds.labels(
                model=settings.embed_model,
                status=status
            ).observe(duration)

    def dense_to_sparse_qdrant_format(self, vec: np.ndarray):
        vec = vec.astype(np.float32)
        indices = np.nonzero(vec)[0].tolist()
        values = vec[indices].tolist()
        return {"indices": indices, "values": values}

    @with_retry(max_retries=3, retryable_exceptions=(ConnectionError, LLMTimeoutError))
    @trace_async_operation("llm.splade_vector", {"operation": "sparse_embedding"})
    async def generate_splade_vector(self, text: str):
        """
        Generate SPLADE sparse vector for given text, in Qdrant sparse format.

        Includes caching, metrics, timeout and retry protection. The timeout represents
        the TOTAL timeout budget across all retry attempts (4 total attempts with max_retries=3).
        Per-attempt timeout is calculated as total_timeout // 4, meaning ~75s per attempt with
        the default 300s total timeout.

        Use asyncio.wait_for() when calling this method to enforce a hard total timeout.
        """
        if not text or not text.strip():
            raise LLMError("Text cannot be empty for SPLADE vector generation")

        start_time = time.time()
        status = 'success'

        settings = get_settings()
        set_span_attributes({
            "llm.model": settings.splade_model,
            "llm.text_length": len(text),
            "llm.operation": "sparse_vector"
        })

        total_timeout = self._timeouts.get("request", 300)
        # Calculate per-attempt timeout using helper (decorator has max_retries=3)
        max_attempts, per_attempt_timeout = calculate_per_attempt_timeout(
            total_timeout, max_retries=3
        )

        async def _compute_splade():
            """Inner function to compute SPLADE vector."""
            log.debug(f"Generating SPLADE vector for text (length: {len(text)})")

            # Use optimized inference without thread pool overhead (compiled models are fast)
            if hasattr(self, '_splade_model_compiled') or self._splade_model is not None:
                # Direct inference for compiled models - no need for thread pool
                inputs = self.splade_tokenizer(
                    text, return_tensors="pt", truncation=True, padding=True, max_length=512
                )

                # Move to same device as model
                device = next(self._splade_model.parameters()).device
                inputs = {k: v.to(device) for k, v in inputs.items()}

                # Use inference mode for optimal performance
                with torch.inference_mode():
                    outputs = self._splade_model(**inputs)
                    logits = outputs.logits

                sparse_vector = torch.log(1 + torch.relu(logits)).squeeze()
                sparse_vector = torch.max(sparse_vector, dim=0)[0]
                return self.dense_to_sparse_qdrant_format(sparse_vector.cpu().numpy())
            else:
                # Fallback to thread pool for non-compiled models
                def _generate_splade_sync():
                    inputs = self.splade_tokenizer(
                        text, return_tensors="pt", truncation=True, padding=True, max_length=512
                    )
                    with torch.no_grad():
                        outputs = self.splade_model(**inputs)
                        logits = outputs.logits
                    sparse_vector = torch.log(1 + torch.relu(logits)).squeeze()
                    sparse_vector = torch.max(sparse_vector, dim=0)[0]
                    return self.dense_to_sparse_qdrant_format(sparse_vector.numpy())

                return await asyncio.to_thread(_generate_splade_sync)

        try:
            # Use per-attempt timeout to ensure total execution time doesn't exceed configured timeout
            result, was_cached = await asyncio.wait_for(
                with_cache(
                    self._cache_service,
                    'splade',
                    _compute_splade,
                    self._splade_ttl,
                    text,  # Cache key argument (must be before return_cache_status)
                    return_cache_status=True
                ),
                timeout=per_attempt_timeout
            )

            # Update status for metrics (cache events already emitted by cache_service)
            status = 'cached' if was_cached else 'success'

            return result
        except asyncio.TimeoutError as exc:
            status = 'timeout'
            log.error(
                f"SPLADE vector generation timed out after {per_attempt_timeout}s (total: {total_timeout}s) for text length {len(text)}"
            )
            raise LLMTimeoutError(
                f"SPLADE vector generation timed out after {per_attempt_timeout} seconds per attempt"
            ) from exc
        except LLMError:
            status = 'error'
            raise
        except Exception as e:
            status = 'error'
            log.error(f"SPLADE vector generation failed: {e}")
            raise LLMError(f"Failed to generate SPLADE vector: {str(e)}") from e
        finally:
            duration = time.time() - start_time
            llm_splade_duration_seconds.labels(
                model=settings.splade_model,
                status=status
            ).observe(duration)

    @with_retry(max_retries=3, retryable_exceptions=(ConnectionError, LLMTimeoutError))
    @trace_async_operation("llm.dense_vector", {"operation": "dense_embedding"})
    async def generate_dense_vector(self, text: str, timeout: int | None = None) -> List[float]:
        """
        Generate dense vector using the embedding model with timeout and retry protection.

        Args:
            text: Text to generate embedding for
            timeout: Total timeout in seconds across all retry attempts.
                     Per-attempt timeout is calculated as timeout // max_attempts.
                     With max_retries=3 (4 total attempts), each attempt gets timeout/4.
                     Default: Loaded from self._timeouts["request"] (configured via settings).
                     Per-attempt timeout is calculated as total_timeout // max_attempts.
                     Example: With default 300s total and max_retries=3 (4 attempts), each attempt gets 75s.
        """
        if self.embed_model is None:
            raise ValueError(
                "Embedding model not provided. Cannot generate dense vectors."
            )
        # Pass timeout and max_attempts to get_embedding for per-attempt timeout calculation
        # Decorator has max_retries=3
        max_attempts, _ = calculate_per_attempt_timeout(
            timeout or self._timeouts.get("request", 300), max_retries=3
        )
        return await self.get_embedding(text, timeout=timeout, max_attempts=max_attempts)

    def set_llm_context_window(
        self, context_window: int | None = None
    ):
        """
        Dynamically change the LLM's context window size with validation.
        
        Args:
            context_window: Desired context window size in tokens. 
                           If None, uses default.
        
        Raises:
            ValueError: If context_window exceeds max_context limit
        """
        # Load context window settings from Pydantic Settings
        settings = get_settings()
        default_context = settings.default_context_window
        max_context = settings.max_context_window
        
        # Use default if not specified
        if context_window is None:
            context_window = default_context
        
        # Validate against maximum limit
        if context_window > max_context:
            error_msg = (
                f"Requested context window ({context_window}) exceeds maximum "
                f"allowed limit ({max_context}). Use a smaller context window."
            )
            log.error(error_msg)
            raise ValueError(error_msg)
        
        # Validate minimum (reasonable lower bound)
        if context_window < MIN_CONTEXT_WINDOW:
            log.warning(
                f"Context window ({context_window}) is very small. "
                f"Minimum recommended: {MIN_CONTEXT_WINDOW} tokens."
            )
        
        # Set the context window
        self._llm.context_window = context_window
        log.info(
            f"LLM context window set to {context_window} tokens "
            f"(default: {default_context}, max: {max_context})"
        )

    def select_appropriate_nodes(self, nodes: Dict[str, List[Any]]) -> List[Any]:
        """
        Select appropriate nodes from retrieval results based on relevance and diversity.

        Args:
            nodes: Dictionary mapping vector types to lists of retrieved nodes

        Returns:
            List of selected nodes prioritized by relevance and diversity
        """
        if not nodes:
            return []

        all_nodes = []

        # Flatten all nodes from different vector types
        for vector_type, node_list in nodes.items():
            if node_list:
                # Tag nodes with their retrieval method for transparency
                for node in node_list:
                    if hasattr(node, 'payload') and isinstance(node.payload, dict):
                        node.payload['retrieval_method'] = vector_type
                    all_nodes.append(node)

        if not all_nodes:
            return []

        # Remove duplicates based on node ID if available
        unique_nodes = []
        seen_ids = set()

        for node in all_nodes:
            node_id = getattr(node, 'id', None)
            if node_id and node_id in seen_ids:
                continue
            if node_id:
                seen_ids.add(node_id)
            unique_nodes.append(node)

        # Sort by relevance score if available
        try:
            unique_nodes.sort(key=lambda x: getattr(x, 'score', 0.0), reverse=True)
        except (AttributeError, TypeError):
            # If sorting fails, keep original order
            pass

        # Return top nodes (limit to reasonable number for context)
        selected_nodes = unique_nodes[:MAX_NODES_FOR_CONTEXT]

        log.info(f"Selected {len(selected_nodes)} nodes from {len(all_nodes)} total retrieved nodes")
        return selected_nodes

    # Instance reset no longer needed - create new instances as needed
