"""Spec for app.application.exceptions. The first six tests are copied word for word
from the boilerplate clone's `tests/unit/application/test_exceptions.py`
(`mcp-server-python-boilerplate @ 67c22ae`); the rest pin the module-level code
constants G6 adds on top of the clone's three classes.
"""

from app.application.exceptions import (
    CONFLICT,
    EXTERNAL_SERVICE_ERROR,
    NOT_FOUND,
    REFUSED,
    REPOSITORY_ERROR,
    VERIFY_FAILED,
    ApplicationError,
    ExternalServiceError,
    RepositoryError,
)


def test_application_error_defaults() -> None:
    err = ApplicationError("something failed")
    assert err.message == "something failed"
    assert err.code == "APPLICATION_ERROR"
    assert str(err) == "something failed"


def test_application_error_custom_code() -> None:
    err = ApplicationError("custom", code="CUSTOM")
    assert err.code == "CUSTOM"


def test_external_service_error_defaults() -> None:
    err = ExternalServiceError("bad request")
    assert err.message == "bad request"
    assert err.code == "EXTERNAL_SERVICE_ERROR"


def test_external_service_error_custom_code() -> None:
    err = ExternalServiceError("timeout", code="TIMEOUT")
    assert err.code == "TIMEOUT"


def test_repository_error_defaults() -> None:
    err = RepositoryError("db failed")
    assert err.message == "db failed"
    assert err.code == "REPOSITORY_ERROR"


def test_repository_error_custom_code() -> None:
    err = RepositoryError("constraint", code="CONSTRAINT")
    assert err.code == "CONSTRAINT"


# ---- the module-level code constants (G6 addition over the clone's three classes) ----


def test_repository_error_default_code_constant() -> None:
    assert REPOSITORY_ERROR == "REPOSITORY_ERROR"
    assert RepositoryError("x").code == REPOSITORY_ERROR


def test_external_service_error_default_code_constant() -> None:
    assert EXTERNAL_SERVICE_ERROR == "EXTERNAL_SERVICE_ERROR"
    assert ExternalServiceError("x").code == EXTERNAL_SERVICE_ERROR


def test_conflict_code_constant() -> None:
    assert CONFLICT == "CONFLICT"
    assert ApplicationError("x", code=CONFLICT).code == "CONFLICT"


def test_verify_failed_code_constant() -> None:
    assert VERIFY_FAILED == "VERIFY_FAILED"
    assert ApplicationError("x", code=VERIFY_FAILED).code == "VERIFY_FAILED"


def test_not_found_code_constant() -> None:
    assert NOT_FOUND == "NOT_FOUND"
    assert ApplicationError("x", code=NOT_FOUND).code == "NOT_FOUND"


def test_refused_code_constant() -> None:
    assert REFUSED == "REFUSED"
    assert ApplicationError("x", code=REFUSED).code == "REFUSED"
