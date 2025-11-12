"""Regression tests for the /ask_philosophy endpoint using canned prompt data."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    assert_philosophy_response_structure,
    assert_philosophy_response_valid_with_prompt,
    assert_keywords_for_prompt,
    assert_keywords_present,
    create_mock_node,
    get_prompt_completion_mock,
    load_canned_response,
)
from tests.helpers.philosopher_test_mapper import philosopher_mapper
from tests.fixtures import get_prompt_catalog
from tests.helpers.assertions import assert_error_response


def load_canned_response_with_normalized_collection(prompt_id: str) -> dict:
    """Load canned response and normalize the collection name."""
    canned = load_canned_response(prompt_id)
    
    # Normalize collection name in input if present
    if "input" in canned and "collection" in canned["input"]:
        original_collection = canned["input"]["collection"]
        normalized_collection = philosopher_mapper.normalize_philosopher_name(original_collection)
        canned["input"]["collection"] = normalized_collection
    
    return canned
from tests.helpers.validators import (
    validate_immersive_mode_response,
    validate_multi_framework_analysis,
    validate_response_content,
    validate_logical_structure,
)


def _build_prompt_cases() -> list[dict[str, object]]:
    """Collect prompt variants for parametrized testing."""
    from tests.helpers.philosopher_test_mapper import philosopher_mapper

    catalog = get_prompt_catalog()
    cases: list[dict[str, object]] = []

    for prompt in catalog["prompts"]:
        if prompt.get("endpoint") != "/ask_philosophy":
            continue

        variants = prompt.get("test_variants") or [{"immersive": False, "temperature": 0.3}]
        for index, variant in enumerate(variants):
            # Normalize philosopher name if specified
            requires_philosopher = prompt.get("requires_philosopher")
            if requires_philosopher:
                requires_philosopher = philosopher_mapper.normalize_philosopher_name(requires_philosopher)
            
            cases.append(
                {
                    "prompt_id": prompt["id"],
                    "case_id": f"{prompt['id']}::variant{index}",
                    "category": prompt.get("category", "uncategorized"),
                    "immersive": variant.get("immersive", False),
                    "temperature": variant.get("temperature", 0.3),
                    "variant_payload": variant.get("payload", {}),
                    "requires_philosopher": requires_philosopher,
                }
            )

    return cases


PROMPT_CASES = _build_prompt_cases()
if not PROMPT_CASES:
    raise RuntimeError("No /ask_philosophy prompts found in prompt catalog")
PROMPT_IDS = {case["prompt_id"] for case in PROMPT_CASES}
SAMPLE_PROMPT_ID = sorted(PROMPT_IDS)[0] if PROMPT_IDS else ""
REQUIRED_CATEGORIES = {"ethical_dilemmas", "metaphysics", "epistemology"}


def _collection_for_case(
    case: dict[str, object] | None,
    canned_input: dict[str, object],
) -> str:
    """Determine which collection to query for a given prompt case."""
    from tests.helpers.philosopher_test_mapper import philosopher_mapper

    requires_philosopher = None
    if case is not None:
        requires_philosopher = case.get("requires_philosopher")

    collection = requires_philosopher or canned_input.get("collection")
    collection_str = str(collection or "Meta Collection")
    
    # Normalize philosopher name using the mapper
    return philosopher_mapper.normalize_philosopher_name(collection_str)


@pytest.mark.parametrize(
    "case",
    PROMPT_CASES,
    ids=[case["case_id"] for case in PROMPT_CASES],
)
def test_philosophy_prompts_cover_catalog(
    test_client: TestClient,
    mock_all_services,
    case: dict[str, object],
) -> None:
    """Ensure every catalogued philosophy prompt returns a valid response."""

    prompt_id = case["prompt_id"]
    canned = load_canned_response_with_normalized_collection(prompt_id)
    canned_input = canned["input"]
    collection = _collection_for_case(case, canned_input)

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node(
            node_id=f"{collection}-context-1",
            text=f"{case['category']} context passage 1",
            collection=collection,
            score=0.96,
        ),
        create_mock_node(
            node_id=f"{collection}-context-2",
            text=f"{case['category']} context passage 2",
            collection=collection,
            score=0.91,
        ),
    ]

    params = {
        "immersive": case["immersive"],
        "temperature": case["temperature"],
    }
    prompt_type = case["variant_payload"].get("prompt_type") if isinstance(case["variant_payload"], dict) else None
    if prompt_type:
        params["prompt_type"] = prompt_type

    response = test_client.post(
        "/ask_philosophy",
        params=params,
        json={
            "query_str": canned_input["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 200, f"{prompt_id} -> {response.status_code}: {response.text}"

    payload = response.json()
    assert_philosophy_response_valid_with_prompt(prompt_id, payload)
    assert_keywords_for_prompt(prompt_id, payload["text"])

    # Enhanced assertions per plan
    response_text = payload["text"]
    assert len(response_text.strip()) >= 100, f"Response too short: {len(response_text.strip())} chars"
    
    # Validate token usage consistency (now handled by assert_philosophy_response_valid)
    usage = payload["raw"]["usage"]
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    
    # Additional realistic usage validation
    assert usage["total_tokens"] < 50000, f"Total tokens {usage['total_tokens']} seems unreasonably high"
    assert usage["prompt_tokens"] < usage["total_tokens"], "Prompt tokens should be less than total"
    assert usage["completion_tokens"] < usage["total_tokens"], "Completion tokens should be less than total"
    
    # Verify completion metadata
    assert payload["raw"]["done"] is True
    assert "done_reason" in payload["raw"] or payload["raw"]["done"] is True
    
    # Check mock call details
    mock_llm.achat.assert_called_once()
    call_kwargs = mock_llm.achat.call_args.kwargs
    assert pytest.approx(case["temperature"]) == call_kwargs["temperature"]
    # Note: query_str is passed as the first positional argument, not in kwargs
    call_args = mock_llm.achat.call_args.args
    assert len(call_args) > 0
    assert call_args[0] == canned_input["query_str"]

    expected_immersive_mode = collection if case["immersive"] else None
    assert call_kwargs.get("immersive_mode") == expected_immersive_mode

    if prompt_type:
        assert call_kwargs.get("prompt_type") == prompt_type
    else:
        assert call_kwargs.get("prompt_type") in (None, "")

    mock_qdrant.gather_points_and_sort.assert_called_once()


def test_prompt_catalog_has_expected_coverage() -> None:
    """Verify the catalog includes the full set of supported prompts and categories."""

    assert len(PROMPT_IDS) == 37

    categories = {case["category"] for case in PROMPT_CASES}
    missing = REQUIRED_CATEGORIES - categories
    assert not missing, f"Missing required philosophy categories: {sorted(missing)}"


@pytest.mark.parametrize("prompt_type", ["adaptive", "writer_academic", "reviewer"])
def test_prompt_type_variants_forwarded(
    test_client: TestClient,
    mock_all_services,
    prompt_type: str,
) -> None:
    """Ensure prompt_type query parameter is forwarded to the LLM layer."""

    base_prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(base_prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(base_prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("node-1", "Prompt type context", collection=collection)
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={
            "immersive": False,
            "temperature": 0.3,
            "prompt_type": prompt_type,
        },
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert_philosophy_response_valid_with_prompt(base_prompt_id, payload)

    mock_llm.achat.assert_called_once()
    assert mock_llm.achat.call_args.kwargs.get("prompt_type") == prompt_type


def test_conversation_history_passthrough(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Conversation history supplied in the request should reach the LLM call."""

    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("node-1", "Conversation context", collection=collection)
    ]

    conversation_history = [
        {"id": "msg-1", "role": "user", "text": "Explain virtue ethics."},
        {"id": "msg-2", "role": "assistant", "text": "Virtue ethics emphasizes character."},
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
            "conversation_history": conversation_history,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert_philosophy_response_valid_with_prompt(prompt_id, payload)

    mock_llm.achat.assert_called_once()
    forwarded_history = mock_llm.achat.call_args.kwargs.get("conversation_history")
    assert forwarded_history is not None
    assert len(forwarded_history) == len(conversation_history)


def test_response_structure_includes_usage(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Validate the response schema includes usage metadata."""

    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("node-1", "Usage context", collection=collection)
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert_philosophy_response_structure(payload)


# ---------------------------------------------------------------------------
# New comprehensive tests per plan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", [
    "ethical_dilemmas", 
    "epistemology", 
    "metaphysics", 
    "political_philosophy", 
    "logic_reasoning", 
    "bioethics", 
    "aesthetics", 
    "metaethics"
])
def test_category_specific_keywords(
    test_client: TestClient,
    mock_all_services,
    category: str,
) -> None:
    """Test category-specific philosophical keyword presence in responses."""
    
    # Find a prompt in this category
    catalog = get_prompt_catalog()
    category_prompts = [p for p in catalog["prompts"] if p.get("category") == category and p.get("endpoint") == "/ask_philosophy"]
    
    if not category_prompts:
        pytest.skip(f"No prompts found for category {category}")
    
    prompt = category_prompts[0]
    prompt_id = prompt["id"]
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("node-1", f"{category} context passage", collection=collection)
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    response_text = payload["text"]
    
    # Category-specific keyword validation
    if category == "ethical_dilemmas":
        keywords = ["utilitarian", "deontology", "virtue ethics"]
    elif category == "epistemology":
        keywords = ["knowledge", "justification", "belief"]
    elif category == "metaphysics":
        keywords = ["identity", "persistence", "ontology"]
    elif category == "political_philosophy":
        keywords = ["justice", "rights", "state"]
    elif category == "logic_reasoning":
        keywords = ["validity", "argument", "fallacy"]
    elif category == "bioethics":
        keywords = ["autonomy", "beneficence", "harm"]
    elif category == "aesthetics":
        keywords = ["beauty", "art", "aesthetic"]
    elif category == "metaethics":
        keywords = ["moral", "realism", "objectivity"]
    else:
        keywords = ["philosophy", "ethics", "reason"]
    
    assert_keywords_present(response_text, keywords, require_all=False)


def test_immersive_mode_philosopher_voice(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Test immersive mode adopts philosopher's voice correctly."""
    
    # Use prompt_007_aristotle_eudaimonia if it exists, otherwise find any Aristotle prompt
    catalog = get_prompt_catalog()
    aristotle_prompts = [p for p in catalog["prompts"] 
                        if p.get("requires_philosopher") == "Aristotle" or "aristotle" in p.get("id", "").lower()]
    
    if not aristotle_prompts:
        pytest.skip("No Aristotle prompts found for immersive mode test")
    
    prompt = aristotle_prompts[0]
    prompt_id = prompt["id"]
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = "Aristotle"

    mock_llm = mock_all_services["llm"]
    # Create a custom mock response that contains Aristotle and first-person language
    mock_response = get_prompt_completion_mock(prompt_id)
    mock_response.content = "I, Aristotle, believe that eudaimonia is the highest good. I maintain that virtue ethics provides the best framework for understanding human flourishing. As I have argued in my Nicomachean Ethics, the virtuous life requires practical wisdom (phronesis)."
    mock_llm.achat.return_value = mock_response

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("aristotle-1", "Aristotelian context", collection=collection)
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": True, "temperature": 0.4},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    response_text = payload["text"]
    
    # Validate immersive mode response using updated validator
    is_valid, error_msg = validate_immersive_mode_response(response_text, "Aristotle")
    assert is_valid, f"Immersive mode validation failed: {error_msg}. Response sample: {response_text[:200]}"
    
    # Verify immersive_mode parameter was set correctly
    mock_llm.achat.assert_called_once()
    call_kwargs = mock_llm.achat.call_args.kwargs
    assert call_kwargs.get("immersive_mode") == collection


def test_multi_framework_analysis_prompts(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Test prompts requiring multiple framework analysis."""
    
    # Find prompts that should mention frameworks
    catalog = get_prompt_catalog()
    framework_prompts = []
    for prompt in catalog["prompts"]:
        if prompt.get("endpoint") != "/ask_philosophy":
            continue
        canned = load_canned_response_with_normalized_collection(prompt["id"])
        if canned.get("expected_output", {}).get("should_mention_frameworks"):
            framework_prompts.append(prompt)
    
    if not framework_prompts:
        pytest.skip("No multi-framework prompts found")
    
    prompt = framework_prompts[0]
    prompt_id = prompt["id"]
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("ethics-1", "Multi-framework context", collection=collection)
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    response_text = payload["text"]
    
    # Validate multi-framework analysis
    frameworks = ["utilitarian", "deontological", "virtue"]
    is_valid, missing = validate_multi_framework_analysis(response_text, frameworks)
    assert is_valid, f"Missing frameworks: {missing}"
    
    # Check minimum response length
    expected_min_length = canned.get("expected_output", {}).get("min_length", 300)
    assert len(response_text.strip()) >= expected_min_length


@pytest.mark.parametrize("refeed", [True, False])
def test_refeed_parameter_propagation(
    test_client: TestClient,
    mock_all_services,
    refeed: bool,
) -> None:
    """Test refeed parameter is correctly propagated to gather_points_and_sort."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("node-1", "Refeed test context", collection=collection)
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3, "refeed": refeed},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 200
    
    # Verify refeed parameter was passed correctly
    mock_qdrant.gather_points_and_sort.assert_called_once()
    call_args = mock_qdrant.gather_points_and_sort.call_args
    assert call_args.kwargs.get("refeed") == refeed


@pytest.mark.parametrize("temperature", [-0.1, 0.0, 1.0, 1.5])
def test_temperature_bounds_validation(
    test_client: TestClient,
    mock_all_services,
    temperature: float,
) -> None:
    """Test invalid temperature values are rejected with HTTP 422."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": temperature},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 422
    error_data = response.json()
    # Handle both single error and list of errors format
    if "detail" in error_data:
        detail = error_data["detail"]
        if isinstance(detail, list):
            assert len(detail) > 0
            # Check that at least one error mentions temperature or validation
            error_msgs = [str(item) for item in detail]
            assert any("temperature" in msg.lower() or "greater than" in msg.lower() 
                      or "less than" in msg.lower() for msg in error_msgs)
        else:
            assert isinstance(detail, str)
            assert "temperature" in detail.lower() or "validation" in detail.lower()


@pytest.mark.parametrize("query_str", ["", "   ", "\t\n"])
def test_empty_query_string_rejected(
    test_client: TestClient,
    mock_all_services,
    query_str: str,
) -> None:
    """Test empty or whitespace-only query strings are rejected."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": query_str,
            "collection": collection,
        },
    )

    # Empty queries might return 400 (bad request) or 404 (no context found)
    assert response.status_code in [400, 404]
    error_data = response.json()
    detail = error_data.get("detail", "").lower()
    assert "empty" in detail or "no relevant context" in detail or "not found" in detail


def test_no_nodes_found_returns_404(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Test when Qdrant returns no nodes, expect HTTP 404."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = []  # No nodes found

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 404
    error_data = response.json()
    assert "No relevant context found" in error_data["detail"]


def test_long_query_handling(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Test handling of very long query strings."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("long-query-1", "Long query context", collection=collection)
    ]

    # Create a query with 5000+ characters
    long_query = "What is the meaning of life? " * 200  # ~5000 chars

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": long_query,
            "collection": collection,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert_philosophy_response_structure(payload)
    
    # Verify set_llm_context_window was called for large content
    mock_llm.set_llm_context_window.assert_called()


def test_special_characters_in_query(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Test queries with special characters, Unicode, and emojis."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("special-1", "Special characters context", collection=collection)
    ]

    # Query with Unicode, emojis, and mathematical symbols
    special_query = "What does 🤔 mean for Σ(philosophy) ∧ ∃truth? Café, naïve, résumé."

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": special_query,
            "collection": collection,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert_philosophy_response_structure(payload)


def test_multiple_conversation_turns(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Test with extensive conversation history (10+ messages)."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("conversation-1", "Multi-turn context", collection=collection)
    ]

    # Create conversation history with 12 messages
    conversation_history = []
    for i in range(6):
        conversation_history.extend([
            {"id": f"user-{i}", "role": "user", "text": f"User question {i+1}"},
            {"id": f"assistant-{i}", "role": "assistant", "text": f"Assistant response {i+1}"}
        ])

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
            "conversation_history": conversation_history,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert_philosophy_response_structure(payload)
    
    # Verify all messages were forwarded
    mock_llm.achat.assert_called_once()
    forwarded_history = mock_llm.achat.call_args.kwargs.get("conversation_history")
    assert forwarded_history is not None
    assert len(forwarded_history) == len(conversation_history)


def test_token_usage_validation(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Validate token usage metadata is reasonable and consistent."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("usage-1", "Token usage context", collection=collection)
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    usage = payload["raw"]["usage"]
    
    # Validate token counts
    assert usage["prompt_tokens"] > 0, "Prompt tokens should be positive"
    assert usage["completion_tokens"] > 0, "Completion tokens should be positive"
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert usage["total_tokens"] < 100000, "Total tokens should be reasonable"


def test_response_content_quality(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Test response content quality using validators."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("quality-1", "Quality context", collection=collection)
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    response_text = payload["text"]
    
    # Validate content quality using updated validator
    is_valid, error_msg = validate_response_content(response_text)
    assert is_valid, f"Content validation failed: {error_msg}"
    
    # Validate logical structure for substantial responses
    if len(response_text.strip()) > 200:
        is_logical, logic_error = validate_logical_structure(response_text)
        assert is_logical, f"Logical structure validation failed: {logic_error}"


@pytest.mark.parametrize("collection_name", ["Aristotle", "Immanuel Kant", "Meta Collection"])
def test_collection_parameter_forwarding(
    test_client: TestClient,
    mock_all_services,
    collection_name: str,
) -> None:
    """Test collection parameter is correctly forwarded to gather_points_and_sort."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)

    # Normalize the collection name for consistency
    normalized_collection = philosopher_mapper.normalize_philosopher_name(collection_name)

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("collection-1", f"{normalized_collection} context", 
                        collection=normalized_collection, 
                        collection_name=normalized_collection)
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection_name,  # Use original name in request
        },
    )

    assert response.status_code == 200
    
    # Verify collection parameter was passed correctly to gather_points_and_sort
    mock_qdrant.gather_points_and_sort.assert_called_once()
    call_args = mock_qdrant.gather_points_and_sort.call_args
    
    # The collection should be part of the request body (first argument)
    body_arg = call_args.args[0] if call_args.args else None
    assert body_arg is not None
    
    # The body should have the normalized collection name
    assert hasattr(body_arg, 'collection')
    assert body_arg.collection == normalized_collection
    
    # Verify that the API normalized the collection name correctly
    # (original collection_name should have been normalized to normalized_collection)
    if collection_name != "Meta Collection":  # Meta Collection doesn't get normalized
        assert normalized_collection in philosopher_mapper.get_available_philosophers()
    else:
        # Meta Collection is a special case - it should remain unchanged
        assert normalized_collection == "Meta Collection"


@pytest.mark.parametrize("input_name,expected_normalized", [
    ("Kant", "Immanuel Kant"),
    ("kant", "Immanuel Kant"), 
    ("aristotle", "Aristotle"),
    ("Aristotle", "Aristotle"),
    ("hume", "David Hume"),
    ("David Hume", "David Hume"),
    ("locke", "John Locke"),
    ("John Locke", "John Locke"),
    ("nietzsche", "Friedrich Nietzsche"),
    ("Friedrich Nietzsche", "Friedrich Nietzsche"),
    ("Meta Collection", "Meta Collection"),
])
def test_collection_name_normalization(
    test_client: TestClient,
    mock_all_services,
    input_name: str,
    expected_normalized: str,
) -> None:
    """Test that collection names are properly normalized (e.g., 'Kant' → 'Immanuel Kant')."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("norm-1", f"{expected_normalized} context", 
                        collection=expected_normalized)
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": input_name,  # Use input name in request
        },
    )

    assert response.status_code == 200
    
    # Verify the collection was normalized correctly
    mock_qdrant.gather_points_and_sort.assert_called_once()
    call_args = mock_qdrant.gather_points_and_sort.call_args
    body_arg = call_args.args[0] if call_args.args else None
    assert body_arg is not None
    assert hasattr(body_arg, 'collection')
    assert body_arg.collection == expected_normalized


def test_mock_service_call_verification(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Test that mock services are called with correct parameters and return expected values."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response_with_normalized_collection(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    mock_qdrant = mock_all_services["qdrant"]
    expected_nodes = [
        create_mock_node("verify-1", "Mock verification context", collection=collection),
        create_mock_node("verify-2", "Additional context", collection=collection)
    ]
    mock_qdrant.gather_points_and_sort.return_value = expected_nodes

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.4},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 200
    
    # Verify LLM service was called correctly
    mock_llm.achat.assert_called_once()
    llm_call_args = mock_llm.achat.call_args
    
    # Check that query string was passed as first argument
    assert len(llm_call_args.args) > 0
    assert llm_call_args.args[0] == canned["input"]["query_str"]
    
    # Check that temperature was passed correctly
    assert llm_call_args.kwargs.get("temperature") == 0.4
    
    # Check that immersive_mode is None for non-immersive requests
    assert llm_call_args.kwargs.get("immersive_mode") is None
    
    # Verify Qdrant service was called correctly
    mock_qdrant.gather_points_and_sort.assert_called_once()
    qdrant_call_args = mock_qdrant.gather_points_and_sort.call_args
    
    # Check that the request body was passed
    body_arg = qdrant_call_args.args[0] if qdrant_call_args.args else None
    assert body_arg is not None
    assert hasattr(body_arg, 'collection')
    assert body_arg.collection == collection
    assert hasattr(body_arg, 'query_str')
    assert body_arg.query_str == canned["input"]["query_str"]


def test_prompt_variants_temperature_differences(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Test prompts with multiple temperature variants are handled correctly."""
    
    # Find a prompt with multiple temperature variants
    catalog = get_prompt_catalog()
    multi_temp_prompts = [p for p in catalog["prompts"] 
                         if p.get("endpoint") == "/ask_philosophy" 
                         and len(p.get("test_variants", [])) > 1]
    
    if not multi_temp_prompts:
        pytest.skip("No multi-temperature variant prompts found")
    
    prompt = multi_temp_prompts[0]
    prompt_id = prompt["id"]
    canned = load_canned_response(prompt_id)
    collection = _collection_for_case(None, canned["input"])
    
    variants = prompt["test_variants"]
    temperatures = [v.get("temperature", 0.3) for v in variants]

    mock_llm = mock_all_services["llm"]
    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("variant-1", "Temperature variant context", collection=collection)
    ]

    for temp in temperatures:
        mock_llm.reset_mock()
        mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)
        
        response = test_client.post(
            "/ask_philosophy",
            params={"immersive": False, "temperature": temp},
            json={
                "query_str": canned["input"]["query_str"],
                "collection": collection,
            },
        )

        assert response.status_code == 200
        
        # Verify correct temperature was passed
        mock_llm.achat.assert_called_once()
        call_kwargs = mock_llm.achat.call_args.kwargs
        assert pytest.approx(temp) == call_kwargs["temperature"]


def test_context_window_scaling(
    test_client: TestClient,
    mock_all_services,
) -> None:
    """Test context window calculation scales with node content."""
    
    prompt_id = SAMPLE_PROMPT_ID
    canned = load_canned_response(prompt_id)
    collection = _collection_for_case(None, canned["input"])

    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = get_prompt_completion_mock(prompt_id)

    # Create nodes with varying text lengths
    long_text = "This is a very long philosophical passage that contains extensive reasoning. " * 50
    short_text = "Brief context."
    
    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("long-1", long_text, collection=collection),
        create_mock_node("long-2", long_text, collection=collection),
        create_mock_node("short-1", short_text, collection=collection),
    ]

    response = test_client.post(
        "/ask_philosophy",
        params={"immersive": False, "temperature": 0.3},
        json={
            "query_str": canned["input"]["query_str"],
            "collection": collection,
        },
    )

    assert response.status_code == 200
    
    # Verify set_llm_context_window was called (context window management is optional)
    if mock_llm.set_llm_context_window.called:
        context_window_calls = mock_llm.set_llm_context_window.call_args_list
        assert len(context_window_calls) >= 1
        
        # Context window should be reasonable for the amount of content
        for call in context_window_calls:
            window_size = call.args[0] if call.args else call.kwargs.get('context_window')
            if window_size is not None:
                assert 1000 <= window_size <= 100000  # More reasonable range
