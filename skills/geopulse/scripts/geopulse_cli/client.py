"""Bearer-only HTTP, local session storage, and atomic downloads for the CLI."""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CLI_CONTRACT = "geopulse-cli-v1"
DEFAULT_BASE_URL = "http://127.0.0.1:8701"


class CliError(Exception):
    def __init__(self, message: str, *, code: str = "cli_error", status: int | None = None,
                 detail: Any = None, request_id: str = "", exit_code: int = 1):
        super().__init__(message)
        self.code = code
        self.status = status
        self.detail = detail
        self.request_id = request_id
        self.exit_code = exit_code

    def payload(self) -> dict:
        return {"status": "error", "error": {
            "code": self.code, "message": str(self), "http_status": self.status,
            "detail": self.detail, "request_id": self.request_id or None,
        }}


@dataclass
class ApiResponse:
    status: int
    headers: Any
    content: bytes

    def json(self) -> Any:
        if not self.content:
            return None
        try:
            return json.loads(self.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CliError("服务返回了无效 JSON", code="invalid_response", status=self.status,
                           exit_code=5) from error


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def normalize_base_url(value: str) -> str:
    result = (value or DEFAULT_BASE_URL).rstrip("/")
    parsed = urllib.parse.urlparse(result)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise CliError("--base-url 必须是有效的 HTTP(S) 服务地址", code="invalid_base_url", exit_code=2)
    return result


def session_path(value: str | None = None) -> Path:
    if value:
        return Path(value).expanduser()
    configured = os.environ.get("GEOPULSE_SESSION")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "geopulse" / "session.json"


def load_session(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        if os.name == "posix" and path.stat().st_mode & 0o077:
            raise CliError(f"会话文件权限过宽，请 chmod 600 {path}", code="unsafe_session_permissions")
        value = json.loads(path.read_text(encoding="utf-8"))
    except CliError:
        raise
    except (OSError, json.JSONDecodeError) as error:
        raise CliError(f"无法读取本机会话：{error}", code="invalid_session") from error
    if not isinstance(value, dict):
        raise CliError("本机会话格式不正确", code="invalid_session")
    return value


def save_session(path: Path, base_url: str, token: str, user: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        path.parent.chmod(0o700)
    payload = {"base_url": base_url, "access_token": token, "user": user,
               "contract": CLI_CONTRACT}
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clear_session(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


class Client:
    def __init__(self, base_url: str, token: str = "", timeout: float = 30):
        self.base_url = normalize_base_url(base_url)
        self.token = token
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            NoRedirects(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
        )

    @classmethod
    def authenticated(cls, args, *, required: bool = True) -> "Client":
        path = session_path(args.session)
        session = load_session(path)
        base_url = normalize_base_url(args.base_url or os.environ.get("GEOPULSE_BASE_URL")
                                      or session.get("base_url") or DEFAULT_BASE_URL)
        token = os.environ.get("GEOPULSE_ACCESS_TOKEN", "")
        if not token and session.get("base_url") == base_url:
            token = session.get("access_token", "")
        if required and not token:
            raise CliError("请先 auth login，或设置 GEOPULSE_ACCESS_TOKEN", code="authentication_required",
                           status=401, exit_code=3)
        return cls(base_url, token, args.timeout)

    def _open(self, method: str, path: str, query: dict | None, json_body: Any,
              data: bytes | None, headers: dict | None, timeout: float | None):
        clean_query = {key: value for key, value in (query or {}).items() if value is not None}
        encoded = urllib.parse.urlencode(clean_query, doseq=True)
        url = f"{self.base_url}{path}{'?' + encoded if encoded else ''}"
        request_headers = {"Accept": "application/json", "User-Agent": f"GeoPulse-CLI/{CLI_CONTRACT}"}
        if self.token:
            request_headers["Authorization"] = f"Bearer {self.token}"
        body = data
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            return self.opener.open(request, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as error:
            self._raise_http(error, method, path)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise CliError(f"无法连接服务：{error}", code="network_error", detail={"method": method, "path": path},
                           exit_code=5) from error

    def _raise_http(self, error: urllib.error.HTTPError, method: str, path: str):
        content = error.read()
        try:
            payload = json.loads(content.decode("utf-8")) if content else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"detail": content.decode("utf-8", errors="replace")[:2000]}
        detail = payload.get("detail", payload)
        message = detail.get("message") if isinstance(detail, dict) else None
        if not message:
            message = str(detail) if detail else f"HTTP {error.code}"
        code = detail.get("code", "http_error") if isinstance(detail, dict) else "http_error"
        exit_code = 3 if error.code in (401, 403) else 4 if error.code in (400, 409, 422) else 5
        raise CliError(message, code=code, status=error.code, detail=detail,
                       request_id=error.headers.get("X-Request-ID", ""), exit_code=exit_code) from None

    def request(self, method: str, path: str, *, query: dict | None = None, json_body: Any = None,
                data: bytes | None = None, headers: dict | None = None, timeout: float | None = None) -> ApiResponse:
        try:
            response = self._open(method, path, query, json_body, data, headers, timeout)
        except urllib.error.HTTPError as error:
            self._raise_http(error, method, path)
        with response:
            return ApiResponse(response.status, response.headers, response.read())

    def download(self, method: str, path: str, target: Path, *, query: dict | None = None,
                 overwrite: bool = False, timeout: float | None = None, validator=None) -> dict:
        target = target.expanduser().resolve()
        if target.exists() and not overwrite:
            raise CliError(f"输出文件已存在：{target}；如确需覆盖请显式使用 --overwrite",
                           code="output_exists", exit_code=2)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        digest = hashlib.sha256()
        size = 0
        try:
            response = self._open(method, path, query, None, None, None, timeout)
            with response, os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
                if not size:
                    raise CliError("下载内容为空，未替换输出文件", code="empty_download", exit_code=5)
                content_type = response.headers.get_content_type()
                if content_type == "application/pdf":
                    with open(temporary, "rb") as downloaded:
                        if downloaded.read(5) != b"%PDF-":
                            raise CliError("PDF 文件签名不正确，未替换输出文件", code="invalid_pdf", exit_code=5)
                expected = response.headers.get("X-Content-SHA256", "")
                if expected and expected.lower() != digest.hexdigest():
                    raise CliError("下载 SHA-256 与服务响应不一致", code="download_hash_mismatch", exit_code=5)
                validation = validator(Path(temporary)) if validator else {}
                os.chmod(temporary, 0o600)
                os.replace(temporary, target)
                return {"path": str(target), "bytes": size, "sha256": digest.hexdigest(),
                        "content_type": content_type, "response_sha256_verified": bool(expected),
                        **(validation or {})}
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def verify_project_export(payload: dict) -> str:
    checksum = payload.get("sha256")
    if not checksum:
        raise CliError("项目导出缺少 sha256", code="export_hash_missing", exit_code=5)
    unsigned = {key: value for key, value in payload.items() if key != "sha256"}
    canonical = json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    actual = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if actual != checksum:
        raise CliError("项目导出内部 SHA-256 校验失败", code="export_hash_mismatch", exit_code=5)
    return actual
