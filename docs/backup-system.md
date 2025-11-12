# Qdrant Backup System

The Qdrant Backup System provides functionality to backup collections from production Qdrant to local development environments, enabling developers to work with realistic data without affecting production systems.

## Features

- **Dual Client Management**: Manages connections to both production and local Qdrant instances
- **Selective Backup**: Backup specific collections or use pattern matching
- **Progress Tracking**: Real-time progress monitoring for backup operations
- **Integrity Validation**: Verify backup completeness and data integrity
- **Error Recovery**: Retry failed operations and repair corrupted backups
- **CLI and API**: Both command-line and REST API interfaces

## Configuration

### Environment Variables

```bash
# Production Qdrant (required)
QDRANT_API_KEY=your_production_api_key

# Optional overrides
QDRANT_PRODUCTION_URL=https://qdrant.ontologicai.com
QDRANT_LOCAL_URL=http://localhost:6333
QDRANT_LOCAL_API_KEY=optional_local_api_key
```

### Local Qdrant Setup

Ensure you have a local Qdrant instance running:

```bash
# Using Docker
docker run -p 6333:6333 qdrant/qdrant

# Or using Docker Compose
docker-compose up qdrant
```

## CLI Usage

### ⚡ Snapshot-Based Backup (Recommended)

For single collections, use the snapshot method for **optimal performance and reliability**:

```bash
# Backup a single collection using snapshots (RECOMMENDED)
python scripts/backup_cli.py snapshot "Aristotle"

# With target name
python scripts/backup_cli.py snapshot "Aristotle" --target "dev_Aristotle"

# With overwrite
python scripts/backup_cli.py snapshot "Aristotle" --overwrite
```

**Why snapshots are better:**
- ✅ **100x+ faster** for large collections (uses native Qdrant snapshot API)
- ✅ **Handles all vector types** automatically (dense + sparse vectors)
- ✅ **Preserves exact settings** (no configuration parsing needed)
- ✅ **More reliable** (atomic operation, no partial failures)
- ✅ **Production-proven** (Qdrant's official backup method)

**Example:** Backing up the Aristotle collection (12,840 points) takes ~3 minutes with snapshots vs. potentially hours with point-by-point backup.

### Basic Commands

```bash
# Check connection health
python scripts/backup_cli.py health

# List collections
python scripts/backup_cli.py list --source production
python scripts/backup_cli.py list --source local

# Get collection information
python scripts/backup_cli.py info "Aristotle" --source production
```

### Point-by-Point Backup (Legacy)

Use these methods for multiple collections or when snapshots aren't available:

```bash
# Backup all philosophy collections
python scripts/backup_cli.py backup

# Backup specific collections
python scripts/backup_cli.py backup --collections "Aristotle" "Kant" "Hume"

# Backup with pattern filtering
python scripts/backup_cli.py backup --filter "A*" --prefix "dev_"

# Backup with overwrite
python scripts/backup_cli.py backup --overwrite

# Validate backup integrity
python scripts/backup_cli.py validate "Aristotle" "Aristotle"
```

### Advanced Usage

```bash
# Backup all collections (including chat history)
python scripts/backup_cli.py backup --all

# Backup with custom prefix
python scripts/backup_cli.py backup --prefix "backup_2024_" --overwrite

# Validate with custom sample size
python scripts/backup_cli.py validate "Kant" "dev_Kant" --sample-size 500
```

## API Usage

### Health Check

```bash
curl http://localhost:8080/admin/backup/health
```

### List Collections

```bash
# Production collections
curl http://localhost:8080/admin/backup/collections/production

# Local collections
curl http://localhost:8080/admin/backup/collections/local
```

### Start Backup

```bash
# Backup all philosophy collections
curl -X POST http://localhost:8080/admin/backup/start \
  -H "Content-Type: application/json" \
  -d '{}'

# Backup specific collections
curl -X POST http://localhost:8080/admin/backup/start \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["Aristotle", "Kant"],
    "target_prefix": "dev_",
    "overwrite": true
  }'

# Selective backup with patterns
curl -X POST http://localhost:8080/admin/backup/start \
  -H "Content-Type: application/json" \
  -d '{
    "include_patterns": ["A*", "K*"],
    "exclude_patterns": ["*_test"],
    "overwrite": false
  }'
```

### Monitor Progress

```bash
# Get backup status
curl http://localhost:8080/admin/backup/status/{backup_id}
```

### Validate Backup

```bash
curl -X POST http://localhost:8080/admin/backup/validate \
  -H "Content-Type: application/json" \
  -d '{
    "source_collection": "Aristotle",
    "target_collection": "Aristotle",
    "sample_size": 100
  }'
```

## Common Workflows

### Initial Development Setup

1. **Check connections**:
   ```bash
   python scripts/backup_cli.py health
   ```

2. **List available collections**:
   ```bash
   python scripts/backup_cli.py list
   ```

3. **Backup all philosophy collections**:
   ```bash
   python scripts/backup_cli.py backup
   ```

4. **Validate the backup**:
   ```bash
   python scripts/backup_cli.py validate "Aristotle" "Aristotle"
   ```

### Selective Development Data

1. **Backup specific philosophers**:
   ```bash
   python scripts/backup_cli.py backup --collections "Aristotle" "Kant" "Nietzsche"
   ```

2. **Backup with development prefix**:
   ```bash
   python scripts/backup_cli.py backup --prefix "dev_" --overwrite
   ```

### Data Refresh

1. **Update existing collections**:
   ```bash
   python scripts/backup_cli.py backup --overwrite
   ```

2. **Validate after update**:
   ```bash
   python scripts/backup_cli.py validate "Aristotle" "Aristotle"
   ```

## Error Handling

The backup system includes comprehensive error handling:

- **Connection failures**: Automatic retry with exponential backoff
- **Partial failures**: Continue with remaining collections, report errors
- **Data integrity**: Validation checks ensure backup completeness
- **Recovery**: Repair operations for corrupted or incomplete backups

## Security Considerations

- **API Key Protection**: Production API keys are never logged or exposed
- **Local Access**: Backup endpoints are admin-only and should not be exposed publicly
- **Data Privacy**: Chat history collections are excluded from philosophy backups
- **Environment Isolation**: Clear separation between production and development data

## Troubleshooting

### Common Issues

1. **Connection Timeout**:
   - Check network connectivity to production Qdrant
   - Verify API key is correct and has necessary permissions
   - Increase timeout in configuration if needed

2. **Local Qdrant Not Running**:
   - Start local Qdrant instance: `docker run -p 6333:6333 qdrant/qdrant`
   - Check local URL configuration

3. **Backup Validation Fails**:
   - Check for network interruptions during backup
   - Verify collection configurations match
   - Use repair functionality to fix issues

4. **Permission Errors**:
   - Ensure API key has read access to production collections
   - Check local Qdrant permissions if using authentication

### Debug Mode

Enable debug logging for detailed troubleshooting:

```bash
export LOG_LEVEL=debug
python scripts/backup_cli.py backup
```

## Performance Considerations

- **Batch Size**: Default 1000 points per batch, configurable
- **Concurrent Operations**: Single-threaded to avoid overwhelming servers
- **Progress Tracking**: Minimal overhead, updates every batch
- **Memory Usage**: Streaming approach, low memory footprint
- **Network Optimization**: Compression and efficient serialization

## Limitations

- **Vector Data**: Full vector data is copied (can be large)
- **Real-time Sync**: Not designed for real-time synchronization
- **Cross-Version**: May have issues with different Qdrant versions
- **Partial Updates**: No incremental backup support yet