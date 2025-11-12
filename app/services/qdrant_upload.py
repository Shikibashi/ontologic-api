"""
qdrant_upload.py

Handles uploading and ingestion of documents (PDF, DOCX, Markdown, TXT) into Qdrant collections.

This module provides a service class and helper functions for:
- Parsing supported file types
- Generating embeddings (via LLMManager or similar)
- Uploading parsed and embedded content to Qdrant

Follows project conventions for modularity, type hints, and docstrings.
"""

from typing import Optional, List, Dict, Any
from pathlib import Path
from app.config.settings import get_settings

# --- LlamaIndex semantic chunking imports ---
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.core import Document
from app.utils.file_parser import FileParser
from app.services.llm_manager import LLMManager
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse, ResponseHandlingException
import uuid
import logging
import traceback
from app.core.logger import log, get_log_directory

# Set up a dedicated file logger for QdrantUploadService
qdrant_upload_logger = logging.getLogger("qdrant_upload")
qdrant_upload_logger.setLevel(logging.DEBUG)

log_dir = get_log_directory()
file_handler = logging.FileHandler(log_dir / "qdrant_upload_debug.log")
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
file_handler.setFormatter(formatter)
if not qdrant_upload_logger.hasHandlers():
    qdrant_upload_logger.addHandler(file_handler)

class QdrantUploadService:
    """
    Service for handling file uploads and ingestion into Qdrant.
    Supports PDF, DOCX, Markdown, and TXT files.
    """

    def extract_file_metadata(self, file_bytes: bytes, filename: str, ext: str) -> dict:
        """
        Extracts metadata from the file itself (PDF/DOCX) or falls back to filename/defaults.

        Args:
            file_bytes (bytes): The file content.
            filename (str): The file name.
            ext (str): File extension.

        Returns:
            dict: Extracted metadata fields (title, author, topic, document_type).
        """
        meta = {}
        if ext == "pdf":
            try:
                # pymupdf4llm depends on pymupdf which provides fitz
                # Verify both dependencies are available
                import fitz
                import pymupdf4llm  # Explicit check for our main dependency
                with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                    info = doc.metadata
                    meta["title"] = info.get("title") or None
                    meta["author"] = info.get("author") or None
                    meta["topic"] = info.get("subject") or None
            except ImportError as e:
                from app.core.logger import log
                log.warning(f"[QdrantUploadService] PDF processing dependencies unavailable: {e}")
            except (ValueError, AttributeError, OSError) as e:
                # ValueError: Invalid PDF structure
                # AttributeError: Missing metadata attributes
                # OSError: File read/memory errors
                from app.core.logger import log
                log.debug(f"[QdrantUploadService] Could not extract PDF metadata: {e}")
        elif ext == "docx":
            try:
                from docx import Document
                from io import BytesIO
                doc = Document(BytesIO(file_bytes))
                cp = doc.core_properties
                meta["title"] = cp.title or None
                meta["author"] = cp.author or None
                meta["topic"] = cp.subject or None
            except ImportError as e:
                log.warning(f"[QdrantUploadService] DOCX processing dependencies unavailable: {e}")
            except (ValueError, KeyError, AttributeError, OSError) as e:
                # ValueError: Corrupt archive
                # KeyError: Missing core properties
                # AttributeError: Invalid document structure
                # OSError: File access errors
                log.debug(f"[QdrantUploadService] Could not extract DOCX metadata: {e}")
        # Fallbacks for all types
        if not meta.get("title"):
            meta["title"] = filename.rsplit(".", 1)[0]
        if not meta.get("author"):
            # Try to extract author from filename if possible
            meta["author"] = self._extract_author_from_filename(filename) or "Unknown Author"
        if not meta.get("document_type"):
            meta["document_type"] = ext.upper()
        return meta

    def _extract_author_from_filename(self, filename: str) -> Optional[str]:
        """
        Attempt to extract author(s) from the filename using common patterns, including handling
        multiple parentheses and dash patterns.

        Args:
            filename (str): The file name.

        Returns:
            str: Extracted author(s) or None if not found.
        """
        import re

        # Remove extension
        name = filename.rsplit(".", 1)[0]

        # Pattern 1: Multiple parentheses groups, prefer second-to-last if last is a known tag
        parens = re.findall(r"\(([^)]+)\)", name)
        if parens:
            # Remove known tags from last group
            known_tags = {"z-library", "zlibrary"}
            last = parens[-1].strip().lower().replace("-", "")
            if last in known_tags and len(parens) > 1:
                author = parens[-2].strip()
                # Remove known tags from author if present
                author = re.sub(r"(?i)z-?library", "", author).strip(" .,-")
                if author:
                    return author
            else:
                # If only one group or last isn't a known tag, use last group if it doesn't look like a tag
                author = parens[-1].strip()
                author_clean = re.sub(r"(?i)z-?library", "", author).strip(" .,-")
                if author_clean and author_clean.lower() not in known_tags:
                    return author_clean

        # Pattern 2: by Author, e.g. "Title by Author"
        match = re.search(r"\bby ([^-()]+)$", name, re.IGNORECASE)
        if match:
            author = match.group(1).strip()
            return author

        # Pattern 3: Dash patterns
        # Default to left side as author for two-part splits ("Author - Title")
        dash_split = [part.strip() for part in name.split(" - ")]
        if len(dash_split) == 2:
            left, right = dash_split
            # Helper: does this look like a person name? (at least two capitalized words)
            def looks_like_name(s):
                return bool(re.match(r"^([A-Z][a-z]+(?: [A-Z][a-z]+)+)$", s))
            left_is_name = looks_like_name(left)
            right_is_name = looks_like_name(right)
            if left_is_name and right_is_name:
                return right  # Prefer right if both look like names
            if right_is_name:
                return right
            if left_is_name:
                return left
            return left  # Default to left if neither looks like a name

        # Pattern 4: Author in brackets, e.g. "[Author] Title"
        match = re.match(r"\[([^\]]+)\]", name)
        if match:
            author = match.group(1).strip()
            return author

        return None

    def __init__(
        self,
        qdrant_client: Optional[AsyncQdrantClient] = None,
        llm_manager: Optional[LLMManager] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
    ):
        """
        Initialize the QdrantUploadService.

        Args:
            qdrant_client (Optional[AsyncQdrantClient]): Qdrant client instance.
            llm_manager (Optional[LLMManager]): LLM manager for embeddings.
            chunk_size (int): Number of characters per chunk.
            chunk_overlap (int): Number of overlapping characters between chunks.
        """
        # Use the singleton Qdrant client from QdrantManager if not provided
        if qdrant_client is not None:
            self.qdrant_client = qdrant_client
        else:
            from app.services.qdrant_manager import QdrantManager
            self.qdrant_client = QdrantManager().qclient
        self.llm_manager = llm_manager or LLMManager()
        self.file_parser = FileParser()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _get_embed_model_name(self) -> str:
        """
        Get embedding model name from settings with graceful fallback.

        Returns:
            str: Embedding model name from settings or default fallback
        """
        try:
            settings = get_settings()
            return settings.embed_model
        except (ImportError, AttributeError, KeyError) as e:
            # Expected configuration errors - use fallback
            qdrant_upload_logger.warning(
                f"Could not read embed_model from settings: {type(e).__name__}: {e}. Using fallback 'nomic-embed-text'."
            )
            return "nomic-embed-text"
        except Exception as e:
            # Unexpected errors - log but still fallback gracefully
            qdrant_upload_logger.error(
                f"Unexpected error reading embed_model: {type(e).__name__}: {e}. Using fallback 'nomic-embed-text'.",
                exc_info=True
            )
            return "nomic-embed-text"

    def _chunk_text(self, text: str) -> List[str]:
        """
        Splits text into semantic chunks using LlamaIndex SemanticSplitterNodeParser with Ollama embeddings.

        Args:
            text (str): The text to chunk.

        Returns:
            List[str]: List of semantically chunked text segments.
        """
        doc = Document(text=text)
        embed_model_name = self._get_embed_model_name()
        embed_model = OllamaEmbedding(model_name=embed_model_name)
        splitter = SemanticSplitterNodeParser(
            buffer_size=1, breakpoint_percentile_threshold=95, embed_model=embed_model
        )
        nodes = splitter.get_nodes_from_documents([doc])
        return [node.get_content() for node in nodes]

    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        collection: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Parse, chunk, embed, and upload a file to Qdrant, with detailed logging.

        Args:
            file_bytes (bytes): The raw file content.
            filename (str): The name of the file (used to infer type).
            collection (str): Qdrant collection to upload to (automatically set to username).
            metadata (Optional[Dict[str, Any]]): Only contains username; all other metadata is extracted from the file or defaulted.

        Returns:
            Dict[str, Any]: Upload result or error details.
        """
        log.info(f"[QdrantUpload] Starting upload_file: filename={filename}, collection={collection}, metadata={metadata}")
        qdrant_upload_logger.info(f"[QdrantUpload] Starting upload_file: filename={filename}, collection={collection}, metadata={metadata}")
        ext = filename.split(".")[-1].lower()
        # Autofill all metadata fields from file or sensible defaults; only username comes from user
        extracted_meta = self.extract_file_metadata(file_bytes, filename, ext)
        user_meta = metadata or {}
        final_meta = {}
        for key in ["title", "author", "topic", "document_type"]:
            if extracted_meta.get(key):
                final_meta[key] = extracted_meta[key]
        # Always include username if present
        if "username" in user_meta:
            final_meta["username"] = user_meta["username"]

        try:
            if ext in ["txt", "md"]:
                log.info(f"[QdrantUpload] Parsing as text/markdown: ext={ext}")
                content = self.file_parser.parse_file(ext, file_bytes.decode("utf-8"))
            elif ext in ["pdf", "docx"]:
                log.info(f"[QdrantUpload] Parsing as binary: ext={ext}")
                content = self.file_parser.parse_file(ext, file_bytes)
            else:
                log.error(f"[QdrantUpload] Unsupported file type: {ext}")
                return {"error": f"Unsupported file type: {ext}"}
        except UnicodeDecodeError as e:
            # Text file encoding error
            log.error(f"[QdrantUpload] File encoding error for {ext} file: {e}")
            return {"error": f"File encoding error: file is not valid UTF-8 text"}
        except (ImportError, AttributeError) as e:
            # Missing parser dependencies
            log.error(f"[QdrantUpload] Parser dependency error for {ext}: {e}", exc_info=True)
            return {"error": f"Document parser unavailable for {ext} files"}
        except (ValueError, OSError, IOError) as e:
            # Corrupt file or file access errors
            log.error(f"[QdrantUpload] Failed to parse {ext} file: {type(e).__name__}: {e}")
            return {"error": f"Failed to parse file: file may be corrupted or invalid"}
        except Exception as e:
            # Truly unexpected errors
            log.error(
                f"[QdrantUpload] Unexpected error parsing file: {type(e).__name__}: {e}",
                exc_info=True
            )
            return {"error": f"Unexpected error processing file: {type(e).__name__}"}

        log.info(f"[QdrantUpload] File parsed successfully. Content length: {len(content)}")
        qdrant_upload_logger.info(f"[QdrantUpload] File parsed successfully. Content length: {len(content)}")
        chunks = self._chunk_text(content)
        log.info(f"[QdrantUpload] Chunked content into {len(chunks)} chunks (chunk_size={self.chunk_size}, overlap={self.chunk_overlap})")
        qdrant_upload_logger.info(f"[QdrantUpload] Chunked content into {len(chunks)} chunks (chunk_size={self.chunk_size}, overlap={self.chunk_overlap})")
        qdrant_upload_logger.debug(f"First chunk preview: {chunks[0][:500] if chunks else 'NO CHUNKS'}")
        if not chunks:
            log.error("[QdrantUpload] No content to upload after chunking.")
            return {"error": "No content to upload after chunking."}

        points = []
        file_uuid = str(uuid.uuid4())
        for idx, chunk in enumerate(chunks):
            try:
                log.debug(f"[QdrantUpload] Generating embedding for chunk {idx+1}/{len(chunks)} (length={len(chunk)})")
                qdrant_upload_logger.debug(f"Generating embedding for chunk {idx+1}/{len(chunks)} (length={len(chunk)})")
                dense_vector = await self.llm_manager.generate_dense_vector(chunk)
                log.debug(f"[QdrantUpload] Embedding for chunk {idx+1}: {dense_vector[:5]}... (len={len(dense_vector)})")
                qdrant_upload_logger.debug(f"Embedding for chunk {idx+1}: {dense_vector[:5]}... (len={len(dense_vector)})")
            except (ConnectionError, TimeoutError) as e:
                # LLM service infrastructure failure
                log.error(f"[QdrantUpload] LLM connection error for chunk {idx}: {e}")
                qdrant_upload_logger.error(f"LLM connection error for chunk {idx}: {e}")
                return {"error": "Embedding service unavailable. Please try again later."}
            except Exception as e:
                # Other LLM errors or unexpected issues
                log.error(
                    f"[QdrantUpload] Failed to generate embedding for chunk {idx}: {type(e).__name__}: {e}",
                    exc_info=True
                )
                qdrant_upload_logger.error(f"Failed to generate embedding for chunk {idx}: {type(e).__name__}: {e}")
                return {"error": f"Failed to generate embedding for chunk {idx}: {type(e).__name__}"}
            point_id = str(uuid.uuid4())
            payload = {
                "text": chunk,
                "filename": filename,
                "chunk_index": idx,
                "chunk_count": len(chunks),
                "file_id": file_uuid,
                **final_meta,
            }
            log.debug(f"[QdrantUpload] Prepared point {idx+1}: id={point_id}, payload_keys={list(payload.keys())}, payload_preview={str(payload)[:200]}")
            qdrant_upload_logger.debug(f"Prepared point {idx+1}: id={point_id}, payload_keys={list(payload.keys())}, payload_preview={str(payload)[:200]}")
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=dense_vector,
                    payload=payload,
                )
            )

        log.info(f"[QdrantUpload] Uploading {len(points)} points to Qdrant collection '{collection}' in batches...")
        qdrant_upload_logger.info(f"[QdrantUpload] Uploading {len(points)} points to Qdrant collection '{collection}' in batches...")
        qdrant_upload_logger.debug(f"Vector size for collection: {len(points[0].vector) if points else 'NO POINTS'}")
        try:
            # Ensure collection exists before upsert
            try:
                await self.qdrant_client.get_collection(collection_name=collection)
                qdrant_upload_logger.info(f"Collection '{collection}' exists.")
            except (ConnectionError, TimeoutError) as e:
                log.error(f"[QdrantUpload] Qdrant connection error: {e}")
                raise
            except ResponseHandlingException as e:
                log.error(f"[QdrantUpload] Qdrant response handling error: {e}")
                raise
            except UnexpectedResponse as e:
                # Collection doesn't exist (404) or other HTTP error - attempt to create if 404
                if hasattr(e, 'status_code') and e.status_code == 404:
                    log.info(f"[QdrantUpload] Collection '{collection}' does not exist (404). Creating...")
                    qdrant_upload_logger.info(f"Collection '{collection}' does not exist (404). Creating...")
                    try:
                        await self.qdrant_client.create_collection(
                            collection_name=collection,
                            vectors_config=models.VectorParams(
                                size=len(points[0].vector),
                                distance=models.Distance.COSINE
                            )
                        )
                        log.info(f"[QdrantUpload] Collection '{collection}' created.")
                        qdrant_upload_logger.info(f"Collection '{collection}' created.")
                    except (ConnectionError, TimeoutError, ResponseHandlingException, UnexpectedResponse) as create_error:
                        log.error(f"[QdrantUpload] Failed to create collection '{collection}': {create_error}")
                        raise
                else:
                    # Non-404 error from Qdrant - re-raise
                    log.error(f"[QdrantUpload] Unexpected Qdrant response (status={getattr(e, 'status_code', 'unknown')}): {e}")
                    raise

            batch_size = 100
            for i in range(0, len(points), batch_size):
                batch = points[i:i+batch_size]
                qdrant_upload_logger.debug(f"Uploading batch {i//batch_size+1}: size={len(batch)}")
                try:
                    await self.qdrant_client.upsert(
                        collection_name=collection,
                        points=batch,
                    )
                except (ConnectionError, TimeoutError) as e:
                    log.error(f"[QdrantUpload] Connection error during batch {i//batch_size+1} upload: {e}")
                    raise
                except (ResponseHandlingException, UnexpectedResponse) as e:
                    log.error(f"[QdrantUpload] Qdrant error during batch {i//batch_size+1} upload: {e}")
                    raise
            log.info("[QdrantUpload] All batches uploaded successfully.")
            qdrant_upload_logger.info("All batches uploaded successfully.")
        except (ConnectionError, TimeoutError, ResponseHandlingException, UnexpectedResponse) as e:
            # Qdrant-specific errors - expected infrastructure failures
            tb = traceback.format_exc()
            log.error(f"[QdrantUpload] Qdrant infrastructure error: {type(e).__name__}: {e}\n{tb}")
            qdrant_upload_logger.error(f"Qdrant infrastructure error: {type(e).__name__}: {e}\nCollection: {collection}")
            return {
                "error": f"Document storage service error: {type(e).__name__}",
                "traceback": tb,
                "qdrant_collection": collection,
            }
        except Exception as e:
            # Truly unexpected errors (programming errors, etc)
            tb = traceback.format_exc()
            log.error(f"[QdrantUpload] Unexpected error uploading to Qdrant: {type(e).__name__}: {e}\n{tb}\nCollection: {collection}\nPoints: {len(points)}\nFirst point payload: {points[0].payload if points else None}")
            log.error(f"[QdrantUpload] Metadata: collection={collection}, filename={filename}, file_id={file_uuid}, meta={final_meta}")
            qdrant_upload_logger.error(f"Unexpected error: {type(e).__name__}: {e}\n{tb}")
            qdrant_upload_logger.error(f"Metadata: collection={collection}, filename={filename}, file_id={file_uuid}")
            return {
                "error": f"Failed to upload to Qdrant: {type(e).__name__}: {e}",
                "traceback": tb,
                "qdrant_collection": collection,
                "points_count": len(points),
                "first_point_payload": points[0].payload if points else None,
            }

        log.info(f"[QdrantUpload] Upload complete: filename={filename}, file_id={file_uuid}, chunks_uploaded={len(points)}")
        total_char_count = sum(len(chunk) for chunk in chunks)
        return {
            "status": "success",
            "filename": filename,
            "collection": collection,
            "chunks_uploaded": len(points),
            "file_id": file_uuid,
            "char_count": total_char_count,
        }

# Reason: Now uses explicit UUIDs for each file and chunk, and splits large files into overlapping chunks for better semantic search and retrieval.
