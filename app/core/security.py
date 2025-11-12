import os
import re
import subprocess
from typing import Dict, Any, List, Optional
from pathlib import Path

from app.core.logger import log


class SecurityManager:
    """Security utilities and validation for the application."""

    # Sensitive keys that should never be logged or exposed
    SENSITIVE_KEYS = {
        'password', 'secret', 'key', 'token', 'auth', 'credential',
        'private', 'secure', 'confidential', 'api_key', 'client_secret'
    }

    # Centralized secret configuration
    REQUIRED_SECRETS = ['QDRANT_API_KEY']  # Required in all environments
    PRODUCTION_SECRETS = ['SESSION_SECRET', 'JWT_SECRET', 'QDRANT_API_KEY', 'ONTOLOGIC_DB_URL']  # Required in production

    # Placeholder values that are insecure and must be changed in production
    INSECURE_PLACEHOLDERS = {
        'CHANGE_THIS_IN_PRODUCTION',
        'changeme',
        'secret',
        'password',
        'default',
    }

    @staticmethod
    def validate_temperature(temperature: float) -> float:
        """Validate and clamp temperature to safe bounds."""
        if not isinstance(temperature, (int, float)):
            raise ValueError("Temperature must be a number")

        # Clamp to valid range
        temperature = max(0.0, min(1.0, float(temperature)))
        return temperature

    @staticmethod
    def validate_limit(limit: int, max_limit: int = 100) -> int:
        """Validate and clamp limit parameters."""
        if not isinstance(limit, int):
            raise ValueError("Limit must be an integer")

        if limit < 1:
            return 1
        if limit > max_limit:
            return max_limit

        return limit

    @staticmethod
    def scrub_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive information from metadata before logging/storage."""
        if not isinstance(data, dict):
            return data

        scrubbed = {}
        for key, value in data.items():
            key_lower = str(key).lower()

            # Check if key contains sensitive terms
            is_sensitive = any(sensitive in key_lower for sensitive in SecurityManager.SENSITIVE_KEYS)

            if is_sensitive:
                scrubbed[key] = "[REDACTED]"
            elif isinstance(value, dict):
                scrubbed[key] = SecurityManager.scrub_metadata(value)
            elif isinstance(value, list):
                scrubbed[key] = [
                    SecurityManager.scrub_metadata(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                scrubbed[key] = value

        return scrubbed

    @staticmethod
    def validate_secret_strength(secret_name: str, secret_value: str, min_length: int = 32) -> tuple[bool, str]:
        """
        Validate that a secret meets minimum security requirements.

        Args:
            secret_name: Name of the secret (for error messages)
            secret_value: The secret value to validate
            min_length: Minimum required length (default 32 bytes)

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check minimum length
        if len(secret_value) < min_length:
            return False, f"{secret_name} must be at least {min_length} characters (got {len(secret_value)})"

        # Check against insecure placeholders (whole-word matching)
        import re
        value_lower = secret_value.lower()
        for placeholder in SecurityManager.INSECURE_PLACEHOLDERS:
            # Use word boundary matching to avoid false positives
            pattern = r'\b' + re.escape(placeholder.lower()) + r'\b'
            if re.search(pattern, value_lower):
                return False, f"{secret_name} contains insecure placeholder value: '{placeholder}'"

        return True, ""

    @staticmethod
    def validate_env_secrets(require_all_in_production: bool = False) -> Dict[str, bool]:
        """
        Validate that required environment secrets are configured.

        Args:
            require_all_in_production: If True, treats all secrets as required and raises
                                      an exception if any are missing (for production environments)

        Returns:
            Dictionary mapping secret names to validation status (True if configured)

        Raises:
            RuntimeError: If require_all_in_production=True and any secrets are missing
        """
        # In production mode, use production secret list
        if require_all_in_production:
            all_secrets = SecurityManager.PRODUCTION_SECRETS
            validation_results = {}
            missing_secrets = []
            weak_secrets = []

            for secret in all_secrets:
                value = os.environ.get(secret)
                is_present = bool(value and len(value.strip()) > 0)

                if not is_present:
                    validation_results[secret] = False
                    missing_secrets.append(secret)
                    log.warning(f"Secret validation: {secret} - ✗ missing")
                    continue

                # For JWT_SECRET and SESSION_SECRET, validate strength
                if secret in ['JWT_SECRET', 'SESSION_SECRET']:
                    is_strong, error_msg = SecurityManager.validate_secret_strength(secret, value)
                    if not is_strong:
                        validation_results[secret] = False
                        weak_secrets.append(f"{secret}: {error_msg}")
                        log.error(f"Secret validation: {secret} - ✗ {error_msg}")
                    else:
                        validation_results[secret] = True
                        log.debug(f"Secret validation: {secret} - ✓ configured (length: {len(value)})")
                else:
                    validation_results[secret] = True
                    log.debug(f"Secret validation: {secret} - ✓ configured")

            # Summary logging
            configured_count = sum(validation_results.values())
            total_count = len(validation_results)
            log.info(f"Secret validation complete: {configured_count}/{total_count} secrets configured")

            # Fail if any secrets are missing or weak in production
            errors = []
            if missing_secrets:
                errors.append(f"Missing secrets: {', '.join(missing_secrets)}")
            if weak_secrets:
                errors.append(f"Weak/insecure secrets: {'; '.join(weak_secrets)}")

            if errors:
                error_msg = f"Production environment requires all secrets to be properly configured. {' | '.join(errors)}"
                log.error(error_msg)
                raise RuntimeError(error_msg)
        else:
            # Development mode - original behavior with enhanced logging
            validation_results = {}
            # In development, check both required and optional secrets but only warn for required ones
            all_secrets = list(set(SecurityManager.REQUIRED_SECRETS + SecurityManager.PRODUCTION_SECRETS))

            for secret in all_secrets:
                value = os.environ.get(secret)
                is_valid = bool(value and len(value.strip()) > 0)
                validation_results[secret] = is_valid

                # Log validation results (scrubbed - only showing presence/absence)
                status = "✓ configured" if is_valid else "✗ missing"
                is_required = secret in SecurityManager.REQUIRED_SECRETS

                if is_valid:
                    log.debug(f"Secret validation: {secret} - {status}")
                else:
                    if is_required:
                        log.warning(f"Required secret {secret} is not configured")
                    else:
                        log.debug(f"Optional secret {secret} is not configured")

            # Summary logging
            configured_count = sum(validation_results.values())
            total_count = len(validation_results)
            log.info(f"Secret validation complete: {configured_count}/{total_count} secrets configured")

        return validation_results

    @staticmethod
    def safe_subprocess_run(
        command: List[str],
        timeout: int = 30,
        allowed_commands: Optional[List[str]] = None
    ) -> subprocess.CompletedProcess:
        """
        Safely run subprocess commands with validation and timeouts.

        Args:
            command: Command to run as list of strings
            timeout: Timeout in seconds
            allowed_commands: Whitelist of allowed command prefixes

        Returns:
            CompletedProcess result

        Raises:
            SecurityError: If command is not allowed or contains dangerous characters
            subprocess.TimeoutExpired: If command times out
        """
        if not command or not isinstance(command, list):
            raise ValueError("Command must be a non-empty list")

        base_command = command[0]

        # Default allowed commands for the application
        if allowed_commands is None:
            allowed_commands = [
                'python', 'pip', 'openspec', 'pytest',
                'git', 'curl', 'wget', 'ls', 'cat', 'head', 'tail'
            ]

        # Check if command is allowed
        if not any(base_command.startswith(allowed) for allowed in allowed_commands):
            raise SecurityError(f"Command '{base_command}' is not in allowed list: {allowed_commands}")

        # Validate and sanitize command arguments
        sanitized_command = []
        # SECURITY: Reject arguments containing shell metacharacters to prevent command injection.
        # Characters like ; | & ` $ ( ) { } can be used to chain commands or execute subshells.
        for arg in command:
            # Remove potentially dangerous characters
            if re.search(r'[;&|`$(){}]', arg):
                log.error(f"Dangerous characters detected in command argument: {arg}")
                raise SecurityError(f"Command argument contains dangerous shell metacharacters: {arg}")
            sanitized_command.append(str(arg))

        try:
            result = subprocess.run(
                sanitized_command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False  # Don't raise on non-zero exit
            )

            # Log command execution (without sensitive data)
            safe_command = SecurityManager._sanitize_command_for_logging(sanitized_command)
            log.info(f"Executed command: {' '.join(safe_command)} (exit code: {result.returncode})")

            return result

        except subprocess.TimeoutExpired as e:
            log.error(f"Command timed out after {timeout}s: {' '.join(command[:2])}")
            raise

    @staticmethod
    def _sanitize_command_for_logging(command: List[str]) -> List[str]:
        """Remove sensitive information from command for logging."""
        sanitized = []

        for arg in command:
            # Check for potential secrets in arguments
            arg_lower = arg.lower()
            if any(sensitive in arg_lower for sensitive in SecurityManager.SENSITIVE_KEYS):
                sanitized.append("[REDACTED]")
            elif len(arg) > 20 and not arg.startswith('-'):
                # Long arguments that might be tokens/secrets
                sanitized.append(f"{arg[:10]}...[TRUNCATED]")
            else:
                sanitized.append(arg)

        return sanitized

    @staticmethod
    def validate_file_path(file_path: str, allowed_extensions: Optional[List[str]] = None) -> bool:
        """
        Validate file paths for security.

        Args:
            file_path: Path to validate
            allowed_extensions: List of allowed file extensions

        Returns:
            True if path is safe
        """
        path = Path(file_path)

        # Check for path traversal attempts
        if '..' in str(path) or str(path).startswith('/'):
            log.warning(f"Potential path traversal attempt: {file_path}")
            return False

        # Check file extension if whitelist provided
        if allowed_extensions:
            if not any(str(path).endswith(ext) for ext in allowed_extensions):
                log.warning(f"File extension not allowed: {file_path}")
                return False

        return True

    @staticmethod
    def get_security_headers() -> Dict[str, str]:
        """
        Get recommended security headers for API responses.

        NOTE: Headers optimized for API-only service (no browser UI).
        Stricter policies are used to minimize attack surface.
        """
        return {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            # Stricter referrer policy for API-only service
            "Referrer-Policy": "no-referrer",
            # Stricter CSP for API-only service (no resources needed)
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        }


class SecurityError(Exception):
    """Custom exception for security-related errors."""
    pass


# Global security manager instance
security_manager = SecurityManager()
