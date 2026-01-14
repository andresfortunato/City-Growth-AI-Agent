"""
Fast HTS Classification Workflow - Variant V2: Categorical Confidence

Based on fast_workflow_combined.py with CATEGORICAL confidence levels.

Key change:
- REPLACED: Numeric confidence scores (0.0-1.0) with categorical levels (HIGH/MEDIUM/LOW)
- Reasoning: Prevents apples-to-oranges comparison between LLM confidence and ruling similarity scores
- Forces LLM to assess based on INFORMATION AVAILABILITY rather than guessing

Confidence levels:
- HIGH: All required information available for definitive classification
- MEDIUM: Sufficient information for candidate list, but some details missing
- LOW: Very little information, many assumptions required
"""

import os
import json
import time
import warnings
from typing import Optional

from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
from openai import OpenAI
from google import genai
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START, END
from sqlalchemy import create_engine, pool, text

warnings.filterwarnings('ignore', message='.*Did not recognize type.*vector.*')

# Always load from project root .env (not backend/.env) to ensure consistent API keys
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # For embeddings (database compatibility)
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

if not GEMINI_API_KEY:
    raise ValueError("Missing required environment variable: GEMINI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("Missing required environment variable: OPENAI_API_KEY (needed for embeddings)")

# Allow model override via environment variable or use default
MODEL_ID = os.getenv("MODEL_OVERRIDE", "google_genai:gemini-3-flash-preview")
MODEL = init_chat_model(MODEL_ID)

# A/B Evaluation: Disable rulings search for ablation study
# Set DISABLE_RULINGS=true to skip ruling retrieval and measure baseline performance
DISABLE_RULINGS = os.getenv("DISABLE_RULINGS", "false").lower() == "true"

# Verbose mode: Set VERBOSE=true to enable debug print statements
VERBOSE = os.getenv("VERBOSE", "false").lower() == "true"


def debug_print(*args, **kwargs):
    """Print only if VERBOSE mode is enabled."""
    if VERBOSE:
        print(*args, **kwargs)

# Hybrid search configuration
# Increased semantic weight to prioritize vector similarity over keyword matching
# This prevents long queries from diluting relevance and helps retrieve specialized
# rulings with domain-specific terminology (e.g., "batting jersey")
SEMANTIC_WEIGHT = 0.7  # 
KEYWORD_WEIGHT = 0.3   # 
HYBRID_SEARCH_LIMIT = 30

# Cached OpenAI client for embeddings (avoid recreating on each call)
# Note: Using OpenAI for embeddings to match database (generated with text-embedding-3-small)
# while Gemini is used for LLM calls
_OPENAI_CLIENT = None

def get_openai_client():
    """Get cached OpenAI client for embeddings."""
    global _OPENAI_CLIENT
    if _OPENAI_CLIENT is None:
        _OPENAI_CLIENT = OpenAI(api_key=OPENAI_API_KEY)
    return _OPENAI_CLIENT


# ============================================================================
# DATABASE CONNECTION
# ============================================================================

def get_raw_connection():
    if not all([DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME]):
        return None
    db_uri = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(
        db_uri,
        poolclass=pool.QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10, "options": "-c statement_timeout=60000"}
    )


# ============================================================================
# HYBRID SEARCH FUNCTIONS (HTS PRODUCTS)
# ============================================================================

def get_query_embedding(query_text: str) -> list[float]:
    """Generate embedding for query text using cached OpenAI client.

    Uses text-embedding-3-small to match the database embeddings.
    Database was populated with OpenAI embeddings, so queries must use the same model
    for valid similarity scores.
    """
    response = get_openai_client().embeddings.create(
        model="text-embedding-3-small",
        input=query_text,
        dimensions=1536
    )
    return response.data[0].embedding

# Removed but kept for reference
def hybrid_search_hts(conn, query_embedding: list[float], query_text: str,
                      subheading_codes: list[str], limit: int = HYBRID_SEARCH_LIMIT) -> list:
    """
    Hybrid search combining semantic similarity and keyword matching.
    Returns HTS products ranked by combined score.
    """
    placeholders = ", ".join([f"'{c}'" for c in subheading_codes])
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    # Escape single quotes in query_text for SQL
    safe_query_text = query_text.replace("'", "''")

    # Embed the vector directly in SQL to avoid ::vector parameter binding issues
    result = conn.execute(text(f"""
        WITH semantic_scores AS (
            SELECT id, 1 - (embedding <=> '{embedding_str}'::vector) AS semantic_score
            FROM hts_products
            WHERE subheading_code IN ({placeholders})
              AND embedding IS NOT NULL
        ),
        keyword_scores AS (
            SELECT id,
                ts_rank(to_tsvector('english', search_text),
                        plainto_tsquery('english', '{safe_query_text}')) AS keyword_score
            FROM hts_products
            WHERE subheading_code IN ({placeholders})
        )
        SELECT
            p.chapter_code, p.chapter_desc,
            p.heading_code, p.heading_desc,
            p.subheading_code, p.subheading_desc,
            p.subheading_8_code, p.subheading_8_desc_explained,
            p.statistical_rep_number, p.statistical_rep_desc_explained,
            p.unit, p.general_duty_rate, p.special_duty_rate, p.usmca_eligible,
            COALESCE(s.semantic_score, 0) AS semantic_score,
            COALESCE(k.keyword_score, 0) AS keyword_score,
            ({SEMANTIC_WEIGHT} * COALESCE(s.semantic_score, 0) +
             {KEYWORD_WEIGHT} * COALESCE(k.keyword_score, 0)) AS hybrid_score
        FROM hts_products p
        LEFT JOIN semantic_scores s ON p.id = s.id
        LEFT JOIN keyword_scores k ON p.id = k.id
        WHERE p.subheading_code IN ({placeholders})
        ORDER BY hybrid_score DESC
        LIMIT {limit}
    """))

    return result.fetchall()


def check_embeddings_available(conn) -> bool:
    """Check if embeddings have been generated for hts_products."""
    result = conn.execute(text(
        "SELECT COUNT(*) FROM hts_products WHERE embedding IS NOT NULL LIMIT 1"
    ))
    return result.scalar() > 0


# ============================================================================
# RULING CODE VALIDATION
# ============================================================================

def check_ruling_code_validity(conn, tariff_code: str) -> dict:
    """
    Validate ruling tariff code at the EXACT level cited in the ruling.

    This function checks whether a ruling's cited tariff code still exists in
    the current HTS schedule. It validates at the precise level (6, 8, or 10 digits)
    that appears in the ruling, not just the parent subheading.

    Strategy:
    - 6-digit (XXXX.XX): Check subheading_code in hts_products
    - 8-digit (XXXX.XX.XX): Check subheading_8_code in hts_products
    - 10-digit (XXXX.XX.XX.XX): Check statistical_rep_number in hts_products

    Historical codes are identified when the exact code no longer exists but its
    parent 6-digit subheading still does (indicating the code was split, merged,
    or renumbered rather than eliminated entirely).

    Args:
        conn: Database connection
        tariff_code: Code from ruling (e.g., "3506.91.00", "6211.33.00.10")

    Returns:
        {
            "exact_code_valid": bool,      # Does exact ruling code exist in current HTS?
            "subheading_valid": bool,      # Does parent 6-digit subheading exist?
            "code_level": str,             # "6-digit", "8-digit", "10-digit", or None
            "is_historical": bool,         # True if subheading exists but exact code doesn't
            "validation_message": str      # Concise message for LLM prompt
        }

    Examples:
        >>> check_ruling_code_validity(conn, "3506.91.00")
        {
            "exact_code_valid": False,
            "subheading_valid": True,
            "code_level": "8-digit",
            "is_historical": True,
            "validation_message": "Historical code - see current 3506.91.xx codes below"
        }

        >>> check_ruling_code_validity(conn, "6211.33.00")
        {
            "exact_code_valid": True,
            "subheading_valid": True,
            "code_level": "8-digit",
            "is_historical": False,
            "validation_message": "Valid current code"
        }
    """
    if not tariff_code:
        return {
            "exact_code_valid": False,
            "subheading_valid": False,
            "code_level": None,
            "is_historical": False,
            "validation_message": "No tariff code provided"
        }

    # 1. Clean and validate format
    clean_code = tariff_code.replace(".", "").replace(" ", "")

    # Format validation - MUST be numeric (prevents SQL injection and invalid codes)
    if not clean_code.isdigit():
        return {
            "exact_code_valid": False,
            "subheading_valid": False,
            "code_level": None,
            "is_historical": False,
            "validation_message": "Invalid format (non-numeric)"
        }

    # 2. Determine code level based on length
    code_length = len(clean_code)

    if code_length >= 10:
        code_level = "10-digit"
        db_column = "statistical_rep_number"
        code_to_check = clean_code[:10]
    elif code_length >= 8:
        code_level = "8-digit"
        db_column = "subheading_8_code"
        code_to_check = clean_code[:8]
    elif code_length >= 6:
        code_level = "6-digit"
        db_column = "subheading_code"
        code_to_check = clean_code[:6]
    else:
        # Invalid length (less than 6 digits)
        return {
            "exact_code_valid": False,
            "subheading_valid": False,
            "code_level": None,
            "is_historical": False,
            "validation_message": "Invalid length (< 6 digits)"
        }

    try:
        # 3. Check if exact code exists at specified level
        result = conn.execute(text(f"""
            SELECT COUNT(*) FROM hts_products
            WHERE {db_column} = '{code_to_check}'
        """))
        exact_exists = result.scalar() > 0

        # 4. Check if parent 6-digit subheading exists
        subheading_6 = clean_code[:6]
        result = conn.execute(text(f"""
            SELECT COUNT(*) FROM hts_products
            WHERE subheading_code = '{subheading_6}'
        """))
        subheading_exists = result.scalar() > 0

        # 5. Determine if historical and create message
        is_historical = (not exact_exists and subheading_exists)

        if exact_exists:
            validation_message = "Valid current code"
        elif is_historical:
            # Format subheading for display (XXXX.XX format)
            formatted_subheading = f"{subheading_6[:4]}.{subheading_6[4:]}"
            validation_message = f"Historical code - see current {formatted_subheading}.xx codes below"
        elif not subheading_exists:
            validation_message = "Subheading eliminated - reference only"
        else:
            validation_message = "Code not found"

        return {
            "exact_code_valid": exact_exists,
            "subheading_valid": subheading_exists,
            "code_level": code_level,
            "is_historical": is_historical,
            "validation_message": validation_message
        }

    except Exception as e:
        # On error, assume code may be historical (safe assumption)
        return {
            "exact_code_valid": False,
            "subheading_valid": False,
            "code_level": code_level,
            "is_historical": False,
            "validation_message": f"Validation error: {str(e)}"
        }


# ============================================================================
# RULINGS SEARCH FUNCTIONS
# ============================================================================

def hybrid_search_rulings(
    conn,
    query_embedding: list[float],
    query_text: str,
    limit: int = 10
) -> list[dict]:
    """
    Hybrid semantic + keyword search on rulings_search table.

    Similar to hybrid_search_hts but adapted for rulings schema.
    Combines cosine similarity on embeddings with full-text search.

    Args:
        conn: Database connection
        query_embedding: Query vector (1536 dimensions)
        query_text: Query string for keyword matching
        limit: Maximum results to return

    Returns:
        List of ruling dicts with scores and metadata
    """
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    safe_query_text = query_text.replace("'", "''")

    # Set HNSW ef_search for better recall (default 40 is too low)
    # ef_search=200 ensures high-quality matches aren't filtered out by the index
    conn.execute(text("SET LOCAL hnsw.ef_search = 200"))

    # Candidate-first pattern: Use HNSW index to get top 100 candidates,
    # then apply quality threshold (0.3) only to those candidates.
    # This prevents full table scan while maintaining quality standards.
    result = conn.execute(text(f"""
        WITH candidate_set AS (
            SELECT
                id,
                ruling_number,
                subject,
                product_description,
                primary_tariff,
                tariff_codes,
                ruling_date,
                1 - (embedding <=> '{embedding_str}'::vector) AS semantic_score
            FROM rulings_search
            WHERE embedding IS NOT NULL
              AND is_revoked = FALSE
              AND product_description IS NOT NULL
            ORDER BY embedding <=> '{embedding_str}'::vector  -- Triggers HNSW index
            LIMIT 100  -- Candidate buffer for thresholding
        ),
        keyword_scores AS (
            SELECT
                id,
                ts_rank(
                    to_tsvector('english', search_text),
                    plainto_tsquery('english', '{safe_query_text}')
                ) AS keyword_score
            FROM rulings_search
            WHERE id IN (SELECT id FROM candidate_set)
        )
        SELECT
            s.ruling_number,
            s.subject,
            s.product_description,
            s.primary_tariff,
            s.tariff_codes,
            s.ruling_date,
            s.semantic_score,
            COALESCE(k.keyword_score, 0) AS keyword_score,
            ({SEMANTIC_WEIGHT} * s.semantic_score +
             {KEYWORD_WEIGHT} * COALESCE(k.keyword_score, 0)) AS hybrid_score
        FROM candidate_set s
        LEFT JOIN keyword_scores k ON s.id = k.id
        WHERE s.semantic_score > 0.25  -- Lowered from 0.3 to improve recall
        ORDER BY hybrid_score DESC
        LIMIT {limit}
    """))

    rows = result.fetchall()

    return [
        {
            "ruling_number": row[0],
            "subject": row[1],
            "product_description": row[2][:500] if row[2] else None,
            "primary_tariff": row[3],
            "tariff_codes": row[4],
            "ruling_date": str(row[5]) if row[5] else None,
            "semantic_score": float(row[6]),
            "keyword_score": float(row[7]),
            "hybrid_score": float(row[8]),
            "match_type": "semantic"
        }
        for row in rows
    ]


def search_rulings_by_subheading(
    conn,
    subheading_codes: list[str],
    limit: int = 10
) -> list[dict]:
    """
    Search rulings by matching 6-digit subheading codes.

    This finds rulings that were classified to the same subheadings
    as our current candidates - strong precedent evidence.

    Args:
        conn: Database connection
        subheading_codes: List of 6-digit codes in "XXXX.XX" format
        limit: Maximum results

    Returns:
        List of ruling dicts
    """
    if not subheading_codes:
        return []

    # SQL-safe list of quoted codes
    subheadings_str = ", ".join([f"'{code}'" for code in subheading_codes])

    result = conn.execute(text(f"""
        SELECT
            ruling_number,
            subject,
            product_description,
            primary_tariff,
            tariff_codes,
            ruling_date
        FROM rulings_search
        WHERE subheading_6 IN ({subheadings_str})
          AND is_revoked = FALSE
          AND product_description IS NOT NULL
        ORDER BY ruling_date DESC
        LIMIT {limit}
    """))

    rows = result.fetchall()

    return [
        {
            "ruling_number": row[0],
            "subject": row[1],
            "product_description": row[2][:500] if row[2] else None,
            "primary_tariff": row[3],
            "tariff_codes": row[4],
            "ruling_date": str(row[5]) if row[5] else None,
            "semantic_score": 0.0,
            "keyword_score": 0.0,
            "hybrid_score": 0.6,
            "match_type": "code"
        }
        for row in rows
    ]


def merge_ruling_results(
    semantic_results: list[dict],
    code_results: list[dict],
    max_results: int = 5
) -> list[dict]:
    """
    Merge semantic and code-based search results with deduplication.

    Strategy:
    - Prioritize semantic matches (higher quality)
    - Add unique code matches (valuable for exact precedents)
    - Deduplicate by ruling_number
    - Sort by hybrid_score descending
    - Limit to max_results

    Args:
        semantic_results: Results from hybrid_search_rulings
        code_results: Results from search_rulings_by_subheading
        max_results: Maximum rulings to return

    Returns:
        Merged and deduplicated list
    """
    seen_numbers = set()
    merged = []

    # Add semantic results first (higher priority)
    for result in semantic_results:
        if result["ruling_number"] not in seen_numbers:
            merged.append(result)
            seen_numbers.add(result["ruling_number"])

    # Add unique code matches
    for result in code_results:
        if result["ruling_number"] not in seen_numbers:
            merged.append(result)
            seen_numbers.add(result["ruling_number"])

    # Sort by hybrid score descending
    merged.sort(key=lambda x: x["hybrid_score"], reverse=True)

    return merged[:max_results]


def format_ruling_results(rulings: list[dict], conn=None) -> str:
    """
    Format rulings for inclusion in LLM classification prompt.

    Creates a human-readable section showing relevant CBP precedents
    with ruling numbers, products, and tariff codes.

    **Enhanced validation**: Uses exact-level code validation (6/8/10 digits)
    and provides instructive flags for historical codes.

    Args:
        rulings: List of ruling dicts
        conn: Optional database connection for historical code checking

    Returns:
        Formatted string for prompt injection
    """
    if not rulings:
        return "No relevant rulings found."

    lines = []
    for i, ruling in enumerate(rulings, 1):
        product_desc = ruling.get('product_description', 'N/A')
        if product_desc and len(product_desc) > 300:
            product_desc = product_desc[:300] + "..."

        # Show ALL tariff codes from the ruling, not just primary
        tariff_codes = ruling.get('tariff_codes') or []  # Handle None explicitly
        primary_tariff = ruling.get('primary_tariff') or 'N/A'

        # Format tariff display - show all codes for multi-code rulings
        if tariff_codes and len(tariff_codes) > 1:
            # Filter out Chapter 98-99 codes (temporary codes not in HTS database yet)
            product_codes = [c for c in tariff_codes if not c.startswith(('98', '99'))]
            if len(product_codes) > 1:
                tariff_display = f"ALL CODES: {', '.join(product_codes)}"
            elif product_codes:
                tariff_display = product_codes[0]
            else:
                tariff_display = primary_tariff
        else:
            tariff_display = primary_tariff

        # Enhanced validation using new function (check primary tariff)
        historical_note = ""
        if conn and primary_tariff != 'N/A':
            validation = check_ruling_code_validity(conn, primary_tariff)

            if validation["is_historical"]:
                # Extract subheading for display
                clean_code = primary_tariff.replace(".", "").replace(" ", "")
                formatted_subheading = f"{clean_code[:4]}.{clean_code[4:6]}" if len(clean_code) >= 6 else primary_tariff
                
                # Historical code note - STRONGER warning with actionable guidance
                historical_note = f"""
  ⚠️ HISTORICAL CODE WARNING ⚠️
  The ruling cites {primary_tariff} which NO LONGER EXISTS in current HTS.

  ACTION REQUIRED: Find the CURRENT equivalent code under subheading {formatted_subheading}.xx
  The ruling's classification LOGIC still applies - it IS the binding precedent for this product type.

  DO NOT use {primary_tariff} in your output - it will fail validation.
  MUST select a currently valid code from the "Available HTS Codes" list."""
            elif not validation["exact_code_valid"] and not validation["subheading_valid"]:
                # Entire subheading eliminated
                historical_note = f"""
  ⚠️  {validation['validation_message']}
  → This ruling is reference-only for understanding product characteristics"""

        lines.append(f"""
Ruling #{i}: {ruling['ruling_number']}
Subject: {ruling['subject']}
Tariff: {tariff_display}{historical_note}
Product: {product_desc}
Match: {ruling.get('match_type', 'unknown')} (score: {ruling.get('hybrid_score', 0):.2f})
{'─' * 70}""")

    return "\n".join(lines)


def extract_ruling_subheadings(rulings: list[dict]) -> list[dict]:
    """
    Extract 6-digit subheadings from ruling tariff codes.

    Uses the primary_tariff field from rulings_search table to extract
    XXXX.XX format subheadings (e.g., "6211.33", "8710.00").

    Args:
        rulings: List of ruling dicts from hybrid_search_rulings

    Returns:
        List of subheading candidate dicts with:
        - subheading: "XXXX.XX" format
        - label: "From ruling {ruling_number}"
        - score: ruling's hybrid_score * 0.8 (dampened)
        - source: "ruling"
        - ruling_number: for traceability
    """
    subheadings = {}

    for ruling in rulings:
        # Use primary_tariff to extract subheading (format: XXXX.XX.XXXX)
        tariff = ruling.get('primary_tariff', '')
        if not tariff:
            continue

        # Extract first 7 chars to get XXXX.XX format
        # Example: "6211.33.00" -> "6211.33"
        parts = tariff.split('.')
        if len(parts) >= 2:
            subheading = f"{parts[0]}.{parts[1]}"

            # Validate format (should be like "6211.33")
            if len(subheading) != 7 or not subheading[:4].isdigit() or not subheading[5:7].isdigit():
                continue

            # Score based on ruling match quality
            ruling_score = ruling.get('hybrid_score', 0.5)

            # Only keep highest-scoring version of each subheading
            if subheading not in subheadings or subheadings[subheading]['score'] < ruling_score:
                subheadings[subheading] = {
                    "subheading": subheading,
                    "label": f"From ruling {ruling['ruling_number']}",
                    "score": ruling_score,
                    "source": "ruling",
                    "ruling_number": ruling['ruling_number']
                }

    return list(subheadings.values())


def merge_subheading_candidates(
    llm_candidates: list[dict],
    ruling_candidates: list[dict],
    max_candidates: int = 10
) -> list[dict]:
    """
    Merge LLM and ruling-derived subheading candidates with deduplication.

    **FIXED STRATEGY (Phase 0 Fix #1):**
    - **MAX-SCORE-WINS**: If same code appears in multiple sources, keep highest score
    - **SOURCE-WEIGHTED RANKING**: Rulings > LLM > Semantic for tie-breaking
    - Total limited to max_candidates to control latency
    - Each candidate tagged with source for traceability

    Args:
        llm_candidates: From narrow_and_select node or merge_initial_candidates
        ruling_candidates: From extract_ruling_subheadings
        max_candidates: Maximum total candidates (default 10)

    Returns:
        Merged list sorted by weighted score descending
    """
    merged = {}

    # Source priority weights for tie-breaking
    SOURCE_PRIORITY = {
        'ruling': 3,    # Highest priority - direct CBP precedent
        'llm': 2       # Medium priority - saw full context
#        'semantic': 1   # Lowest priority - vector similarity only
    }

    # Process ALL candidates with max-score-wins logic
    all_candidates = [
        *[{**c, 'source': c.get('source', 'llm')} for c in llm_candidates],
        *[{**c, 'source': 'ruling'} for c in ruling_candidates]
    ]

    for cand in all_candidates:
        code = cand.get('subheading', '').replace('.', '').replace(' ', '')
        if len(code) != 6:
            continue

        source = cand.get('source', 'llm')
        score = cand.get('score', 0)

        # No score boosting - let scores from different sources compete equally
        weighted_score = score

        if code in merged:
            # MAX-SCORE-WINS: Keep candidate with higher weighted score
            existing_score = merged[code].get('weighted_score', 0)
            if weighted_score > existing_score:
                merged[code] = {
                    **cand,
                    'weighted_score': weighted_score,
                    'original_score': score
                }
            elif weighted_score == existing_score:
                # Tie-breaker: prefer higher priority source
                existing_priority = SOURCE_PRIORITY.get(merged[code].get('source'), 0)
                new_priority = SOURCE_PRIORITY.get(source, 0)
                if new_priority > existing_priority:
                    merged[code] = {
                        **cand,
                        'weighted_score': weighted_score,
                        'original_score': score
                    }
        else:
            # First occurrence of this code
            merged[code] = {
                **cand,
                'weighted_score': weighted_score,
                'original_score': score
            }

    # Sort by weighted score descending, then by source priority
    sorted_candidates = sorted(
        merged.values(),
        key=lambda x: (
            x.get('weighted_score', 0),
            SOURCE_PRIORITY.get(x.get('source'), 0)
        ),
        reverse=True
    )

    # Limit to max_candidates
    return sorted_candidates[:max_candidates]


# ============================================================================
# STATE DEFINITION
# ============================================================================

class FastState(TypedDict):
    original_input: str
    language: str
    image_url: Optional[str]
    user_instructions: Optional[str]
    normalized_product: str
    materials: str
    primary_use: str
    chapter_candidates: list[dict]
    heading_candidates: list[dict]
    subheading_candidates: list[dict]
    initial_confidence: float
    chapter_summary: str
    chapter_rules: str  # Dynamic chapter-specific classification rules
    detailed_candidates: list[dict]
    confidence: float
    reasoning: str
    final_codes: list[str]
    relevant_rulings: list[dict]  # CBP ruling precedents
    ruling_subheadings: list[dict]    # Extracted from rulings
    multi_product_flag: bool  # Multi-product detection
    num_distinct_products: int  # Number of distinct products


# ============================================================================
# NODE 1: NARROW AND SELECT (MERGED)
# ============================================================================

def narrow_and_select(state: FastState) -> dict:
    """
    Merged node: Analyzes product and identifies chapter/heading/subheading candidates
    in a SINGLE LLM call. Previously this was 2 separate nodes.
    """
    model = MODEL
    original_input = state.get("original_input", "")
    image_url = state.get("image_url")
    user_instructions = state.get("user_instructions", "")

    # Format broker instructions for injection into user message
    instruction_block = ""
    if user_instructions:
        instruction_block = (
            f"\n\n--- BROKER INSTRUCTIONS ---\n"
            f"Apply the following specific classification rules or preferences:\n"
            f"{user_instructions}\n"
            f"---------------------------"
        )

    system_prompt = """You are an expert HTS (Harmonized Tariff Schedule) classifier.

TASK: Analyze the product and provide classification candidates at ALL levels:
1. Chapters (2-digit) - 1 to 3 candidates
2. Headings (4-digit) - 1 to 5 candidates
3. Subheadings (6-digit) - 1 to 5 candidates

RULES:
- Base your analysis on the product description and image (if provided)
- Subheadings MUST be valid 6-digit codes derived from your heading candidates
- Format subheadings as "XXXX.XX" (e.g., "6201.40")
- Return "unknown" for materials/use if not determinable
- Provide a categorical confidence score for the classification: HIGH (all info available), MEDIUM (sufficient info), LOW (very little info)

OUTPUT: JSON with chapters, headings, and subheadings."""

    if image_url:
        user_content = [
            {"type": "text", "text": f"Product: {original_input}{instruction_block}\n\nClassify this product."},
            {"type": "image_url", "image_url": {"url": image_url}}
        ]
    else:
        user_content = f"Product: {original_input}{instruction_block}\n\nClassify this product."

    class ChapterCandidate(BaseModel):
        chapter: int = Field(description="2-digit chapter code")
        label: str
        score: float = Field(ge=0.0, le=1.0)

    class HeadingCandidate(BaseModel):
        heading: str = Field(description="4-digit heading code")
        label: str
        score: float = Field(ge=0.0, le=1.0)

    class SubheadingCandidate(BaseModel):
        subheading: str = Field(description="6-digit subheading in format XXXX.XX")
        label: str
        score: float = Field(ge=0.0, le=1.0)

    class NarrowAndSelectOutput(BaseModel):
        normalized_product: str = Field(description="Concise product name, 1-3 words")
        materials: str
        primary_use: str
        chapter_candidates: list[ChapterCandidate] = Field(max_length=3)
        heading_candidates: list[HeadingCandidate] = Field(max_length=5)
        subheading_candidates: list[SubheadingCandidate] = Field(max_length=5)
        confidence: str = Field(
            description="Categorical confidence: HIGH (all info available), MEDIUM (sufficient info), LOW (very little info)",
            pattern="^(HIGH|MEDIUM|LOW)$"
        )

    structured_model = model.with_structured_output(NarrowAndSelectOutput)

    response = structured_model.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ])

    debug_print(f"  [narrow_and_select] Chapters: {len(response.chapter_candidates)}, "
          f"Headings: {len(response.heading_candidates)}, "
          f"Subheadings: {len(response.subheading_candidates)}")

    return {
        "normalized_product": response.normalized_product,
        "materials": response.materials,
        "primary_use": response.primary_use,
        "chapter_candidates": [
            {"chapter": c.chapter, "label": c.label, "score": c.score}
            for c in response.chapter_candidates
        ],
        "heading_candidates": [
            {"heading": h.heading, "label": h.label, "score": h.score}
            for h in response.heading_candidates
        ],
        "subheading_candidates": [
            {"subheading": s.subheading, "label": s.label, "score": s.score}
            for s in response.subheading_candidates
        ],
        "initial_confidence": response.confidence
    }


# ============================================================================

# ============================================================================
# REMOVED: semantic_subheading_search and merge_initial_candidates
# This variant (D) tests workflow without semantic search
# ============================================================================

# NODE 1.5: VALIDATE SUBHEADINGS (ANTI-HALLUCINATION)
# ============================================================================

def validate_subheadings(state: FastState) -> dict:
    """
    Validates LLM-generated subheadings against the database.

    Anti-hallucination pattern:
    1. Check which subheadings actually exist in hts_products
    2. If any are invalid, query for correct subheadings under the identified headings
    3. Return only validated subheading candidates

    This adds ~100-200ms but prevents cascading failures from hallucinated codes.
    """
    engine = get_raw_connection()

    if engine is None:
        debug_print("  [validate_subheadings] Database not configured, skipping validation")
        return {}  # Pass through unchanged

    subheading_candidates = state.get("subheading_candidates", [])
    heading_candidates = state.get("heading_candidates", [])

    if not subheading_candidates:
        debug_print("  [validate_subheadings] No subheadings to validate")
        return {}

    # Extract codes for validation
    llm_codes = []
    for s in subheading_candidates:
        code = s.get("subheading", "").replace(".", "").replace(" ", "")
        if len(code) == 6:
            llm_codes.append(code)

    if not llm_codes:
        debug_print("  [validate_subheadings] No valid 6-digit codes to validate")
        return {}

    try:
        with engine.connect() as conn:
            # Step 1: Check which LLM-generated subheadings exist in DB
            codes_str = ", ".join([f"'{c}'" for c in llm_codes])
            result = conn.execute(text(f"""
                SELECT DISTINCT subheading_code
                FROM hts_products
                WHERE subheading_code IN ({codes_str})
            """))
            valid_codes = {str(row[0]).replace(".", "") for row in result.fetchall()}

            # Count valid vs invalid
            invalid_count = len(llm_codes) - len(valid_codes)

            if invalid_count == 0:
                debug_print(f"  [validate_subheadings] ✅ All {len(llm_codes)} subheadings validated")
                return {}  # All good, no changes needed

            debug_print(f"  [validate_subheadings] ⚠️ {invalid_count}/{len(llm_codes)} subheadings invalid")

            # Step 2: Keep valid ones from LLM output
            validated_candidates = [
                s for s in subheading_candidates
                if s.get("subheading", "").replace(".", "").replace(" ", "") in valid_codes
            ]

            # Step 3: If we lost too many, query DB for alternatives under the headings
            if len(validated_candidates) < 2 and heading_candidates:
                heading_codes = [h.get("heading", "").replace(".", "") for h in heading_candidates]
                headings_str = ", ".join([f"'{h}'" for h in heading_codes if len(h) == 4])

                if headings_str:
                    result = conn.execute(text(f"""
                        SELECT DISTINCT subheading_code, subheading_desc
                        FROM hts_products
                        WHERE heading_code IN ({headings_str})
                        ORDER BY subheading_code
                        LIMIT 10
                    """))

                    db_subheadings = result.fetchall()

                    # Add DB subheadings as fallback candidates
                    for row in db_subheadings:
                        code = str(row[0]).replace(".", "") if row[0] else ""
                        if code and code not in valid_codes:
                            validated_candidates.append({
                                "subheading": f"{code[:4]}.{code[4:]}",
                                "label": row[1] if row[1] else "From database",
                                "score": 0.5  # Lower confidence for DB-sourced
                            })

                    debug_print(f"  [validate_subheadings] 📥 Added {len(db_subheadings)} subheadings from DB")

            debug_print(f"  [validate_subheadings] Final: {len(validated_candidates)} validated subheadings")

            return {"subheading_candidates": validated_candidates}

    except Exception as e:
        debug_print(f"  [validate_subheadings] Error: {e}")
        import traceback
        traceback.print_exc()
        return {}  # On error, pass through unchanged
    finally:
        engine.dispose()


# ============================================================================
# NODE 2: FETCH CHAPTER SUMMARY AND RULES (NO LLM - Database Only)
# ============================================================================

def fetch_chapter_summary(state: FastState) -> dict:
    """
    Fetch pre-computed chapter summary AND chapter-specific classification rules.
    
    The rules are dynamically loaded based on detected chapter candidates,
    reducing token waste by only including relevant rules (e.g., footwear rules
    only when Chapter 64 is a candidate).
    
    NO LLM CALL - pure database lookups.
    """
    engine = get_raw_connection()

    if engine is None:
        debug_print("  [fetch_chapter_summary] Database not configured")
        return {"chapter_summary": "Database not configured", "chapter_rules": ""}

    chapter_candidates = state.get("chapter_candidates", [])
    if not chapter_candidates:
        return {"chapter_summary": "No chapter candidates", "chapter_rules": ""}

    top_confidence = max(c["score"] for c in chapter_candidates)
    if top_confidence > 0.9:
        chapters_to_fetch = [chapter_candidates[0]["chapter"]]
    else:
        chapters_to_fetch = [c["chapter"] for c in chapter_candidates[:2]]

    chapter_codes = [str(ch).zfill(2) for ch in chapters_to_fetch]

    try:
        with engine.connect() as conn:
            placeholders = ", ".join([f"'{c}'" for c in chapter_codes])
            
            # Fetch chapter summaries (existing behavior)
            result = conn.execute(text(f"""
                SELECT DISTINCT chapter_code, chapter_summary, chapter_total_notes
                FROM chapter_notes
                WHERE chapter_code IN ({placeholders})
                  AND chapter_summary IS NOT NULL
            """))

            rows = result.fetchall()

            summaries = []
            if rows:
                for row in rows:
                    chapter_code, summary, note_count = row
                    summaries.append(f"### Chapter {chapter_code} ({note_count} notes)\n{summary}")
            
            combined_summary = "\n\n".join(summaries) if summaries else "No chapter summaries available"
            
            # Fetch chapter-specific classification rules (NEW)
            rules_text = ""
            try:
                rules_result = conn.execute(text(f"""
                    SELECT chapter_code, rules_text
                    FROM chapter_classification_rules
                    WHERE chapter_code IN ({placeholders})
                    ORDER BY priority DESC
                """))
                
                rules_rows = rules_result.fetchall()
                
                if rules_rows:
                    rules_parts = [row[1] for row in rules_rows if row[1]]
                    rules_text = "\n\n".join(rules_parts)
                    rule_chapters = [row[0] for row in rules_rows]
                    debug_print(f"  [fetch_chapter_summary] Loaded rules for chapters: {rule_chapters}")
            except Exception as rules_error:
                # Table might not exist yet - gracefully degrade
                debug_print(f"  [fetch_chapter_summary] Rules table not available: {rules_error}")
                rules_text = ""
            
            debug_print(f"  [fetch_chapter_summary] Fetched summaries for chapters: {chapter_codes}")

            return {
                "chapter_summary": combined_summary,
                "chapter_rules": rules_text
            }

    except Exception as e:
        debug_print(f"  [fetch_chapter_summary] Error: {e}")
        return {
            "chapter_summary": f"Error fetching summary: {str(e)}",
            "chapter_rules": ""
        }
    finally:
        engine.dispose()


# ============================================================================
# NODE 2.5: SEARCH RULINGS (NEW)
# ============================================================================

def search_rulings(state: FastState) -> dict:
    """
    Search rulings database for relevant CBP classification precedents.

    IMPROVED: Also extracts subheading codes from found rulings to expand
    the candidate list beyond initial LLM predictions.

    Two-pronged search strategy:
    1. Semantic search: Find rulings with similar product descriptions
    2. Code-based search: Find rulings classified to same subheadings

    Results are merged, deduplicated, and subheadings extracted.

    Returns:
        - relevant_rulings: Top 5 rulings for LLM context
        - ruling_subheadings: Subheading codes extracted from rulings
    """
    # A/B Eval: Skip rulings search when disabled
    if DISABLE_RULINGS:
        debug_print("  [search_rulings] DISABLED via DISABLE_RULINGS env var (ablation mode)")
        return {"relevant_rulings": [], "ruling_subheadings": []}

    start = time.time()
    engine = get_raw_connection()

    if engine is None:
        debug_print("  [search_rulings] Database not configured")
        return {"relevant_rulings": [], "ruling_subheadings": []}

    # Use original_input for semantic search (preserves user vocabulary)
    original_input = state.get('original_input', '')

    if original_input:
        query_text = original_input
        debug_print(f"  [search_rulings] Using original_input ({len(query_text)} chars)")
    else:
        normalized_product = state.get('normalized_product', '')
        materials = state.get('materials', '')
        primary_use = state.get('primary_use', '')
        query_text = f"{normalized_product} {materials} {primary_use}".strip()
        debug_print(f"  [search_rulings] Using LLM summary ({len(query_text)} chars)")

    if not query_text:
        debug_print("  [search_rulings] No query text available")
        return {"relevant_rulings": [], "ruling_subheadings": []}

    # Extract subheading candidates for code-based search (optional, as tiebreaker)
    subheading_candidates = state.get("subheading_candidates", [])
    subheading_codes = []
    for s in subheading_candidates:
        code = s.get("subheading", "").replace(".", "").replace(" ", "")
        if len(code) == 6:
            subheading_codes.append(f"{code[:4]}.{code[4:]}")

    try:
        # Generate query embedding for semantic search
        debug_print(f"  [search_rulings] Query preview: {query_text[:80]}...")
        query_embedding = get_query_embedding(query_text)

        with engine.connect() as conn:
            # Strategy 1: Semantic + keyword hybrid search (PRIMARY)
            # Increased limit from 10 to 20 to improve ground truth ruling retrieval
            semantic_results = hybrid_search_rulings(
                conn,
                query_embedding,
                query_text,
                limit=20
            )

            if semantic_results:
                top = semantic_results[0]
                debug_print(f"  [search_rulings] Top semantic: {top['ruling_number']} "
                      f"(score: {top.get('hybrid_score', 0):.3f})")

            # Strategy 2: Code-based search (SUPPLEMENTARY)
            # Adds rulings that match by code even if semantic search missed them
            code_results = []
            if subheading_codes:
                code_results = search_rulings_by_subheading(
                    conn,
                    subheading_codes,
                    limit=10  # Increased from 3 to improve coverage
                )

            # Merge: prioritize semantic, add code-based for diversity
            # Increased from 5 to 10 rulings to give LLM more precedent options
            combined = merge_ruling_results(
                semantic_results,
                code_results[:3],  # Increased from 1 to 3 code-based rulings
                max_results=10
            )

            # NEW: Extract subheadings from found rulings
            ruling_subheadings = extract_ruling_subheadings(combined)

            elapsed = (time.time() - start) * 1000
            debug_print(f"  [search_rulings] Found {len(combined)} rulings "
                  f"(semantic: {len(semantic_results)}, code: {len(code_results)}) "
                  f"in {elapsed:.0f}ms")

            # Log extracted subheadings
            if ruling_subheadings:
                ruling_codes = [r['subheading'] for r in ruling_subheadings]
                debug_print(f"  [search_rulings] Extracted subheadings from rulings: {ruling_codes}")

            # Log ruling numbers
            if combined:
                ruling_numbers = [r.get('ruling_number', 'N/A') for r in combined]
                debug_print(f"  [search_rulings] Ruling numbers: {', '.join(ruling_numbers)}")

            return {
                "relevant_rulings": combined,
                "ruling_subheadings": ruling_subheadings  # NEW
            }

    except Exception as e:
        debug_print(f"  [search_rulings] Error: {e}")
        import traceback
        traceback.print_exc()
        return {"relevant_rulings": [], "ruling_subheadings": []}
    finally:
        engine.dispose()


# ============================================================================
# NODE 2.6: MERGE FINAL CANDIDATES (ADD RULING SUBHEADINGS)
# ============================================================================

def merge_final_candidates(state: FastState) -> dict:
    """
    Add ruling-derived subheadings to the candidate list.

    At this point, subheading_candidates already contains merged LLM + semantic candidates
    (from merge_initial_candidates). This node adds any NEW subheadings suggested by rulings.

    This breaks the "locked-in" problem by allowing ruling-suggested
    codes to be searched even if LLM didn't predict them initially.

    Example fix for H078897:
    - LLM predicted: 6202.40 (women's coats)
    - Ruling suggests: 6211.33 (other garments, men's)
    - After merge: both are in candidate list
    - HTS search finds 6211.33.xx products
    - LLM can now select correct code
    """
    llm_candidates = state.get("subheading_candidates", [])
    ruling_candidates = state.get("ruling_subheadings", [])

    # Count originals
    llm_count = len(llm_candidates)
    ruling_count = len(ruling_candidates)

    # Merge with limit of 15 candidates (Phase 0 Fix #2: increased from 10)
    merged = merge_subheading_candidates(
        llm_candidates,
        ruling_candidates,
        max_candidates=15
    )

    # Count sources in merged result
    merged_llm = sum(1 for c in merged if c.get('source') in ['llm', 'semantic'])
    merged_ruling = sum(1 for c in merged if c.get('source') == 'ruling')

    debug_print(f"  [merge_final_candidates] Input: {llm_count} LLM, {ruling_count} ruling")
    debug_print(f"  [merge_final_candidates] Output: {len(merged)} total ({merged_llm} LLM, {merged_ruling} ruling)")

    # Log new codes added from rulings
    llm_codes = {c.get('subheading', '').replace('.', '') for c in llm_candidates}
    new_from_rulings = [
        c for c in merged
        if c.get('source') == 'ruling' and c.get('subheading', '').replace('.', '') not in llm_codes
    ]
    if new_from_rulings:
        new_codes = [c['subheading'] for c in new_from_rulings]
        debug_print(f"  [merge_final_candidates] NEW codes from rulings: {new_codes}")

    return {"subheading_candidates": merged}


# ============================================================================
# NODE 3: SEARCH AND CLASSIFY
# ============================================================================

def search_and_classify(state: FastState) -> dict:
    """
    Search HTS products using hybrid semantic + keyword search (when available)
    or fallback to exact SQL matching.

    Now includes CBP rulings context in classification prompt.
    """
    model = MODEL
    engine = get_raw_connection()

    if engine is None:
        return {
            "detailed_candidates": [],
            "confidence": 0.3,
            "reasoning": "Database not configured"
        }

    subheading_candidates = state.get("subheading_candidates", [])
    if not subheading_candidates:
        return {
            "detailed_candidates": [],
            "confidence": 0.3,
            "reasoning": "No subheading candidates"
        }

    subheading_codes = []
    for s in subheading_candidates:
        code = s["subheading"].replace(".", "").replace(" ", "")
        if len(code) == 6:
            subheading_codes.append(code)

    if not subheading_codes:
        return {
            "detailed_candidates": [],
            "confidence": 0.3,
            "reasoning": "No valid subheading codes"
        }

    try:
        with engine.connect() as conn:
            # Full retrieval - NO hybrid search, NO limit
            # Retrieve ALL codes within candidate subheadings for complete LLM context
            debug_print("  [search_and_classify] Using full retrieval (no hybrid search)")
            placeholders = ", ".join([f"'{c}'" for c in subheading_codes])
            result = conn.execute(text(f"""
                SELECT
                    chapter_code, chapter_desc,
                    heading_code, heading_desc,
                    subheading_code, subheading_desc,
                    subheading_8_code, subheading_8_desc_explained,
                    statistical_rep_number, statistical_rep_desc_explained,
                    unit, general_duty_rate, special_duty_rate, usmca_eligible
                FROM hts_products
                WHERE subheading_code IN ({placeholders})
                ORDER BY subheading_code, subheading_8_code, statistical_rep_number
            """))
            rows = result.fetchall()

            if not rows:
                return {
                    "detailed_candidates": [],
                    "confidence": 0.3,
                    "reasoning": f"No products found for subheadings: {subheading_codes}"
                }

            hts_text = format_hts_results(rows)
            debug_print(f"  [search_and_classify] Found {len(rows)} HTS codes")

            # Format rulings for prompt (Phase 0 Fix #4: check historical codes)
            relevant_rulings = state.get("relevant_rulings", [])
            rulings_text = format_ruling_results(relevant_rulings, conn)

    except Exception as e:
        debug_print(f"  [search_and_classify] DB Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "detailed_candidates": [],
            "confidence": 0.3,
            "reasoning": f"Database error: {str(e)}"
        }
    finally:
        engine.dispose()

    chapter_summary = state.get("chapter_summary", "")
    chapter_rules = state.get("chapter_rules", "")

    system_prompt = """You are an HTS classification expert selecting the best tariff codes.

TASK:
- Review the HTS codes from the database
- CITE and APPLY relevant CBP rulings as binding classification precedents
- Select ALL codes that could apply to this product (1-10 codes)
- Provide both 8-digit and 10-digit codes when applicable
- Consider chapter notes for legal requirements

*** MANDATORY RULING USAGE RULES ***
1. You MUST cite at least one CBP ruling by number (e.g., "N289289") if any rulings are provided
2. If a ruling describes a NEARLY IDENTICAL product, you MUST use that ruling's tariff codes as PRIMARY
3. DO NOT say "well-established practice" or "straightforward classification" - CITE THE SPECIFIC RULING
4. If you choose a code NOT directly supported by a ruling, you MUST explain why the rulings don't apply
5. Rulings are BINDING legal precedents - they OVERRIDE general customs knowledge

*** MULTI-CODE RULINGS ***
When a ruling shows MULTIPLE codes (e.g., "CODES: 6104.43.2020, 6211.43.0091, 6117.80.9540"):
- These represent DIFFERENT COMPONENTS of the product (e.g., dress, top, tights, headpiece)
- You MUST include ALL codes from the ruling as separate candidates
- Each component/code should be listed individually in your output
- Do NOT pick just one code from a multi-code ruling - include ALL of them

FORMAT YOUR REASONING TO INCLUDE:
- "Based on ruling [NUMBER], which classifies [similar product] under [code]..."
- "Ruling [NUMBER] is directly applicable because..."
- If no ruling applies: "The provided rulings do not directly apply because..."

CRITICAL RULES FOR HISTORICAL RULING CODES:
1. If a ruling is marked as "HISTORICAL CODE", the exact tariff code cited is OBSOLETE
2. BUT the ruling's classification LOGIC still applies - find the EQUIVALENT current code under the same subheading
3. Historical rulings are still BINDING precedents for the product type

GENERAL CLASSIFICATION RULES:
- ONLY use codes from the "Available HTS Codes" database results provided
- NEVER invent or guess codes
- NEVER use historical/obsolete code numbers directly
- CBP rulings are MANDATORY precedents - you MUST cite them
- Chapter notes are legally binding - follow them
- When uncertain, include multiple codes rather than guessing
- Order by confidence (highest first)

GENERAL RULES OF INTERPRETATION (GRI):

1: Classification by heading terms and section/chapter notes (titles/index are reference only).
2:
(a) Incomplete/unfinished articles with "essential character" classify as complete
(b) Material references include mixtures; goods with multiple materials use Rule 3

3: (two or more possible headings):
(a) Most specific description PREVAILS - CRITICAL GUIDANCE:
    - MATERIAL-BASED headings (e.g., 6913-Ceramic, 7013-Glass, 4420-Wood, 3824-Chemical preparations)
      are MORE SPECIFIC than USE-BASED headings (e.g., 9505-Festive articles, 8306-Ornaments)
    - Example: "Ceramic Christmas tree" → 6913 (ceramic articles) NOT 9505 (festive articles)
    - Example: "Krill oil supplement" → 3824 (chemical preparations) NOT 1516/1603 (fats/fish extracts)
    - The MATERIAL defines WHAT the article IS; the USE describes HOW it is used
    - Only classify under USE-based heading if NO material heading exists or Chapter Note explicitly excludes
(b) If material is mixed, classify by component giving "essential character"
(c) If STILL tied after (a) and (b), use last heading numerically

4: Classify under "most akin" goods if Rules 1-3 fail
5: Containers/cases classify with contents if specially fitted and for long-term use (unless container gives essential character). Packing materials classify with goods unless reusable.
6: Same rules apply at subheading level (compare only same-level subheadings)

*** 8/10-DIGIT GRANULAR CLASSIFICATION ***
The 8 and 10-digit statistical suffixes often depend on attributes like:
- SIZE: children's vs adult, specific size ranges (e.g., sizes 2-6, 7-16)
- GENDER: men's, women's, boys', girls', unisex
- MATERIAL %: fiber content percentages, specific material thresholds
- SPECIFIC USE: work footwear vs athletic, formal vs casual
- VALUE: price thresholds (e.g., over/under $X per unit)

When these attributes are NOT specified in the product description:
1. Identify ALL plausible 10-digit codes under the correct 6-digit subheading
2. Include MULTIPLE options in your candidates (e.g., both men's and women's versions)
3. Note in reasoning which attribute is missing and what values would lead to each code
4. Do NOT guess a single code - provide alternatives for user to verify"""

    # Build chapter rules section only if rules exist
    chapter_rules_section = ""
    if chapter_rules:
        chapter_rules_section = f"""
Chapter-Specific Classification Rules:
{chapter_rules}
"""

    user_prompt = f"""Product: {state['normalized_product']}
Materials: {state['materials']}
Use: {state['primary_use']}

Chapter Notes Summary:
{chapter_summary}
{chapter_rules_section}
Available HTS Codes:
{hts_text}

Relevant CBP Rulings (BINDING classification precedents):
{rulings_text}

IMPORTANT: You MUST cite at least one ruling number in your reasoning. Select all applicable HTS codes. If a ruling matches this product closely, use that ruling's code. Return JSON."""

    class HTSCandidate(BaseModel):
        code: str = Field(description="8 or 10-digit HTS code from database")
        certainty: str = Field(
            description="""HIGH: ONLY when (1) CBP ruling cites nearly identical product with this code, AND (2) all critical attributes (material, size, gender) are specified. MEDIUM: Similar ruling exists OR product matches heading clearly but 10-digit uncertain. LOW: No relevant ruling, multiple headings equally valid, or key info missing.""",
            pattern="^(HIGH|MEDIUM|LOW)$"
        )
        reasoning: str

    class ClassificationOutput(BaseModel):
        candidates: list[HTSCandidate] = Field(min_length=1, max_length=10)
        overall_certainty: str = Field(
            description="Overall certainty - use LOWEST of any candidate's certainty. If any candidate is MEDIUM, overall is MEDIUM. If any is LOW, overall is LOW.",
            pattern="^(HIGH|MEDIUM|LOW)$"
        )
        information_gaps: str = Field(
            description="What additional information would increase certainty? (if MEDIUM/LOW)"
        )
        reasoning: str

    structured_model = model.with_structured_output(ClassificationOutput)

    response = structured_model.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ])

    debug_print(f"  [search_and_classify] Selected {len(response.candidates)} candidates (certainty: {response.overall_certainty})")

    return {
        "detailed_candidates": [
            {"code": c.code, "certainty": c.certainty, "reasoning": c.reasoning}
            for c in response.candidates
        ],
        "confidence": response.overall_certainty,  # Store as confidence for compatibility
        "certainty": response.overall_certainty,
        "information_gaps": response.information_gaps,
        "reasoning": response.reasoning
    }


# ============================================================================
# NODE 3.5: COMPARE AND DECIDE (EXPLICIT REASONING STEP - VARIANT C)
# ============================================================================

def compare_and_decide(state: FastState) -> dict:
    """
    Tiered classification step: Assign candidates to tiers (PRIMARY/ALTERNATIVE/POSSIBLE/CONSIDERED)
    with explicit ranking and multi-product detection.

    This replaces the old "select top 3" approach with a more nuanced tier system.
    """
    model = MODEL
    candidates = state.get("detailed_candidates", [])
    relevant_rulings = state.get("relevant_rulings", [])

    if not candidates:
        return {}

    # Format candidates for comparison
    candidates_text = "\n".join([
        f"Candidate {i+1}: {c['code']} (certainty: {c.get('certainty', 'MEDIUM')})\n  Reasoning: {c['reasoning']}"
        for i, c in enumerate(candidates)
    ])

    # Format rulings - show ALL tariff codes for multi-code rulings
    def format_ruling_codes_brief(r):
        codes = r.get('tariff_codes') or []  # Handle None explicitly
        # Filter out Chapter 98-99 codes (not in HTS database yet)
        product_codes = [c for c in codes if not c.startswith(('98', '99'))]
        if len(product_codes) > 1:
            return f"CODES: {', '.join(product_codes)}"
        return r.get('primary_tariff', 'N/A')

    rulings_text = "\n".join([
        f"Ruling {r['ruling_number']}: {format_ruling_codes_brief(r)} - {r['product_description'][:200]}..."
        for r in relevant_rulings[:5]  # Increased from 3 to 5 for better coverage
    ]) if relevant_rulings else "No relevant rulings found."

    system_prompt = """You are a senior customs classification reviewer.

TASK: Review candidates and assign to tiers with explicit ranking.

TIER DEFINITIONS:
- PRIMARY (usually 1): The definitive classification. Use multiple PRIMARY only if
  description contains MULTIPLE DISTINCT PRODUCTS (flag this).
- ALTERNATIVE (usually 1-2): Equally valid options for ambiguous cases.
- POSSIBLE (usually 1-3): Could apply but less certain due to missing information.
- CONSIDERED: Codes you evaluated but rejected. Include reasoning why rejected.

*** RULING-BASED RANKING RULE (HIGHEST PRIORITY) ***
When a CBP ruling describes a product SUBSTANTIALLY SIMILAR to the query:
1. The ruling's tariff code(s) MUST be ranked as PRIMARY (rank 1)
2. OVERRIDE your general classification intuition with the ruling
3. Only rank a different code as PRIMARY if you have SPECIFIC evidence
   that the ruling does not apply (different material, different use, etc.)
4. Document WHY if you deviate from a ruling's classification
5. Set ruling_support to the ruling number when using a ruling-supported code

Rulings are LEGALLY BINDING precedents. When in doubt, FOLLOW THE RULING.

COMMON MISTAKE: The correct code appears in candidates but gets ranked as ALTERNATIVE
instead of PRIMARY because the LLM "second-guesses" the ruling. DO NOT DO THIS.
If a ruling supports a code, that code is PRIMARY unless you can prove it doesn't apply.

MULTI-PRODUCT DETECTION & MULTI-CODE EXTRACTION:
Carefully analyze if the product contains MULTIPLE DISTINCT ITEMS requiring separate classification:
- Costume SET with dress + tights + headpiece = multi_product_flag=true (each component gets PRIMARY)
- Kit with multiple different tools = multi_product_flag=true
- Bundle of different product types = multi_product_flag=true
- Single product with multiple materials = multi_product_flag=false (one PRIMARY code)

*** CRITICAL: EXTRACT ALL CODES FROM MATCHING RULINGS ***
If a CBP ruling shows MULTIPLE tariff codes (e.g., "CODES: 6104.43.2020, 6211.43.0091, 6117.80.9540"):
- Each code represents a DIFFERENT COMPONENT of the product
- ALL codes from that ruling must be included as PRIMARY candidates
- Set multi_product_flag=true when ruling has multiple codes
- Do NOT pick just one code - use ALL codes the ruling specifies

CRITICAL RULES:
1. If a CBP ruling describes a nearly IDENTICAL product, ALL of that ruling's tariff codes MUST be PRIMARY
2. Ruling precedents are BINDING - you must follow them unless the product is materially different
3. ALL candidates must be ranked (no ties in rank) - rank 1 is best
4. Each tier should have a soft limit (PRIMARY: varies by ruling, ALTERNATIVE: 2, POSSIBLE: 3, CONSIDERED: unlimited)
5. When ruling shows multiple codes, there will be multiple PRIMARY codes (one per component)

RULES OF CLASSIFICATION (GRI):
1: Classification by heading terms and section/chapter notes (titles/index are reference only).
2: (a) Incomplete/unfinished articles with "essential character" classify as complete
   (b) Material references include mixtures; goods with multiple materials use Rule 3
3: (two or more possible headings):
   (a) Most specific description PREVAILS - MATERIAL VS USE RULE:
       * MATERIAL-BASED headings (6913-Ceramic, 7013-Glass, 3824-Chemicals) are MORE SPECIFIC
         than USE-BASED headings (9505-Festive, 8306-Ornaments, 1516-Fats, 1603-Fish extracts)
       * "Ceramic Christmas tree" → 6913 (ceramic) NOT 9505 (festive)
       * "Krill oil supplement" → 3824 (chemical prep) NOT 1516/1603 (animal fats/fish)
       * Material defines WHAT the article IS; use describes HOW it is used
   (b) If material is mixed, classify by component giving "essential character"
   (c) If STILL tied, use last heading numerically
4: Classify under "most akin" goods if Rules 1-3 fail
5: Containers/cases classify with contents if specially fitted and for long-term use
6: Same rules apply at subheading level (compare only same-level subheadings)

*** WHEN RULINGS CONFLICT WITH GRI 3(a) ***
If CBP rulings suggest BOTH a material-based code AND a use-based code:
- Apply GRI 3(a) to determine which ruling's LOGIC is correct
- Do NOT blindly follow the most recent ruling - follow the ruling that correctly applies GRI
- Material-based classification is almost always more specific than use-based

OUTPUT: Rank ALL candidates (including rejected ones in CONSIDERED tier)."""

    user_prompt = f"""Product: {state['normalized_product']}
Materials: {state['materials']}
Use: {state['primary_use']}

CANDIDATE CODES:
{candidates_text}

CBP RULING PRECEDENTS:
{rulings_text}

Assign each candidate to a tier and provide global ranking. Detect if this describes multiple products."""

    class RankedCandidate(BaseModel):
        code: str = Field(description="8 or 10-digit HTS code")
        tier: str = Field(
            description="PRIMARY: best match | ALTERNATIVE: equally valid | POSSIBLE: less certain | CONSIDERED: rejected",
            pattern="^(PRIMARY|ALTERNATIVE|POSSIBLE|CONSIDERED)$"
        )
        rank: int = Field(ge=1, description="Global rank, 1 = best")
        certainty: str = Field(pattern="^(HIGH|MEDIUM|LOW)$")
        reasoning: str
        ruling_support: Optional[str] = Field(default=None, description="Ruling number if this code is supported by a ruling")

    class TieredDecisionOutput(BaseModel):
        ranked_candidates: list[RankedCandidate] = Field(min_length=1, max_length=15)
        multi_product_flag: bool = Field(description="True if description describes multiple distinct products")
        num_distinct_products: int = Field(ge=1, description="Number of distinct products in description")
        overall_certainty: str = Field(pattern="^(HIGH|MEDIUM|LOW)$")
        reasoning: str

    structured_model = model.with_structured_output(TieredDecisionOutput)

    response = structured_model.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ])

    primary_codes = [c.code for c in response.ranked_candidates if c.tier == "PRIMARY"]
    debug_print(f"  [compare_and_decide] PRIMARY: {primary_codes} | Multi-product: {response.multi_product_flag}")

    # Convert to dict format and sort by rank
    ranked_candidates = sorted(
        [
            {
                "code": c.code,
                "tier": c.tier,
                "rank": c.rank,
                "certainty": c.certainty,
                "reasoning": c.reasoning,
                "ruling_support": c.ruling_support
            }
            for c in response.ranked_candidates
        ],
        key=lambda x: x["rank"]
    )

    return {
        "detailed_candidates": ranked_candidates,
        "multi_product_flag": response.multi_product_flag,
        "num_distinct_products": response.num_distinct_products,
        "certainty": response.overall_certainty,
        "confidence": response.overall_certainty,  # For compatibility
        "reasoning": response.reasoning
    }


def format_hts_results(rows) -> str:
    lines = []
    for row in rows:
        code = row[8] if row[8] else row[6]  # 10-digit or 8-digit
        desc = row[9] if row[9] else row[7]
        duty = row[11] if row[11] else "N/A"
        lines.append(f"Code: {code}\nDescription: {desc}\nDuty: {duty}\n{'─'*40}")
    return "\n".join(lines)


# ============================================================================
# NODE 4: HYDRATE CANDIDATES
# ============================================================================

def hydrate_candidates(state: FastState) -> dict:
    """Enrich candidates with full hierarchy and duty info from database."""
    engine = get_raw_connection()
    candidates = state.get("detailed_candidates", [])

    if not candidates or not engine:
        return {"detailed_candidates": candidates}

    hts_codes = []
    for c in candidates:
        code = c.get("code", "").replace(".", "").replace(" ", "")
        if code and len(code) in (8, 10):
            hts_codes.append(code)

    if not hts_codes:
        return {"detailed_candidates": candidates}

    try:
        with engine.connect() as conn:
            formatted = "', '".join(hts_codes)
            result = conn.execute(text(f"""
                SELECT
                    subheading_8_code, subheading_8_desc_explained,
                    statistical_rep_number, statistical_rep_desc_explained,
                    general_duty_rate, special_duty_rate, unit,
                    heading_code, heading_desc,
                    subheading_code, subheading_desc,
                    chapter_code, chapter_desc
                FROM hts_products
                WHERE subheading_8_code IN ('{formatted}')
                   OR statistical_rep_number IN ('{formatted}')
            """))

            rows = result.fetchall()

            row_map = {}
            for row in rows:
                if row[0]:
                    row_map[row[0].replace(".", "")] = row
                if row[2]:
                    row_map[row[2].replace(".", "")] = row

            hydrated = []
            for cand in candidates:
                code = cand.get("code", "").replace(".", "")
                row = row_map.get(code)

                if row:
                    is_10 = len(code) == 10

                    # Determine which description to use (10-digit takes precedence if available)
                    description = row[3] if is_10 and row[3] else row[1]
                    hts_code = row[2] if is_10 and row[2] else row[0]

                    # Build hierarchy object matching ResultCard expectations
                    hierarchy = {
                        "chapter": {"code": str(row[11]), "description": row[12] or ""},
                        "heading": {"code": str(row[7]), "description": row[8] or ""},
                        "subheading": {"code": str(row[9]), "description": row[10] or ""},
                        "hts_full": {
                            "code": str(hts_code) if hts_code else "",
                            "description": description if description else ""
                        }
                    }

                    # For 10-digit codes, add US HTS and Statistical Reporting Number
                    if is_10:
                        us_hts_code = code[6:8] if len(code) >= 8 else ""
                        stat_code = code[8:10] if len(code) == 10 else ""

                        hierarchy["us_hts"] = {
                            "code": us_hts_code,
                            "description": row[1] if row[1] else ""  # 8-digit description
                        }
                        hierarchy["statistical_reporting_number"] = {
                            "code": stat_code,
                            "description": description if description else ""
                        }

                    hydrated.append({
                        **cand,
                        "code": code,
                        "description": description,
                        "hierarchy": hierarchy,
                        "duty_info": {
                            "general_rate": row[4] or "N/A",
                            "special_rate": row[5] or "N/A",
                            "quota": row[6] or "N/A"
                        },
                        # Preserve tier and rank fields from compare_and_decide
                        "tier": cand.get("tier"),
                        "rank": cand.get("rank"),
                        "ruling_support": cand.get("ruling_support")
                    })
                else:
                    hydrated.append(cand)

            debug_print(f"  [hydrate_candidates] Hydrated {len(hydrated)} candidates")
            return {"detailed_candidates": hydrated}

    except Exception as e:
        debug_print(f"  [hydrate_candidates] Error: {e}")
        return {"detailed_candidates": candidates}
    finally:
        engine.dispose()


# ============================================================================
# NODE 5: FORMAT FINAL CODES
# ============================================================================

def format_final_codes(state: FastState) -> dict:
    candidates = state.get("detailed_candidates", [])

    if not candidates:
        return {
            "final_codes": [],
            "ranked_candidates": [],
            "confidence": 0.0,
            "reasoning": "No candidates"
        }

    # Group by tier
    by_tier = {"PRIMARY": [], "ALTERNATIVE": [], "POSSIBLE": [], "CONSIDERED": []}
    for c in candidates:
        tier = c.get("tier", "POSSIBLE")
        by_tier[tier].append(c)

    # Build backward-compatible final_codes (PRIMARY + ALTERNATIVE only)
    codes = []
    seen = set()

    for cand in by_tier["PRIMARY"] + by_tier["ALTERNATIVE"]:
        code = cand.get("code", "").replace(".", "").replace(" ", "")

        if len(code) == 10:
            formatted = f"{code[:4]}.{code[4:6]}.{code[6:8]}.{code[8:]}"
            code_8 = f"{code[:4]}.{code[4:6]}.{code[6:8]}"
            if code_8 not in seen:
                codes.append(code_8)
                seen.add(code_8)
        elif len(code) == 8:
            formatted = f"{code[:4]}.{code[4:6]}.{code[6:]}"
        else:
            formatted = code

        if formatted not in seen:
            codes.append(formatted)
            seen.add(formatted)

    return {
        "final_codes": codes,  # Backward compat (flat list of actionable codes)
        "ranked_candidates": candidates,  # Full tiered output with all metadata
        "confidence": state.get("confidence", 0.5),
        "reasoning": state.get("reasoning", "")
    }


# ============================================================================
# BUILD GRAPH (WITH PARALLEL EXECUTION)
# ============================================================================

builder = StateGraph(FastState)

# Add all nodes
builder.add_node("narrow_and_select", narrow_and_select)
builder.add_node("validate_subheadings", validate_subheadings)
builder.add_node("fetch_chapter_summary", fetch_chapter_summary)
builder.add_node("search_rulings", search_rulings)
builder.add_node("merge_final_candidates", merge_final_candidates)          # NEW NODE
builder.add_node("search_and_classify", search_and_classify)
builder.add_node("compare_and_decide", compare_and_decide)                 # VARIANT C: Reasoning step
builder.add_node("hydrate_candidates", hydrate_candidates)
builder.add_node("format_final_codes", format_final_codes)

# PARALLEL FAN-OUT: Both nodes start from START
builder.add_edge(START, "narrow_and_select")

# PARALLEL FAN-IN: Both merge into merge_initial_candidates
# LangGraph automatically waits for both to complete before running merge

# Sequential flow continues
builder.add_edge("narrow_and_select", "validate_subheadings")
builder.add_edge("validate_subheadings", "fetch_chapter_summary")
builder.add_edge("fetch_chapter_summary", "search_rulings")
builder.add_edge("search_rulings", "merge_final_candidates")
builder.add_edge("merge_final_candidates", "search_and_classify")
# VARIANT C: Add explicit reasoning step
builder.add_edge("search_and_classify", "compare_and_decide")
builder.add_edge("compare_and_decide", "hydrate_candidates")
builder.add_edge("hydrate_candidates", "format_final_codes")
builder.add_edge("format_final_codes", END)

graph = builder.compile()


# ============================================================================
# PUBLIC API
# ============================================================================

def classify_single(
    product_description: str,
    language: str = "en",
    image_url: Optional[str] = None,
    user_instructions: Optional[str] = None
) -> dict:
    """
    Classify a single product using the fast workflow with rulings integration.
    """
    start_time = time.time()

    initial_state = {
        "original_input": product_description,
        "language": language,
        "image_url": image_url,
        "user_instructions": user_instructions,
        "normalized_product": "",
        "materials": "",
        "primary_use": "",
        "chapter_candidates": [],
        "heading_candidates": [],
        "subheading_candidates": [],
        "initial_confidence": 0.0,
        "chapter_summary": "",
        "chapter_rules": "",
        "detailed_candidates": [],
        "confidence": 0.0,
        "reasoning": "",
        "final_codes": [],
        "relevant_rulings": [],        # NEW: Initialize rulings list
        "semantic_subheadings": [],    # NEW: From parallel semantic search
        "ruling_subheadings": [],       # NEW: Extracted from rulings
        "multi_product_flag": False,    # NEW: Multi-product detection
        "num_distinct_products": 1      # NEW: Number of distinct products
    }

    result = graph.invoke(initial_state)
    execution_time = time.time() - start_time

    # Extract warnings if any (from reasoning or candidates)
    warnings = []
    reasoning_text = result.get("reasoning", "")
    if "missing" in reasoning_text.lower() or "uncertain" in reasoning_text.lower() or "caveat" in reasoning_text.lower():
        warnings.append("Classification may require additional product information for higher confidence.")

    # Extract rulings metadata
    relevant_rulings = result.get("relevant_rulings", [])
    rulings_count = len(relevant_rulings)

    # Extract and group candidates by tier for easy access (preserves ranking within each tier)
    # Note: detailed_candidates contains tier info from hydrate_candidates node
    detailed_candidates = result.get("detailed_candidates", [])
    by_tier = {
        "PRIMARY": [c for c in detailed_candidates if c.get("tier") == "PRIMARY"],
        "ALTERNATIVE": [c for c in detailed_candidates if c.get("tier") == "ALTERNATIVE"],
        "POSSIBLE": [c for c in detailed_candidates if c.get("tier") == "POSSIBLE"],
        "CONSIDERED": [c for c in detailed_candidates if c.get("tier") == "CONSIDERED"]
    }

    return {
        "final_codes": result.get("final_codes", []),  # Backward compat (PRIMARY + ALTERNATIVE codes)
        "ranked_candidates": detailed_candidates,  # Full tiered output sorted by rank (1 = best)

        # Individual tier access for easier consumption (each preserves ranking)
        "primary_candidates": by_tier["PRIMARY"],
        "alternative_candidates": by_tier["ALTERNATIVE"],
        "possible_candidates": by_tier["POSSIBLE"],
        "considered_candidates": by_tier["CONSIDERED"],

        "multi_product_flag": result.get("multi_product_flag", False),
        "num_distinct_products": result.get("num_distinct_products", 1),
        "confidence": result.get("confidence", 0.0),
        "reasoning": result.get("reasoning", ""),
        "detailed_candidates": result.get("detailed_candidates", []),
        "chapter_notes_summary": result.get("chapter_summary", ""),
        "warnings": warnings,
        "execution_time_seconds": round(execution_time, 2),
        "normalized_product": result.get("normalized_product", ""),
        "rulings_count": rulings_count
    }


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Fast HTS Classification with Improved Rulings (fixes locked-in problem)"
    )
    parser.add_argument("--single", type=str, help="Classify single product")
    parser.add_argument("--language", type=str, default="en", help="Language (en/es)")
    parser.add_argument("--instructions", type=str, default=None, help="Custom broker instructions")

    args = parser.parse_args()

    if args.single:
        print("\n" + "=" * 60)
        print("HTS EXPRESS CLASSIFICATION")
        print("=" * 60)
        print(f"Product: {args.single}\n")

        result = classify_single(args.single, args.language, user_instructions=args.instructions)

        print("\n" + "=" * 60)
        print("RESULT")
        print("=" * 60)
        print(f"Codes: {', '.join(result['final_codes'])}")
        print(f"Certainty: {result['confidence']}")  # Now a string: HIGH/MEDIUM/LOW
        print(f"Time: {result['execution_time_seconds']}s")
        print(f"Rulings found: {result.get('rulings_count', 0)}")
        print(f"Reasoning: {result['reasoning']}")
    else:
        parser.print_help()
