# Scripts Directory

This directory contains utility scripts for the ontologic-api project.

## Current Scripts

### API Testing & Documentation
- `check_endpoints.py` - Script to verify API endpoint availability
- `check_exposed_endpoints.py` - Script to check exposed endpoints  
- `generate_api_docs.py` - Script to generate API documentation
- `test_endpoints.py` - Basic endpoint testing

### Database & Maintenance
- `migrate_db.py` - Database migration utilities
- `backup_cli.py` - Qdrant backup operations CLI
- `chat_cleanup_cli.py` - Chat history cleanup CLI
- `chat_maintenance_cli.py` - Chat maintenance operations

### Development Tools
- `setup_telemetry.py` - OpenTelemetry setup script
- `pre-commit-check.sh` - Pre-commit validation script

## Removed Scripts

**Removed 6 outdated scripts** that referenced non-existent endpoints or obsolete functionality:
- `test_llm_endpoints.py` - Referenced non-existent `ask_philosophy` endpoint
- `test_all_endpoints.py` - Comprehensive testing with outdated endpoints
- `test_pdf_context.py/.sh/.md` - PDF context testing with wrong endpoints
- `smoke_refactor.py` - Referenced non-existent dependency functions
- `test_timeouts.py` - Referenced non-existent `/query` endpoint

## Usage

Run scripts from the project root directory:

```bash
python scripts/script_name.py
```

For CLI tools with arguments:
```bash
python scripts/backup_cli.py --help
python scripts/chat_cleanup_cli.py --help
```