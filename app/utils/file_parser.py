"""
Utility module for parsing various file types and extracting their text content.
"""

from typing import Any
import pymupdf4llm
from app.utils.temp_file import secure_temp_file

class FileParser:
    """
    A utility class for parsing different file types (TXT, MD, PDF, DOCX)
    and extracting their textual content.

    PDF parsing uses pymupdf4llm for LLM-optimized text extraction with
    structure preservation (headers, lists, tables) in Markdown format.
    """

    def parse_text(self, file_content: str) -> str:
        """
        Parses a plain text file.

        Args:
            file_content (str): The raw content of the text file.

        Returns:
            str: The extracted text content.
        """
        return file_content

    def parse_markdown(self, file_content: str) -> str:
        """
        Parses a Markdown file. For now, it treats Markdown as plain text.
        Further enhancements can include stripping Markdown syntax.

        Args:
            file_content (str): The raw content of the Markdown file.

        Returns:
            str: The extracted text content, without Markdown formatting (future).
        """
        return file_content

    def _strip_markdown_formatting(self, markdown_text: str) -> str:
        """
        Convert Markdown text to plain text for backward compatibility.

        Handles: headers, bold/italic, links, tables, lists, code blocks.

        Args:
            markdown_text (str): The Markdown-formatted text to strip.

        Returns:
            str: Plain text with Markdown formatting removed.
        """
        import re
        text = markdown_text

        # Remove code blocks first (to avoid processing markdown inside them)
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'`([^`]+)`', r'\1', text)

        # Remove headers (lines starting with #)
        text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

        # Remove bold/italic formatting
        text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
        text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)

        # Remove links [text](url) -> text
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

        # Remove table formatting (preserve content)
        text = re.sub(r'^\|(.+)\|$', r'\1', text, flags=re.MULTILINE)
        text = re.sub(r'\|', ' ', text)  # Convert remaining pipes to spaces

        # Remove list markers but preserve content
        text = re.sub(r'^[-\*\+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)

        # Clean up extra whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)

        return text.strip()

    def parse_pdf(self, file_content: bytes, page_chunks: bool = False, output_format: str = "markdown") -> str:
        """
        Parses a PDF file using pymupdf4llm for LLM-optimized text extraction.

        This method converts PDF content to clean Markdown format with:
        - Automatic reading order detection (handles multi-column layouts)
        - Header detection via font size (preserves document hierarchy)
        - List and table detection (common in philosophical texts)
        - Structure preservation for better LLM understanding

        Args:
            file_content (bytes): The binary content of the PDF file.
            page_chunks (bool): If True, returns page-by-page chunks with metadata.
                              If False (default), returns full document as single string.
            output_format (str): "markdown" (default) for structured output or "text" for plain text
                               (backward compatibility).

        Returns:
            str: The extracted text content in specified format.

        Raises:
            TypeError: If file_content is not bytes or output_format is invalid.
            ValueError: If the PDF file cannot be parsed or is empty.
        """
        # Validate parameters
        if not isinstance(file_content, bytes):
            raise TypeError("file_content must be bytes")
        if len(file_content) == 0:
            raise ValueError("file_content cannot be empty")
        if output_format not in ["markdown", "text"]:
            raise ValueError("output_format must be 'markdown' or 'text'")

        try:
            # Use secure temporary file handling for pymupdf4llm processing
            with secure_temp_file(suffix=".pdf", content=file_content) as tmp_path:
                # Use pymupdf4llm for LLM-optimized extraction with error handling
                try:
                    if page_chunks:
                        # Return page-by-page chunks with metadata (useful for RAG)
                        pages = pymupdf4llm.to_markdown(
                            tmp_path,
                            page_chunks=True,
                            table_strategy="lines_strict",  # Detect tables
                            ignore_images=True,  # Focus on text for now
                        )
                        # Combine all page texts into single string
                        text_content = "\n\n".join(page["text"] for page in pages)
                    else:
                        # Return full document as single Markdown string
                        text_content = pymupdf4llm.to_markdown(
                            tmp_path,
                            table_strategy="lines_strict",
                            ignore_images=True,
                        )
                except TypeError as e:
                    # Fallback to basic extraction if advanced parameters fail
                    from app.core.logger import log
                    log.warning(f"[FileParser] Advanced parameters failed, using basic extraction: {e}")
                    if page_chunks:
                        pages = pymupdf4llm.to_markdown(tmp_path, page_chunks=True)
                        text_content = "\n\n".join(page["text"] for page in pages)
                    else:
                        text_content = pymupdf4llm.to_markdown(tmp_path)

                # Convert to plain text if requested for backward compatibility
                if output_format == "text":
                    text_content = self._strip_markdown_formatting(text_content)

                return text_content

        except ImportError as e:
            from app.core.logger import log
            log.error(f"[FileParser] pymupdf4llm not available: {e}")
            raise ValueError(f"PDF processing library not available: {e}")
        except FileNotFoundError as e:
            from app.core.logger import log
            log.error(f"[FileParser] Temporary file error: {e}")
            raise ValueError(f"Failed to create temporary file for PDF processing: {e}")
        except Exception as e:
            from app.core.logger import log
            log.error(f"[FileParser] Unexpected PDF parsing error: {e}")
            raise ValueError(f"Failed to parse PDF content: {e}")

    def parse_docx(self, file_content: bytes) -> str:
        """
        Parses a DOCX file using python-docx.

        Args:
            file_content (bytes): The binary content of the DOCX file.

        Returns:
            str: The extracted text content.

        Raises:
            ValueError: If the DOCX file cannot be parsed.
        """
        try:
            from docx import Document
            from io import BytesIO
            doc = Document(BytesIO(file_content))
            text_content = []
            for para in doc.paragraphs:
                text_content.append(para.text)
            return "\n".join(text_content)
        except Exception as e:
            from app.core.logger import log
            log.error(f"[FileParser] Error parsing DOCX: {e}")
            raise ValueError(f"Failed to parse DOCX content: {e}")

    def parse_file(self, file_extension: str, file_content: Any) -> str:
        """
        Dispatches file content to the appropriate parser based on its extension.

        Args:
            file_extension (str): The extension of the file (e.g., "txt", "md", "pdf", "docx").
            file_content (Any): The content of the file, either str for text/markdown
                                or bytes for binary files like PDF/DOCX.

        Returns:
            str: The extracted text content from the file.

        Raises:
            ValueError: If the file extension is not supported.
            NotImplementedError: If the parser for the given file type is not yet implemented.
            TypeError: If the file content type does not match the expected type for the extension.
        """
        extension_lower = file_extension.lower()
        if extension_lower == "txt":
            if not isinstance(file_content, str):
                raise TypeError("TXT file content must be a string.")
            return self.parse_text(file_content)
        elif extension_lower == "md":
            if not isinstance(file_content, str):
                raise TypeError("Markdown file content must be a string.")
            return self.parse_markdown(file_content)
        elif extension_lower == "pdf":
            if not isinstance(file_content, bytes):
                raise TypeError("PDF file content must be bytes.")
            return self.parse_pdf(file_content)
        elif extension_lower == "docx":
            if not isinstance(file_content, bytes):
                raise TypeError("DOCX file content must be bytes.")
            return self.parse_docx(file_content)
        else:
            raise ValueError(f"Unsupported file extension: {file_extension}")
