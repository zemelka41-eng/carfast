Media uploads live here at runtime; keep the directory empty in VCS.

- Allowed image formats: JPEG/PNG/WebP by default (extensions: `jpg`, `jpeg`, `jfif`, `png`, `webp`). Override with env vars `MEDIA_ALLOWED_IMAGE_EXTENSIONS` and `MEDIA_ALLOWED_IMAGE_MIME_TYPES` if you need additional safe types.
- Maximum image size: `MAX_IMAGE_SIZE` (default 10 MB). Requests beyond this limit are rejected early by middleware and Django's upload caps.
- Upload validation: `UploadValidationMiddleware` blocks disallowed formats/content types and oversize files, logging the request path and field when it happens.
- Product images are stored under `products/`; avoid manual edits unless you know what you are doing.
- Back up `media/` before deployments that touch storage and keep log rotation on for `logs/`.
