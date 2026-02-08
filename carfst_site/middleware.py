import logging
import re
import uuid
from pathlib import Path
from typing import Callable

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.http.multipartparser import MultiPartParserError

from carfst_site.build_id import get_build_id

logger = logging.getLogger("request_errors")


class ErrorLoggingMiddleware:
    """
    Adds a request id to each request/response and writes errors to logs/errors.log.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.request_id = request_id
        request.META["HTTP_X_REQUEST_ID"] = request_id

        try:
            response = self.get_response(request)
        except Exception:
            logger.exception(
                "Unhandled exception",
                extra={
                    "request_id": request_id,
                    "path": request.path,
                    "method": request.method,
                    "user": getattr(request, "user", None),
                },
            )
            raise

        response["X-Request-ID"] = request_id
        if response.status_code >= 500:
            logger.error(
                "Response with %s",
                response.status_code,
                extra={
                    "request_id": request_id,
                    "path": request.path,
                    "method": request.method,
                    "user": getattr(request, "user", None),
                },
            )
        return response


class BuildIdHeaderMiddleware:
    """
    Adds X-Build-ID header to every response for diagnostics.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response["X-Build-ID"] = get_build_id()
        return response


class UploadValidationMiddleware:
    """
    Rejects uploads that exceed size limits or use disallowed formats.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                files = request.FILES
            except MultiPartParserError:
                logger.warning("Invalid multipart upload", extra={"path": request.path})
                return HttpResponseBadRequest("Invalid upload payload.")

            for field_name, uploaded_file in files.items():
                failure = self._validate_file(uploaded_file)
                if failure:
                    logger.warning(
                        "Rejected upload: %s",
                        failure,
                        extra={
                            "path": request.path,
                            "field": field_name,
                            "content_type": getattr(uploaded_file, "content_type", None),
                            "size": getattr(uploaded_file, "size", None),
                        },
                    )
                    return HttpResponseBadRequest(failure)

        return self.get_response(request)

    def _validate_file(self, uploaded_file: UploadedFile) -> str | None:
        allowed_extensions = {ext.lower().lstrip(".") for ext in settings.MEDIA_ALLOWED_IMAGE_EXTENSIONS}
        allowed_mime_types = {mime.lower() for mime in settings.MEDIA_ALLOWED_IMAGE_MIME_TYPES}
        max_size_bytes = settings.MAX_IMAGE_SIZE

        file_size = getattr(uploaded_file, "size", None)
        if max_size_bytes and file_size is not None and file_size > max_size_bytes:
            return f"File '{uploaded_file.name}' exceeds maximum size of {max_size_bytes} bytes."

        extension = Path(uploaded_file.name or "").suffix.lower().lstrip(".")
        content_type = (getattr(uploaded_file, "content_type", "") or "").lower()

        if extension and extension not in allowed_extensions:
            return f"File '{uploaded_file.name}' has a disallowed extension."

        if content_type and content_type not in allowed_mime_types:
            return f"File '{uploaded_file.name}' has a disallowed content type."

        if content_type.startswith("image/") and not extension:
            return f"File '{uploaded_file.name}' must include a valid extension."

        return None


class SecurityHeadersMiddleware:
    """
    Adds additional security headers: Permissions-Policy, CSP Report-Only.
    Should be placed after SecurityMiddleware in MIDDLEWARE list.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response
        # CSP Report-Only configuration from settings
        self.csp_report_only = getattr(settings, "CSP_REPORT_ONLY", False)
        self.csp_report_uri = getattr(settings, "CSP_REPORT_URI", None)
        self.csp_policy = getattr(settings, "CSP_POLICY", None)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        
        # Permissions-Policy (formerly Feature-Policy)
        # Restrict access to browser features for security
        # Using a restrictive policy by default
        permissions_policy = (
            "accelerometer=(), "
            "autoplay=(), "
            "camera=(), "
            "cross-origin-isolated=(), "
            "display-capture=(), "
            "encrypted-media=(), "
            "fullscreen=(), "
            "geolocation=(), "
            "gyroscope=(), "
            "magnetometer=(), "
            "microphone=(), "
            "midi=(), "
            "payment=(), "
            "picture-in-picture=(), "
            "publickey-credentials-get=(), "
            "screen-wake-lock=(), "
            "sync-xhr=(), "
            "usb=(), "
            "web-share=(), "
            "xr-spatial-tracking=()"
        )
        response["Permissions-Policy"] = permissions_policy
        
        # Content-Security-Policy Report-Only (safe mode, doesn't block resources)
        if self.csp_report_only and self.csp_policy:
            header_name = "Content-Security-Policy-Report-Only"
            csp_value = self.csp_policy
            if self.csp_report_uri:
                csp_value = f"{csp_value}; report-uri {self.csp_report_uri}"
            response[header_name] = csp_value
        
        return response


class AdminCacheControlMiddleware:
    """
    Adds Cache-Control: no-store for admin pages to prevent caching of sensitive content.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response
        admin_prefix = settings.ADMIN_URL.rstrip("/")
        self.admin_prefix = admin_prefix if admin_prefix else "admin"
        # Paths that should have no-store cache control
        self.no_cache_paths = [self.admin_prefix, "adminlogin/", "staff/"]

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        
        # Check if path starts with any admin prefix
        path = request.path.lstrip("/")
        for prefix in self.no_cache_paths:
            if path.startswith(prefix):
                # Prevent caching of admin pages
                response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
                response["Pragma"] = "no-cache"
                response["Expires"] = "0"
                break
        
        return response


class RobotsNoIndexMiddleware:
    """
    Adds X-Robots-Tag: noindex, nofollow header for admin and lead pages.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response
        admin_prefix = settings.ADMIN_URL.rstrip("/")
        self.admin_prefix = admin_prefix if admin_prefix else "admin"
        # Paths that should have noindex
        self.noindex_paths = [self.admin_prefix, "adminlogin/", "staff/", "lead/"]

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        
        # Check if path starts with any noindex prefix
        path = request.path.lstrip("/")
        for prefix in self.noindex_paths:
            if path.startswith(prefix):
                response["X-Robots-Tag"] = "noindex, nofollow"
                break
        
        return response


class TemplateArtifactCleanupMiddleware:
    """
    Removes Django template comments and artifacts from HTML responses.
    Only processes text/html responses and only if markers are detected (minimal risk).
    Protects <script> and <style> blocks from cleanup.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response
        # Compile regex patterns once
        self.django_comment_pattern = re.compile(r'\{#.*?#\}', re.DOTALL)
        # Pattern for standalone lines with 3+ hashes: ^\s*#{3,}\s*$
        self.standalone_hashes_pattern = re.compile(r'(?m)^\s*#{3,}\s*$\n?')
        # Pattern for markdown headers at start of line: ^\s*#{3,}\s+.*?$
        self.markdown_header_pattern = re.compile(r'(?m)^\s*#{3,}\s+.*?$', re.MULTILINE)
        self.placeholder_pattern = re.compile(
            r'Inline\s+SVG\s+placeholder(?:\s+for\s+cases\s+when\s+product\s+has\s+no\s+images)?',
            re.IGNORECASE
        )
        # Pattern to extract script/style blocks
        self.script_style_pattern = re.compile(
            r'(<script[^>]*>.*?</script>|<style[^>]*>.*?</style>)',
            re.DOTALL | re.IGNORECASE
        )

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        
        # Only process text/html responses
        content_type = response.get("Content-Type", "").lower()
        if not content_type.startswith("text/html"):
            return response
        
        # Check if response has content and if markers are present (minimal risk)
        if not hasattr(response, "content") or not response.content:
            return response
        
        content_str = response.content.decode("utf-8", errors="ignore")
        
        # Only process if markers are detected
        has_django_comment = "{#" in content_str or "#}" in content_str
        # Check for markdown header artifacts (3+ hash symbols, including "#####") and placeholder text
        has_artifacts = "Inline SVG placeholder" in content_str or "###" in content_str or "#####" in content_str
        
        if not (has_django_comment or has_artifacts):
            return response
        
        # Protect script/style blocks: extract them temporarily
        protected_blocks = []
        placeholder_prefix = "___PROTECTED_BLOCK_"
        placeholder_counter = 0
        
        def replace_block(match):
            nonlocal placeholder_counter
            placeholder = f"{placeholder_prefix}{placeholder_counter}___"
            protected_blocks.append(match.group(0))
            placeholder_counter += 1
            return placeholder
        
        # Extract script/style blocks
        content_str = self.script_style_pattern.sub(replace_block, content_str)
        
        # Remove Django template comments: {# ... #}
        if has_django_comment:
            content_str = self.django_comment_pattern.sub("", content_str)
            # Also remove unclosed comment markers
            content_str = content_str.replace("{#", "").replace("#}", "")
        
        # Remove artifact strings (excluding protected blocks)
        if has_artifacts:
            # Remove markdown headers (3+ hash symbols + text at start of line, including "##### Преимущество")
            content_str = self.markdown_header_pattern.sub("", content_str)
            # Remove standalone hash lines (3+ hash symbols on separate lines)
            content_str = self.standalone_hashes_pattern.sub("", content_str)
            # Remove sequences of 3+ hashes anywhere in text (markdown header artifacts, including "#####")
            # This will remove "#####" from "##### Преимущество" leaving just "Преимущество"
            content_str = re.sub(r'#{3,}\s*', '', content_str)
            # Remove placeholder text
            content_str = self.placeholder_pattern.sub("", content_str)
        
        # Restore protected blocks
        for i, block in enumerate(protected_blocks):
            placeholder = f"{placeholder_prefix}{i}___"
            content_str = content_str.replace(placeholder, block, 1)
        
        # Clean up extra whitespace that might result from removals (but preserve newlines)
        # Only collapse multiple spaces/tabs into single space, preserve line breaks
        content_str = re.sub(r'[ \t]+', ' ', content_str)
        content_str = re.sub(r' *\n *', '\n', content_str)
        
        # Update response content
        response.content = content_str.encode("utf-8")
        # Update Content-Length if present
        if "Content-Length" in response:
            response["Content-Length"] = str(len(response.content))
        
        return response
