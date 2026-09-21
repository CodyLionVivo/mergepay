from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.config import settings
from app.github_client import (
    GITHUB_API_VERSION,
    MAX_CHECK_RUNS,
    MAX_FILES,
    CheckRunsTooLargeError,
    GitHubClient,
    GitHubError,
    GitHubForbiddenError,
    GitHubTransportError,
    GitHubUnauthorizedError,
    GitHubUnexpectedStatusError,
    InvalidPullRequestUrlError,
    PullRequestNotFoundError,
    PullRequestTooLargeError,
    parse_pull_request_url,
)

OWNER = "acme"
REPO = "demo"
PULL_NUMBER = 21
PULL_REQUEST_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PULL_NUMBER}"

PULL_PATH = f"/repos/{OWNER}/{REPO}/pulls/{PULL_NUMBER}"
FILES_PATH = f"{PULL_PATH}/files"

BASE_SHA = "b" * 40
HEAD_SHA = "h" * 40

# Incluye campos que GitHub devuelve y que nosotros descartamos, para
# comprobar que no se filtra el JSON completo.
PULL_REQUEST_PAYLOAD: dict[str, Any] = {
    "html_url": PULL_REQUEST_URL,
    "state": "open",
    "draft": False,
    "user": {"login": "octodev", "id": 4242},
    "base": {"ref": "main", "sha": BASE_SHA},
    "head": {
        "ref": "feat/example",
        "sha": HEAD_SHA,
        "repo": {"full_name": f"{OWNER}/{REPO}"},
    },
    "title": "campo que no debe aparecer",
    "body": "otro campo que no debe aparecer",
    "mergeable": True,
}

FILES_PAYLOAD: list[dict[str, Any]] = [
    {
        "filename": "app/main.py",
        "status": "modified",
        "additions": 3,
        "deletions": 1,
        "changes": 4,
        "patch": "@@ -1 +1 @@",
        "blob_url": "https://github.com/acme/demo/blob/abc/app/main.py",
    },
    {
        "filename": "tests/test_main.py",
        "status": "added",
        "additions": 10,
        "deletions": 0,
        "changes": 10,
        "patch": "@@ -0,0 +1,10 @@",
    },
]

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler, token: str | None = None) -> GitHubClient:
    return GitHubClient(token=token, transport=httpx.MockTransport(handler))


def file_item(index: int) -> dict[str, Any]:
    return {
        "filename": f"src/module_{index}.py",
        "status": "modified",
        "additions": 1,
        "deletions": 1,
        "changes": 2,
    }


def make_handler(
    pull_response: httpx.Response | None = None,
    first_page: list[dict[str, Any]] | None = None,
    second_page: list[dict[str, Any]] | None = None,
) -> Handler:
    """Handler que sirve el PR y sus archivos paginados."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == PULL_PATH:
            return pull_response or httpx.Response(200, json=PULL_REQUEST_PAYLOAD)

        if request.url.path == FILES_PATH:
            assert request.url.params["per_page"] == str(MAX_FILES)

            if request.url.params.get("page") == "2":
                return httpx.Response(200, json=second_page or [])

            return httpx.Response(
                200, json=FILES_PAYLOAD if first_page is None else first_page
            )

        raise AssertionError(f"ruta inesperada: {request.url.path}")

    return handler


# ─────────────────────────────────────────
# 1 a 5. Parseo de la URL.
# ─────────────────────────────────────────


def test_valid_url_is_accepted() -> None:
    ref = parse_pull_request_url(PULL_REQUEST_URL)

    assert ref.owner == OWNER
    assert ref.repo == REPO
    assert ref.pull_number == PULL_NUMBER


def test_url_parts_are_extracted() -> None:
    ref = parse_pull_request_url("https://github.com/octo-org/my.repo_1/pull/7")

    assert ref.owner == "octo-org"
    assert ref.repo == "my.repo_1"
    assert ref.pull_number == 7


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/acme/demo/pull/21",
        "https://example.com/acme/demo/pull/21",
        "https://github.com.evil.test/acme/demo/pull/21",
        "http://github.com/acme/demo/pull/21",
    ],
)
def test_other_domains_are_rejected(url: str) -> None:
    with pytest.raises(InvalidPullRequestUrlError):
        parse_pull_request_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/demo",
        "https://github.com/acme/demo/issues/21",
        "https://github.com/acme/demo/pulls/21",
        "https://github.com/acme/demo/commit/abc123",
    ],
)
def test_urls_without_pull_segment_are_rejected(url: str) -> None:
    with pytest.raises(InvalidPullRequestUrlError):
        parse_pull_request_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/demo/pull/abc",
        "https://github.com/acme/demo/pull/",
        "https://github.com/acme/demo/pull/-1",
        "https://github.com/acme/demo/pull/0",
        "https://github.com/acme/demo/pull/21.5",
    ],
)
def test_invalid_pull_numbers_are_rejected(url: str) -> None:
    with pytest.raises(InvalidPullRequestUrlError):
        parse_pull_request_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com//demo/pull/21",
        "https://github.com/acme//pull/21",
        "https://github.com/acme/demo/extra/pull/21",
    ],
)
def test_empty_owner_or_repo_is_rejected(url: str) -> None:
    with pytest.raises(InvalidPullRequestUrlError):
        parse_pull_request_url(url)


# ─────────────────────────────────────────
# 6. Metadatos del PR.
# ─────────────────────────────────────────


def test_get_pull_request_maps_github_json() -> None:
    with make_client(make_handler()) as client:
        summary = client.get_pull_request(parse_pull_request_url(PULL_REQUEST_URL))

    assert summary.owner == OWNER
    assert summary.repo == REPO
    assert summary.pull_number == PULL_NUMBER
    assert summary.html_url == PULL_REQUEST_URL
    assert summary.state == "open"
    assert summary.draft is False
    assert summary.author == "octodev"
    assert summary.base_ref == "main"
    assert summary.base_sha == BASE_SHA
    assert summary.head_ref == "feat/example"
    assert summary.head_sha == HEAD_SHA
    assert summary.head_repo_full_name == f"{OWNER}/{REPO}"

    # Nada del resto del JSON de GitHub sobrevive.
    assert set(summary.model_dump()) == {
        "owner",
        "repo",
        "pull_number",
        "html_url",
        "state",
        "draft",
        "author",
        "base_ref",
        "base_sha",
        "head_ref",
        "head_sha",
        "head_repo_full_name",
    }


# ─────────────────────────────────────────
# 7. Archivos del PR.
# ─────────────────────────────────────────


def test_list_pull_request_files_maps_github_json() -> None:
    with make_client(make_handler()) as client:
        files = client.list_pull_request_files(
            parse_pull_request_url(PULL_REQUEST_URL)
        )

    assert [file.filename for file in files] == ["app/main.py", "tests/test_main.py"]
    assert [file.status for file in files] == ["modified", "added"]
    assert [file.additions for file in files] == [3, 10]
    assert [file.deletions for file in files] == [1, 0]
    assert [file.changes for file in files] == [4, 10]

    # `patch` y `blob_url` se descartan.
    assert set(files[0].model_dump()) == {
        "filename",
        "status",
        "additions",
        "deletions",
        "changes",
        "previous_filename",
    }

    # Sin rename no hay ruta anterior.
    assert all(file.previous_filename is None for file in files)


def test_renamed_file_maps_previous_filename() -> None:
    renamed = {
        "filename": "tests/regression/test_login.py",
        "status": "renamed",
        "additions": 0,
        "deletions": 0,
        "changes": 0,
        "previous_filename": "tests/test_login.py",
    }

    with make_client(make_handler(first_page=[renamed, *FILES_PAYLOAD])) as client:
        files = client.list_pull_request_files(
            parse_pull_request_url(PULL_REQUEST_URL)
        )

    assert files[0].status == "renamed"
    assert files[0].filename == "tests/regression/test_login.py"
    assert files[0].previous_filename == "tests/test_login.py"

    # El resto sigue sin ruta anterior.
    assert files[1].previous_filename is None
    assert files[2].previous_filename is None


# ─────────────────────────────────────────
# 8. Inspeccion combinada.
# ─────────────────────────────────────────


def test_inspect_pull_request_combines_metadata_and_files() -> None:
    with make_client(make_handler()) as client:
        inspection = client.inspect_pull_request(PULL_REQUEST_URL)

    assert inspection.owner == OWNER
    assert inspection.repo == REPO
    assert inspection.pull_number == PULL_NUMBER
    assert inspection.head_sha == HEAD_SHA
    assert inspection.author == "octodev"

    assert len(inspection.files) == 2
    assert inspection.files[0].filename == "app/main.py"
    assert inspection.files[1].changes == 10


def test_inspect_pull_request_rejects_invalid_url() -> None:
    with make_client(make_handler()) as client:
        with pytest.raises(InvalidPullRequestUrlError):
            client.inspect_pull_request("https://example.com/acme/demo/pull/21")


# ─────────────────────────────────────────
# 9 a 12. Errores HTTP.
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (404, PullRequestNotFoundError),
        (401, GitHubUnauthorizedError),
        (403, GitHubForbiddenError),
        (500, GitHubUnexpectedStatusError),
        (422, GitHubUnexpectedStatusError),
    ],
)
def test_http_errors_raise_specific_exceptions(
    status_code: int, expected_error: type[Exception]
) -> None:
    handler = make_handler(pull_response=httpx.Response(status_code, json={}))

    with make_client(handler) as client:
        with pytest.raises(expected_error):
            client.inspect_pull_request(PULL_REQUEST_URL)


def test_error_message_never_contains_the_token() -> None:
    handler = make_handler(pull_response=httpx.Response(403, json={}))

    with make_client(handler, token="super-secret-token") as client:
        with pytest.raises(GitHubForbiddenError) as raised:
            client.inspect_pull_request(PULL_REQUEST_URL)

    assert "super-secret-token" not in str(raised.value)


# ─────────────────────────────────────────
# 13 y 14. Limite de archivos del MVP.
# ─────────────────────────────────────────


def test_exactly_100_files_with_empty_second_page_is_valid() -> None:
    full_page = [file_item(index) for index in range(MAX_FILES)]
    handler = make_handler(first_page=full_page, second_page=[])

    with make_client(handler) as client:
        files = client.list_pull_request_files(
            parse_pull_request_url(PULL_REQUEST_URL)
        )

    assert len(files) == MAX_FILES
    assert files[0].filename == "src/module_0.py"
    assert files[-1].filename == f"src/module_{MAX_FILES - 1}.py"


def test_more_than_100_files_raises_limit_error() -> None:
    full_page = [file_item(index) for index in range(MAX_FILES)]
    handler = make_handler(first_page=full_page, second_page=[file_item(MAX_FILES)])

    with make_client(handler) as client:
        with pytest.raises(PullRequestTooLargeError) as raised:
            client.list_pull_request_files(parse_pull_request_url(PULL_REQUEST_URL))

    assert str(raised.value) == "Pull request exceeds MergePay MVP file limit"


def test_second_page_is_not_requested_when_first_is_not_full() -> None:
    requested_pages: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == PULL_PATH:
            return httpx.Response(200, json=PULL_REQUEST_PAYLOAD)

        requested_pages.append(request.url.params.get("page"))

        return httpx.Response(200, json=FILES_PAYLOAD)

    with make_client(handler) as client:
        client.list_pull_request_files(parse_pull_request_url(PULL_REQUEST_URL))

    assert requested_pages == [None]


# ─────────────────────────────────────────
# Check runs.
# ─────────────────────────────────────────

CHECK_RUNS_PATH = f"/repos/{OWNER}/{REPO}/commits/{HEAD_SHA}/check-runs"

CHECK_RUNS_PAYLOAD: list[dict[str, Any]] = [
    {
        "name": "build",
        "status": "completed",
        "conclusion": "success",
        "head_sha": HEAD_SHA,
        "html_url": "https://github.com/acme/demo/runs/1",
        "id": 1,
        "output": {"title": "campo que no debe aparecer"},
    },
    {
        "name": "acceptance-tests",
        "status": "in_progress",
        "conclusion": None,
        "head_sha": HEAD_SHA,
        "html_url": None,
        "started_at": "2026-03-10T00:00:00Z",
    },
]


def check_run_item(index: int) -> dict[str, Any]:
    return {
        "name": f"check-{index}",
        "status": "completed",
        "conclusion": "success",
        "head_sha": HEAD_SHA,
        "html_url": None,
    }


def check_runs_handler(
    check_runs: list[dict[str, Any]],
    total_count: int | None = None,
    response: httpx.Response | None = None,
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if response is not None:
            return response

        return httpx.Response(
            200,
            json={
                "total_count": len(check_runs) if total_count is None else total_count,
                "check_runs": check_runs,
            },
        )

    return handler


def test_list_check_runs_maps_github_json() -> None:
    with make_client(check_runs_handler(CHECK_RUNS_PAYLOAD)) as client:
        runs = client.list_check_runs(
            parse_pull_request_url(PULL_REQUEST_URL), HEAD_SHA
        )

    assert [run.name for run in runs] == ["build", "acceptance-tests"]
    assert [run.status for run in runs] == ["completed", "in_progress"]
    assert [run.conclusion for run in runs] == ["success", None]
    assert all(run.head_sha == HEAD_SHA for run in runs)
    assert runs[0].html_url == "https://github.com/acme/demo/runs/1"
    assert runs[1].html_url is None

    # `id`, `output` y demas se descartan.
    assert set(runs[0].model_dump()) == {
        "name",
        "status",
        "conclusion",
        "head_sha",
        "html_url",
    }


def test_list_check_runs_uses_the_supplied_head_sha() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)

        return httpx.Response(200, json={"total_count": 0, "check_runs": []})

    other_sha = "f" * 40

    with make_client(handler) as client:
        client.list_check_runs(parse_pull_request_url(PULL_REQUEST_URL), other_sha)

    assert seen["path"] == f"/repos/{OWNER}/{REPO}/commits/{other_sha}/check-runs"
    assert seen["params"] == {"filter": "latest", "per_page": str(MAX_CHECK_RUNS)}


def test_exactly_100_check_runs_is_valid() -> None:
    full_page = [check_run_item(index) for index in range(MAX_CHECK_RUNS)]

    with make_client(check_runs_handler(full_page)) as client:
        runs = client.list_check_runs(
            parse_pull_request_url(PULL_REQUEST_URL), HEAD_SHA
        )

    assert len(runs) == MAX_CHECK_RUNS
    assert runs[-1].name == f"check-{MAX_CHECK_RUNS - 1}"


def test_more_than_100_check_runs_raises_limit_error() -> None:
    full_page = [check_run_item(index) for index in range(MAX_CHECK_RUNS)]
    handler = check_runs_handler(full_page, total_count=MAX_CHECK_RUNS + 1)

    with make_client(handler) as client:
        with pytest.raises(CheckRunsTooLargeError) as raised:
            client.list_check_runs(parse_pull_request_url(PULL_REQUEST_URL), HEAD_SHA)

    assert str(raised.value) == "Pull request exceeds MergePay MVP check run limit"


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (404, PullRequestNotFoundError),
        (401, GitHubUnauthorizedError),
        (403, GitHubForbiddenError),
        (500, GitHubUnexpectedStatusError),
    ],
)
def test_check_runs_http_errors_reuse_existing_exceptions(
    status_code: int, expected_error: type[Exception]
) -> None:
    handler = check_runs_handler([], response=httpx.Response(status_code, json={}))

    with make_client(handler) as client:
        with pytest.raises(expected_error):
            client.list_check_runs(parse_pull_request_url(PULL_REQUEST_URL), HEAD_SHA)


# ─────────────────────────────────────────
# Cabeceras y autenticacion.
# ─────────────────────────────────────────


def capture_headers(seen: dict[str, str]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)

        return httpx.Response(200, json=PULL_REQUEST_PAYLOAD)

    return handler


def test_required_headers_are_sent() -> None:
    seen: dict[str, str] = {}

    with make_client(capture_headers(seen)) as client:
        client.get_pull_request(parse_pull_request_url(PULL_REQUEST_URL))

    assert seen["accept"] == "application/vnd.github+json"
    assert seen["x-github-api-version"] == GITHUB_API_VERSION
    assert seen["user-agent"] == "MergePay"


def test_token_is_sent_as_bearer_when_configured() -> None:
    seen: dict[str, str] = {}

    with make_client(capture_headers(seen), token="secret-token") as client:
        client.get_pull_request(parse_pull_request_url(PULL_REQUEST_URL))

    assert seen["authorization"] == "Bearer secret-token"


def test_no_authorization_header_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "github_token", None)

    seen: dict[str, str] = {}

    with make_client(capture_headers(seen)) as client:
        client.get_pull_request(parse_pull_request_url(PULL_REQUEST_URL))

    assert "authorization" not in seen


# ─────────────────────────────────────────
# Fallos de transporte.
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "transport_error",
    [
        httpx.ConnectError("[Errno 11001] getaddrinfo failed"),
        httpx.ReadTimeout("timed out"),
        httpx.RemoteProtocolError("peer closed connection"),
    ],
    ids=["connect", "timeout", "protocol"],
)
def test_transport_failure_raises_github_transport_error(
    transport_error: httpx.RequestError,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise transport_error

    with make_client(handler) as client:
        with pytest.raises(GitHubTransportError):
            client.inspect_pull_request(PULL_REQUEST_URL)


def test_transport_error_is_a_github_error() -> None:
    # Las capas de arriba que ya capturan GitHubError lo cubren sin cambios.
    assert issubclass(GitHubTransportError, GitHubError)


def test_transport_error_never_leaks_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with make_client(handler, token="super-secret-token") as client:
        with pytest.raises(GitHubTransportError) as raised:
            client.get_branch_head_sha(OWNER, REPO, "main")

    assert "super-secret-token" not in repr(raised.value)

    # La excepcion de httpx lleva la Request (y su Authorization): no viaja.
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_http_errors_keep_their_existing_exceptions() -> None:
    # El parche de transporte no cambia como se tratan las respuestas HTTP.
    for status_code, expected in [
        (404, PullRequestNotFoundError),
        (401, GitHubUnauthorizedError),
        (403, GitHubForbiddenError),
        (500, GitHubUnexpectedStatusError),
    ]:
        handler = make_handler(pull_response=httpx.Response(status_code, json={}))

        with make_client(handler) as client:
            with pytest.raises(expected):
                client.inspect_pull_request(PULL_REQUEST_URL)
