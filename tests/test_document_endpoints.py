"""
Test suite for document upload, list, and delete endpoints.

Tests cover:
- File upload with validation (extension and magic bytes)
- File size limits
- Document listing with pagination
- Document deletion with authorization
- Cross-user isolation
"""

import pytest
import io
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.user_models import User
from contextlib import contextmanager


@pytest.fixture
def mock_qdrant_manager():
    """Mock QdrantManager for document operations."""
    manager = MagicMock()
    manager.qclient = AsyncMock()
    return manager


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    user = MagicMock(spec=User)
    user.id = "test-user-id"
    user.username = "testuser"
    user.email = "test@example.com"
    return user


@pytest.fixture
def valid_pdf_bytes():
    """Valid PDF file bytes with correct magic signature."""
    return b'%PDF-1.4\n%\xE2\xE3\xCF\xD3\n' + b'Sample PDF content' * 100


@pytest.fixture
def valid_txt_bytes():
    """Valid text file bytes."""
    return b'This is a test text file with some content.'


@pytest.fixture
def invalid_pdf_bytes():
    """Invalid PDF - wrong magic bytes."""
    return b'Not a PDF file' * 100


@contextmanager
def authenticated_client(test_client, mock_user):
    """Context manager to temporarily authenticate a test client."""
    from app.core.auth_config import current_active_user
    from app.core.dependencies import require_documents_enabled
    
    # Override dependencies
    test_client.app.dependency_overrides[current_active_user] = lambda: mock_user
    test_client.app.dependency_overrides[require_documents_enabled] = lambda: None
    
    try:
        yield test_client
    finally:
        # Clean up overrides
        if current_active_user in test_client.app.dependency_overrides:
            del test_client.app.dependency_overrides[current_active_user]
        if require_documents_enabled in test_client.app.dependency_overrides:
            del test_client.app.dependency_overrides[require_documents_enabled]


class TestDocumentUpload:
    """Tests for POST /documents/upload endpoint."""

    def test_upload_valid_pdf(self, test_client: TestClient, mock_qdrant_manager, mock_user, valid_pdf_bytes):
        """Test uploading a valid PDF file."""
        with authenticated_client(test_client, mock_user):
            # Mock successful upload
            mock_qdrant_manager.qclient.get_collection = AsyncMock(return_value=MagicMock())

            # Mock upload service
            with patch('app.router.documents.QdrantUploadService') as mock_service:
                mock_instance = mock_service.return_value
                mock_instance.upload_file = AsyncMock(return_value={
                    'status': 'success',
                    'file_id': 'test-file-id',
                    'filename': 'test.pdf',
                    'collection': 'testuser',
                    'chunks_uploaded': 5
                })

                response = test_client.post(
                    '/documents/upload',
                    files={'file': ('test.pdf', io.BytesIO(valid_pdf_bytes), 'application/pdf')}
                )

                assert response.status_code == 200
                data = response.json()
                assert data['status'] == 'success'
                assert data['file_id'] == 'test-file-id'
                assert data['filename'] == 'test.pdf'
                assert data['chunks_uploaded'] == 5

    def test_upload_missing_authentication(self, test_client: TestClient, valid_pdf_bytes):
        """Test upload fails without authentication."""
        # Don't override authentication - should fail with 401
        response = test_client.post(
            '/documents/upload',
            files={'file': ('test.pdf', io.BytesIO(valid_pdf_bytes), 'application/pdf')}
        )

        assert response.status_code == 401  # Unauthorized

    def test_upload_invalid_file_type(self, test_client: TestClient, mock_user):
        """Test upload rejects invalid file extensions."""
        with authenticated_client(test_client, mock_user):
            response = test_client.post(
                '/documents/upload',
                files={'file': ('test.exe', io.BytesIO(b'exe content'), 'application/octet-stream')}
            )

            assert response.status_code == 400
            response_data = response.json()
            # Check the actual error structure
            assert 'detail' in response_data
            assert 'details' in response_data['detail']
            assert len(response_data['detail']['details']) > 0
            assert 'Unsupported file type' in response_data['detail']['details'][0]['message']

    def test_upload_magic_byte_validation_pdf(self, test_client: TestClient, mock_user, invalid_pdf_bytes):
        """Test magic byte validation rejects fake PDF files."""
        with authenticated_client(test_client, mock_user):
            response = test_client.post(
                '/documents/upload',
                files={'file': ('fake.pdf', io.BytesIO(invalid_pdf_bytes), 'application/pdf')}
            )

            assert response.status_code == 400
            response_data = response.json()
            # Check the actual error structure
            assert 'detail' in response_data
            assert 'details' in response_data['detail']
            assert len(response_data['detail']['details']) > 0
            assert 'content does not match expected PDF format' in response_data['detail']['details'][0]['message']

    def test_upload_file_size_limit(self, test_client: TestClient, mock_qdrant_manager, mock_user):
        """Test file size limit enforcement."""
        # Create a file larger than 50MB
        large_file = b'%PDF-1.4\n' + (b'x' * (51 * 1024 * 1024))

        with authenticated_client(test_client, mock_user):
            response = test_client.post(
                '/documents/upload',
                files={'file': ('large.pdf', io.BytesIO(large_file), 'application/pdf')}
            )

            assert response.status_code == 413
            response_data = response.json()
            # Check the actual error structure
            assert 'detail' in response_data
            assert 'details' in response_data['detail']
            assert len(response_data['detail']['details']) > 0
            assert 'File too large' in response_data['detail']['details'][0]['message']

    def test_upload_valid_txt_utf8(self, test_client: TestClient, mock_qdrant_manager, mock_user, valid_txt_bytes):
        """Test uploading valid UTF-8 text file."""
        with authenticated_client(test_client, mock_user):
            with patch('app.router.documents.QdrantUploadService') as mock_service:
                mock_instance = mock_service.return_value
                mock_instance.upload_file = AsyncMock(return_value={
                    'status': 'success',
                    'file_id': 'test-txt-id',
                    'filename': 'test.txt',
                    'collection': 'testuser',
                    'chunks_uploaded': 1
                })

                response = test_client.post(
                    '/documents/upload',
                    files={'file': ('test.txt', io.BytesIO(valid_txt_bytes), 'text/plain')}
                )

                assert response.status_code == 200
                data = response.json()
                assert data['filename'] == 'test.txt'


class TestDocumentList:
    """Tests for GET /documents/list endpoint."""

    def test_list_documents_success(self, test_client: TestClient, mock_qdrant_manager, mock_user):
        """Test listing user documents."""
        with authenticated_client(test_client, mock_user), \
             patch('app.router.documents.check_collection_exists') as mock_check:
            
            # Mock collection exists
            from app.core.qdrant_helpers import CollectionCheckResult
            mock_check.return_value = CollectionCheckResult.EXISTS

            # Mock scroll results
            mock_point = MagicMock()
            mock_point.payload = {
                'file_id': 'file-123',
                'filename': 'test.pdf',
                'document_type': 'pdf',
                'uploaded_at': '2025-01-01T00:00:00',
                'title': 'Test Document'
            }
            mock_qdrant_manager.qclient.scroll = AsyncMock(return_value=([mock_point], None))

            response = test_client.get(
                '/documents/list',
                params={'limit': 20, 'offset': 0}
            )

            assert response.status_code == 200
            data = response.json()
            assert data['total'] == 1
            assert len(data['documents']) == 1
            assert data['documents'][0]['file_id'] == 'file-123'

    def test_list_no_documents(self, test_client: TestClient, mock_qdrant_manager, mock_user):
        """Test listing when user has no documents."""
        with authenticated_client(test_client, mock_user), \
             patch('app.router.documents.check_collection_exists') as mock_check:
            
            # Mock collection doesn't exist
            from app.core.qdrant_helpers import CollectionCheckResult
            mock_check.return_value = CollectionCheckResult.NOT_FOUND

            response = test_client.get(
                '/documents/list',
                params={'limit': 20, 'offset': 0}
            )

            assert response.status_code == 200
            data = response.json()
            assert data['total'] == 0
            assert len(data['documents']) == 0

    def test_list_pagination(self, test_client: TestClient, mock_qdrant_manager, mock_user):
        """Test document list pagination."""
        with authenticated_client(test_client, mock_user), \
             patch('app.router.documents.check_collection_exists') as mock_check:
            
            # Mock collection exists
            from app.core.qdrant_helpers import CollectionCheckResult
            mock_check.return_value = CollectionCheckResult.EXISTS

            # Mock multiple documents
            mock_points = [
                MagicMock(payload={
                    'file_id': f'file-{i}',
                    'filename': f'test{i}.pdf',
                    'document_type': 'pdf',
                    'uploaded_at': '2025-01-01T00:00:00'
                })
                for i in range(10)
            ]
            mock_qdrant_manager.qclient.scroll = AsyncMock(return_value=(mock_points, None))

            response = test_client.get(
                '/documents/list',
                params={'limit': 5, 'offset': 0}
            )

            assert response.status_code == 200
            data = response.json()
            assert data['total'] == 10
            assert len(data['documents']) == 5  # Limited to 5


class TestDocumentDelete:
    """Tests for DELETE /documents/{file_id} endpoint."""

    def test_delete_document_success(self, test_client: TestClient, mock_qdrant_manager, mock_user):
        """Test successful document deletion."""
        with authenticated_client(test_client, mock_user), \
             patch('app.router.documents.check_collection_exists') as mock_check:
            
            # Mock collection exists
            from app.core.qdrant_helpers import CollectionCheckResult
            mock_check.return_value = CollectionCheckResult.EXISTS

            # Mock scroll results
            mock_point = MagicMock()
            mock_point.id = 'point-123'
            mock_qdrant_manager.qclient.scroll = AsyncMock(return_value=([mock_point], None))

            # Mock delete
            mock_qdrant_manager.qclient.delete = AsyncMock()

            response = test_client.delete('/documents/file-123')

            assert response.status_code == 200
            data = response.json()
            assert data['status'] == 'success'
            assert data['file_id'] == 'file-123'
            assert data['chunks_deleted'] == 1

    def test_delete_document_not_found(self, test_client: TestClient, mock_qdrant_manager, mock_user):
        """Test deleting non-existent document."""
        with authenticated_client(test_client, mock_user), \
             patch('app.router.documents.check_collection_exists') as mock_check:
            
            # Mock collection exists but no matching points
            from app.core.qdrant_helpers import CollectionCheckResult
            mock_check.return_value = CollectionCheckResult.EXISTS
            mock_qdrant_manager.qclient.scroll = AsyncMock(return_value=([], None))

            response = test_client.delete('/documents/nonexistent')

            assert response.status_code == 404
            response_data = response.json()
            # Check the actual error structure
            if 'detail' in response_data and isinstance(response_data['detail'], dict):
                assert 'not found' in response_data['detail']['message'].lower()
            else:
                assert 'not found' in str(response_data).lower()

    def test_delete_no_collection(self, test_client: TestClient, mock_qdrant_manager, mock_user):
        """Test deleting when user has no documents collection."""
        with authenticated_client(test_client, mock_user), \
             patch('app.router.documents.check_collection_exists') as mock_check:
            
            # Mock collection doesn't exist
            from app.core.qdrant_helpers import CollectionCheckResult
            mock_check.return_value = CollectionCheckResult.NOT_FOUND

            response = test_client.delete('/documents/file-123')

            assert response.status_code == 404


class TestCrossUserIsolation:
    """Tests for cross-user data isolation."""

    def test_user_cannot_list_other_users_documents(self, test_client: TestClient, mock_qdrant_manager):
        """Test that users can only list their own documents."""
        # Create a user B mock
        user_b = MagicMock(spec=User)
        user_b.id = "user-b-id"
        user_b.username = "userB"
        user_b.email = "userb@example.com"
        
        with authenticated_client(test_client, user_b), \
             patch('app.router.documents.check_collection_exists') as mock_check:
            
            # Mock collection doesn't exist for userB (they have no documents)
            from app.core.qdrant_helpers import CollectionCheckResult
            mock_check.return_value = CollectionCheckResult.NOT_FOUND

            response = test_client.get(
                '/documents/list',
                params={'limit': 20, 'offset': 0}
            )

            # UserB should see no documents (since they query their own collection)
            assert response.status_code == 200
            data = response.json()
            assert data['total'] == 0

    def test_user_cannot_delete_other_users_documents(self, test_client: TestClient, mock_qdrant_manager):
        """Test that delete operation includes username filter."""
        # Create a user B mock
        user_b = MagicMock(spec=User)
        user_b.id = "user-b-id"
        user_b.username = "userB"
        user_b.email = "userb@example.com"
        
        with authenticated_client(test_client, user_b), \
             patch('app.router.documents.check_collection_exists') as mock_check:
            
            # Mock collection exists but no matching points for userB
            from app.core.qdrant_helpers import CollectionCheckResult
            mock_check.return_value = CollectionCheckResult.EXISTS
            mock_qdrant_manager.qclient.scroll = AsyncMock(return_value=([], None))

            response = test_client.delete('/documents/file-belonging-to-userA')

            # Should fail because the scroll with username filter returns nothing
            assert response.status_code == 404
            response_data = response.json()
            # Check the actual error structure
            if 'detail' in response_data and isinstance(response_data['detail'], dict):
                assert 'not found' in response_data['detail']['message'].lower()
            else:
                assert 'not found' in str(response_data).lower()


class TestDocumentSubscriptionEnforcement:
    """Tests for subscription-based access control on document endpoints."""

    @pytest.fixture
    def mock_subscription_manager(self):
        """Mock subscription manager that denies access."""
        manager = AsyncMock()
        manager.check_api_access = AsyncMock(return_value=False)
        manager.track_api_usage = AsyncMock()
        return manager

    @pytest.fixture
    def mock_subscription_manager_allowed(self):
        """Mock subscription manager that allows access."""
        manager = AsyncMock()
        manager.check_api_access = AsyncMock(return_value=True)
        manager.track_api_usage = AsyncMock()
        return manager

    def test_upload_denied_when_subscription_disallows(
        self, test_client: TestClient, mock_user, valid_pdf_bytes, mock_subscription_manager
    ):
        """Test upload returns 403 when subscription tier disallows uploads."""
        from app.core.dependencies import get_subscription_manager

        with authenticated_client(test_client, mock_user):
            # Override subscription manager to deny access
            test_client.app.dependency_overrides[get_subscription_manager] = lambda: mock_subscription_manager

            try:
                with patch('app.config.settings.get_settings') as mock_settings:
                    settings_instance = MagicMock()
                    settings_instance.payments_enabled = True
                    mock_settings.return_value = settings_instance

                    response = test_client.post(
                        '/documents/upload',
                        files={'file': ('test.pdf', io.BytesIO(valid_pdf_bytes), 'application/pdf')}
                    )

                    assert response.status_code == 403
                    # Verify subscription check was called
                    mock_subscription_manager.check_api_access.assert_called_once()
            finally:
                if get_subscription_manager in test_client.app.dependency_overrides:
                    del test_client.app.dependency_overrides[get_subscription_manager]

    def test_upload_tracks_usage_on_success(
        self, test_client: TestClient, mock_user, valid_pdf_bytes, mock_subscription_manager_allowed
    ):
        """Test upload tracks subscription usage after successful upload."""
        from app.core.dependencies import get_subscription_manager

        with authenticated_client(test_client, mock_user):
            # Override subscription manager to allow access
            test_client.app.dependency_overrides[get_subscription_manager] = lambda: mock_subscription_manager_allowed

            try:
                with patch('app.config.settings.get_settings') as mock_settings, \
                     patch('app.router.documents.QdrantUploadService') as mock_service:

                    settings_instance = MagicMock()
                    settings_instance.payments_enabled = True
                    settings_instance.max_upload_size_mb = 50
                    mock_settings.return_value = settings_instance

                    # Mock successful upload
                    mock_instance = mock_service.return_value
                    mock_instance.upload_file = AsyncMock(return_value={
                        'status': 'success',
                        'file_id': 'test-file-id',
                        'filename': 'test.pdf',
                        'collection': 'testuser',
                        'chunks_uploaded': 5
                    })

                    response = test_client.post(
                        '/documents/upload',
                        files={'file': ('test.pdf', io.BytesIO(valid_pdf_bytes), 'application/pdf')}
                    )

                    assert response.status_code == 200
                    # Verify usage tracking was attempted
                    mock_subscription_manager_allowed.track_api_usage.assert_called_once()
            finally:
                if get_subscription_manager in test_client.app.dependency_overrides:
                    del test_client.app.dependency_overrides[get_subscription_manager]

    def test_list_denied_when_subscription_disallows(
        self, test_client: TestClient, mock_user, mock_subscription_manager
    ):
        """Test list returns 403 when subscription tier disallows listing."""
        from app.core.dependencies import get_subscription_manager

        with authenticated_client(test_client, mock_user):
            # Override subscription manager to deny access
            test_client.app.dependency_overrides[get_subscription_manager] = lambda: mock_subscription_manager

            try:
                with patch('app.config.settings.get_settings') as mock_settings:
                    settings_instance = MagicMock()
                    settings_instance.payments_enabled = True
                    mock_settings.return_value = settings_instance

                    response = test_client.get(
                        '/documents/list',
                        params={'limit': 20, 'offset': 0}
                    )

                    assert response.status_code == 403
                    # Verify subscription check was called
                    mock_subscription_manager.check_api_access.assert_called_once()
            finally:
                if get_subscription_manager in test_client.app.dependency_overrides:
                    del test_client.app.dependency_overrides[get_subscription_manager]

    def test_delete_denied_when_subscription_disallows(
        self, test_client: TestClient, mock_user, mock_subscription_manager
    ):
        """Test delete returns 403 when subscription tier disallows deletion."""
        from app.core.dependencies import get_subscription_manager

        with authenticated_client(test_client, mock_user):
            # Override subscription manager to deny access
            test_client.app.dependency_overrides[get_subscription_manager] = lambda: mock_subscription_manager

            try:
                with patch('app.config.settings.get_settings') as mock_settings:
                    settings_instance = MagicMock()
                    settings_instance.payments_enabled = True
                    mock_settings.return_value = settings_instance

                    response = test_client.delete('/documents/file-123')

                    assert response.status_code == 403
                    # Verify subscription check was called
                    mock_subscription_manager.check_api_access.assert_called_once()
            finally:
                if get_subscription_manager in test_client.app.dependency_overrides:
                    del test_client.app.dependency_overrides[get_subscription_manager]

    def test_upload_token_estimation_accuracy(
        self, test_client: TestClient, mock_user, mock_subscription_manager_allowed
    ):
        """Test upload token estimation is accurate and doesn't build large strings."""
        from app.core.dependencies import get_subscription_manager
        from app.core.constants import CHARS_PER_TOKEN_ESTIMATE

        # Create a known-size text file (1000 chars)
        test_content = b"X" * 1000
        expected_tokens = 1000 / CHARS_PER_TOKEN_ESTIMATE  # ~250 tokens

        with authenticated_client(test_client, mock_user):
            # Override subscription manager to allow access
            test_client.app.dependency_overrides[get_subscription_manager] = lambda: mock_subscription_manager_allowed

            try:
                with patch('app.config.settings.get_settings') as mock_settings, \
                     patch('app.router.documents.QdrantUploadService') as mock_service:

                    settings_instance = MagicMock()
                    settings_instance.payments_enabled = True
                    settings_instance.max_upload_size_mb = 50
                    mock_settings.return_value = settings_instance

                    # Mock successful upload
                    mock_instance = mock_service.return_value
                    mock_instance.upload_file = AsyncMock(return_value={
                        'status': 'success',
                        'file_id': 'test-file-id',
                        'filename': 'test.txt',
                        'collection': 'testuser',
                        'chunks_uploaded': 1
                    })

                    response = test_client.post(
                        '/documents/upload',
                        files={'file': ('test.txt', io.BytesIO(test_content), 'text/plain')}
                    )

                    assert response.status_code == 200

                    # Verify track_api_usage was called with correct token count (within ±10%)
                    mock_subscription_manager_allowed.track_api_usage.assert_called_once()
                    call_args = mock_subscription_manager_allowed.track_api_usage.call_args
                    tokens_used = call_args.kwargs['tokens_used']

                    # Assert tokens are within ±10% of expected
                    assert abs(tokens_used - expected_tokens) / expected_tokens <= 0.10, \
                        f"Token estimation {tokens_used} not within ±10% of expected {expected_tokens}"

                    # Assert tokens are positive and reasonable
                    assert tokens_used > 0, "Tokens used should be greater than 0"
                    assert tokens_used < 1000, "Tokens used should be less than character count"
            finally:
                if get_subscription_manager in test_client.app.dependency_overrides:
                    del test_client.app.dependency_overrides[get_subscription_manager]
