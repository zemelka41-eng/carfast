from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render


def robots_txt_view(request):
    """
    Return robots.txt as plain text with one directive per line.
    Guarantees multiline output (no template whitespace collapse).
    Content-Type: text/plain; charset=utf-8.
    """
    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    base_url = f"https://{canonical_host}"
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /adminlogin/",
        "Disallow: /staff/",
        "Disallow: /lead/",
        "Allow: /",
        "",
        "User-agent: Yandex",
        "Clean-param: utm_source&utm_medium&utm_campaign&utm_content&utm_term&utm_id&utm_referrer&gclid&fbclid&yclid&ysclid",
        "",
        f"Sitemap: {base_url}/sitemap.xml",
        "",
    ]
    body = "\n".join(lines)
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


YANDEX_VERIFICATION_HTML = """<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
</head>
<body>Verification: 70c3a80a6008addf</body>
</html>
"""


def yandex_verification(request):
    return HttpResponse(YANDEX_VERIFICATION_HTML, content_type="text/html; charset=UTF-8")


def custom_404(request, exception):
    """Render 404 template with no JSON-LD: request.schema_disabled + context overrides."""
    request.schema_disabled = True
    return render(
        request,
        "404.html",
        {
            "schema_allowed": False,
            "page_schema_payload": None,
            "schema_disabled": True,
        },
        status=404,
    )
