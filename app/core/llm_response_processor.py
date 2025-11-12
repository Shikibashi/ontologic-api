"""Centralized LLM response processing to eliminate code duplication."""

from typing import Any, Optional
import re
import html


class LLMResponseProcessor:
    """Handles different LLM response formats consistently across the codebase."""

    @staticmethod
    def extract_content(response: Any) -> str:
        """
        Extract text content from various LLM response formats.

        Args:
            response: LLM response in various formats

        Returns:
            Extracted text content

        Raises:
            ValueError: If no content can be extracted
        """
        if not response:
            raise ValueError("Response is None or empty")

        # Try different response formats in order of common usage
        if hasattr(response, 'message') and hasattr(response.message, 'content'):
            content = response.message.content.strip()
        elif hasattr(response, 'content'):
            content = response.content.strip()
        elif hasattr(response, 'text'):
            content = response.text.strip()
        elif hasattr(response, 'choices') and response.choices and hasattr(response.choices[0], 'text'):
            # Handle CompletionResponse format
            content = response.choices[0].text.strip()
        elif hasattr(response, 'choices') and response.choices and hasattr(response.choices[0], 'message'):
            # Handle ChatCompletionResponse format
            content = response.choices[0].message.content.strip()
        elif isinstance(response, str):
            content = response.strip()
        else:
            # Try to get string representation as fallback
            content = str(response).strip()

        if not content:
            raise ValueError("Extracted content is empty")

        # Apply input sanitization
        return LLMResponseProcessor._sanitize_content(content)

    @staticmethod
    def extract_content_with_think_tag_removal(response: Any) -> str:
        """
        Extract content and remove thinking tags if present.

        Args:
            response: LLM response that may contain </think> tags

        Returns:
            Cleaned text content
        """
        content = LLMResponseProcessor.extract_content(response)

        # Remove thinking tags if present
        if "</think>" in content:
            content = content.split("</think>")[1].strip()

        return content

    @staticmethod
    def extract_lines(response: Any, skip_empty: bool = True, skip_numbered: bool = True) -> list[str]:
        """
        Extract content as list of lines with filtering options.

        Args:
            response: LLM response
            skip_empty: Whether to skip empty lines
            skip_numbered: Whether to skip numbered/bulleted lines

        Returns:
            List of filtered lines
        """
        content = LLMResponseProcessor.extract_content(response)
        lines = content.split('\n')

        if skip_empty:
            lines = [line.strip() for line in lines if line.strip()]

        if skip_numbered:
            # Filter out lines that start with numbers, bullets, or dashes
            filtered_lines = []
            for line in lines:
                line = line.strip()
                if not line.startswith(('1.', '2.', '3.', '4.', '-', '*')):
                    filtered_lines.append(line)
            lines = filtered_lines

        return lines

    @staticmethod
    def validate_content_length(content: str, min_length: int = 50, max_length: int = 20000) -> None:
        """
        Validate content length requirements.

        Args:
            content: Content to validate
            min_length: Minimum required length
            max_length: Maximum allowed length

        Raises:
            ValueError: If content doesn't meet length requirements
        """
        if len(content) < min_length:
            raise ValueError(f"Content too short ({len(content)} chars, minimum {min_length})")

        if len(content) > max_length:
            raise ValueError(f"Content too long ({len(content)} chars, maximum {max_length})")

    @staticmethod
    def safe_extract_content(response: Any, fallback: str = "Content unavailable") -> str:
        """
        Safely extract content with fallback for error cases.

        Args:
            response: LLM response
            fallback: Fallback text if extraction fails

        Returns:
            Extracted content or fallback text
        """
        try:
            return LLMResponseProcessor.extract_content(response)
        except ValueError as e:
            # ValueError is expected for empty/invalid responses
            from app.core.logger import log

            log.warning(
                f"Failed to extract content from response (using fallback): {e}. "
                f"Response type: {type(response).__name__}"
            )
            return fallback
        except AttributeError as e:
            # AttributeError indicates unexpected response structure
            from app.core.logger import log

            log.warning(
                f"Response has unexpected structure (using fallback): {e}. "
                f"Response type: {type(response).__name__}, "
                f"Available attributes: {dir(response) if hasattr(response, '__dict__') else 'N/A'}"
            )
            return fallback
        except Exception as e:
            # Catch-all for unexpected errors
            from app.core.logger import log

            log.error(
                f"Unexpected error extracting content (using fallback): {e}. "
                f"Response type: {type(response).__name__}",
                exc_info=True
            )
            return fallback

    @staticmethod
    def _sanitize_content(content: str) -> str:
        """
        Sanitize content to remove potentially harmful or problematic text.

        Args:
            content: Raw text content to sanitize

        Returns:
            Sanitized content safe for processing
        """
        if not content:
            return content

        # Start with HTML entity decoding for proper text processing
        content = html.unescape(content)

        # Remove potentially dangerous content
        content = LLMResponseProcessor._remove_dangerous_patterns(content)

        # Normalize whitespace and control characters
        content = LLMResponseProcessor._normalize_whitespace(content)

        # Remove excessive repetition
        content = LLMResponseProcessor._reduce_repetition(content)

        # Validate final content
        content = LLMResponseProcessor._validate_sanitized_content(content)

        return content

    @staticmethod
    def _remove_dangerous_patterns(content: str) -> str:
        """Remove potentially dangerous patterns from content."""
        # Remove script-like patterns
        content = re.sub(r'<script.*?</script>', '', content, flags=re.IGNORECASE | re.DOTALL)

        # Remove potential code injection patterns
        dangerous_patterns = [
            r'eval\s*\(',                    # eval() calls
            r'exec\s*\(',                    # exec() calls
            r'__import__\s*\(',              # import calls
            r'os\.system\s*\(',              # system calls
            r'subprocess\.',                 # subprocess calls
            r'open\s*\(',                    # file operations
            r'file\s*\(',                    # file operations
        ]

        for pattern in dangerous_patterns:
            content = re.sub(pattern, '[FILTERED]', content, flags=re.IGNORECASE)

        return content

    @staticmethod
    def _normalize_whitespace(content: str) -> str:
        """Normalize whitespace and control characters."""
        # Replace multiple whitespace with single space
        content = re.sub(r'\s+', ' ', content)

        # Remove control characters except newlines and tabs
        content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', content)

        # Normalize line endings
        content = content.replace('\r\n', '\n').replace('\r', '\n')

        # Remove excessive consecutive newlines (more than 3)
        content = re.sub(r'\n{4,}', '\n\n\n', content)

        return content.strip()

    @staticmethod
    def _reduce_repetition(content: str) -> str:
        """Reduce excessive repetition in content."""
        # Remove repeated words (more than 5 consecutive identical words)
        content = re.sub(r'\b(\w+)(\s+\1){5,}', r'\1 \1 \1 [REPETITION_REDUCED]', content)

        # Remove repeated characters (more than 10 consecutive identical chars)
        content = re.sub(r'(.)\1{10,}', r'\1\1\1[CHARS_REDUCED]', content)

        # Remove repeated lines
        lines = content.split('\n')
        cleaned_lines = []
        prev_line = None
        repeat_count = 0

        for line in lines:
            stripped_line = line.strip()
            if stripped_line == prev_line and stripped_line:
                repeat_count += 1
                if repeat_count <= 2:  # Allow up to 2 consecutive identical lines
                    cleaned_lines.append(line)
                elif repeat_count == 3:
                    cleaned_lines.append('[LINES_REDUCED]')
            else:
                cleaned_lines.append(line)
                repeat_count = 0
            prev_line = stripped_line

        return '\n'.join(cleaned_lines)

    @staticmethod
    def _validate_sanitized_content(content: str) -> str:
        """Final validation and cleanup of sanitized content."""
        # Ensure content isn't too long after sanitization
        max_length = 100000  # 100K characters max
        if len(content) > max_length:
            content = content[:max_length] + '\n[CONTENT_TRUNCATED]'

        # Remove leading/trailing whitespace
        content = content.strip()

        # Ensure content ends properly (no dangling punctuation issues)
        if content and not content[-1] in '.!?':
            content = content.rstrip() + '.'

        return content

    @staticmethod
    def sanitize_extracted_content(content: str) -> str:
        """
        Public method for sanitizing already-extracted content.

        Args:
            content: Content to sanitize

        Returns:
            Sanitized content
        """
        return LLMResponseProcessor._sanitize_content(content)
