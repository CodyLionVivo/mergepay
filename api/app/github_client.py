"""Capa de lectura de pull requests de GitHub.

Solo lee: resuelve la URL de un PR, pide sus metadatos y la lista de archivos
tocados, y los traduce a los schemas de MergePay. No persiste nada ni decide
nada sobre el bounty.
"""

import re
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

import httpx

from app.config import settings
from app.schemas import (
    GitHubCheckRun,
    PullRequestFile,
    PullRequestInspection,
    PullRequestRef,
    PullRequestSummary,
)

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"
USER_AGENT = "MergePay"

REQUEST_TIMEOUT_SECONDS = 10.0

# Topes del MVP. Coinciden con el maximo de per_page que acepta GitHub, asi que
# una sola pagina basta para el caso normal.
MAX_FILES = 100
MAX_CHECK_RUNS = 100

# Solo la forma canonica https://github.com/{owner}/{repo}/pull/{number}.
# Estos valores acaban formando la URL contra api.github.com, de modo que el
# patron es deliberadamente estrecho.
PULL_REQUEST_URL_PATTERN = re.compile(
    r"^https://github\.com"
    r"/(?P<owner>[A-Za-z0-9._-]+)"
    r"/(?P<repo>[A-Za-z0-9._-]+)"
    r"/pull/(?P<pull_number>[1-9][0-9]*)/?$"
)


class GitHubError(Exception):
    """Raiz de los errores de esta capa."""


class InvalidPullRequestUrlError(GitHubError):
    """La URL no es la de un pull request de github.com."""


class PullRequestNotFoundError(GitHubError):
    """GitHub respondio 404."""


class GitHubUnauthorizedError(GitHubError):
    """GitHub respondio 401."""


class GitHubForbiddenError(GitHubError):
    """GitHub respondio 403 (permisos o rate limit)."""


class GitHubUnexpectedStatusError(GitHubError):
    """GitHub respondio un codigo de error que no sabemos interpretar."""


class PullRequestTooLargeError(GitHubError):
    """El PR tiene mas archivos de los que soporta el MVP."""


class CheckRunsTooLargeError(GitHubError):
    """El commit tiene mas check runs de los que soporta el MVP."""


class BranchNotFoundError(GitHubError):
    """GitHub no encontro el repositorio o la rama pedidos."""


class GitHubTransportError(GitHubError):
    """No se llego a obtener respuesta de GitHub (red, DNS, timeout)."""


def parse_pull_request_url(pull_request_url: str) -> PullRequestRef:
    """Extrae owner, repo y numero de la URL de un pull request."""
    match = PULL_REQUEST_URL_PATTERN.match(pull_request_url.strip())

    if match is None:
        raise InvalidPullRequestUrlError(
            "Expected a URL of the form "
            "https://github.com/{owner}/{repo}/pull/{number}"
        )

    return PullRequestRef(
        owner=match.group("owner"),
        repo=match.group("repo"),
        pull_number=int(match.group("pull_number")),
    )


def build_headers(token: str | None) -> dict[str, str]:
    """Cabeceras de la API. El token solo viaja en Authorization."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": USER_AGENT,
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


class GitHubClient:
    """Cliente de solo lectura sobre la REST API de GitHub."""

    def __init__(
        self,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=GITHUB_API_URL,
            headers=build_headers(token if token is not None else settings.github_token),
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Hace la llamada y devuelve JSON ya decodificado.

        El objeto Response nunca sale de aqui: cada codigo de error se traduce
        a una excepcion propia. Los mensajes no incluyen el token ni el cuerpo
        de la respuesta.
        """
        try:
            response = self._client.get(path, params=params)
        except httpx.RequestError as error:
            # Solo fallos de transporte (conexion, DNS, timeouts...). Se corta
            # la cadena: la excepcion de httpx lleva la Request, y con ella
            # la cabecera Authorization.
            raise GitHubTransportError(
                f"GitHub request failed for {path}: {type(error).__name__}"
            ) from None

        if response.status_code == 404:
            raise PullRequestNotFoundError(f"GitHub returned 404 for {path}")

        if response.status_code == 401:
            raise GitHubUnauthorizedError(f"GitHub returned 401 for {path}")

        if response.status_code == 403:
            raise GitHubForbiddenError(f"GitHub returned 403 for {path}")

        if response.status_code >= 400:
            raise GitHubUnexpectedStatusError(
                f"GitHub returned HTTP {response.status_code} for {path}"
            )

        return response.json()

    def get_pull_request(self, ref: PullRequestRef) -> PullRequestSummary:
        payload = self._get(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.pull_number}")

        # `user` y `head.repo` pueden llegar nulos (cuenta borrada, fork
        # eliminado), por eso se leen con get en vez de indexar.
        user = payload.get("user") or {}
        base = payload.get("base") or {}
        head = payload.get("head") or {}
        head_repo = head.get("repo") or {}

        return PullRequestSummary(
            owner=ref.owner,
            repo=ref.repo,
            pull_number=ref.pull_number,
            html_url=payload.get("html_url"),
            state=payload.get("state"),
            draft=payload.get("draft"),
            author=user.get("login"),
            base_ref=base.get("ref"),
            base_sha=base.get("sha"),
            head_ref=head.get("ref"),
            head_sha=head.get("sha"),
            head_repo_full_name=head_repo.get("full_name"),
        )

    def list_pull_request_files(self, ref: PullRequestRef) -> list[PullRequestFile]:
        path = f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.pull_number}/files"

        files = [
            _to_file(item) for item in self._get(path, params={"per_page": MAX_FILES})
        ]

        if len(files) < MAX_FILES:
            return files

        # La primera pagina vino llena: puede que no haya mas, o puede que el PR
        # se salga del MVP. Solo la segunda pagina lo aclara.
        if self._get(path, params={"per_page": MAX_FILES, "page": 2}):
            raise PullRequestTooLargeError(
                "Pull request exceeds MergePay MVP file limit"
            )

        return files

    def list_check_runs(
        self, ref: PullRequestRef, head_sha: str
    ) -> list[GitHubCheckRun]:
        """Check runs del commit indicado, quedandose con el ultimo de cada uno.

        El SHA es el que nos pasan, no uno derivado aqui: el verifier evalua
        exactamente el commit que inspecciono.
        """
        payload = self._get(
            f"/repos/{ref.owner}/{ref.repo}/commits/{head_sha}/check-runs",
            params={"filter": "latest", "per_page": MAX_CHECK_RUNS},
        )

        items = payload.get("check_runs") or []
        total_count = payload.get("total_count", len(items))

        if total_count > MAX_CHECK_RUNS or len(items) > MAX_CHECK_RUNS:
            raise CheckRunsTooLargeError(
                "Pull request exceeds MergePay MVP check run limit"
            )

        return [_to_check_run(item) for item in items]

    def inspect_pull_request(self, pull_request_url: str) -> PullRequestInspection:
        ref = parse_pull_request_url(pull_request_url)

        summary = self.get_pull_request(ref)
        files = self.list_pull_request_files(ref)

        return PullRequestInspection(**summary.model_dump(), files=files)

    def get_branch_head_sha(self, owner: str, repo: str, branch: str) -> str:
        """SHA del commit al que apunta hoy la rama. Solo el SHA.

        Cada segmento se codifica por separado: vienen de datos que escribio un
        usuario, y una rama como `feature/x` debe viajar como un solo segmento.
        """
        path = "/repos/{}/{}/commits/{}".format(
            quote(owner, safe=""),
            quote(repo, safe=""),
            quote(branch, safe=""),
        )

        try:
            payload = self._get(path)
        except PullRequestNotFoundError as error:
            # `_get` nombra el 404 pensando en PRs. Aqui significa que no
            # existe el repo o la rama, y se traduce sin tocar esa excepcion.
            raise BranchNotFoundError(
                f"GitHub branch not found: {owner}/{repo}@{branch}"
            ) from error

        sha = payload.get("sha") if isinstance(payload, dict) else None

        if not isinstance(sha, str) or sha == "":
            raise GitHubUnexpectedStatusError(
                f"GitHub returned no commit SHA for {path}"
            )

        return sha


def _to_file(item: dict[str, Any]) -> PullRequestFile:
    return PullRequestFile(
        filename=item.get("filename"),
        status=item.get("status"),
        additions=item.get("additions"),
        deletions=item.get("deletions"),
        changes=item.get("changes"),
        previous_filename=item.get("previous_filename"),
    )


def _to_check_run(item: dict[str, Any]) -> GitHubCheckRun:
    # `started_at` puede no venir en un run recien encolado; el schema lo acepta
    # como None y lo guarda solo como metadata. `id` siempre lo trae GitHub y es
    # el selector cuando un required check aparece varias veces.
    return GitHubCheckRun(
        id=item.get("id"),
        name=item.get("name"),
        status=item.get("status"),
        conclusion=item.get("conclusion"),
        head_sha=item.get("head_sha"),
        html_url=item.get("html_url"),
        started_at=item.get("started_at"),
    )
