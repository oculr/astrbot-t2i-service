# AstrBot Text2Image Service

[中文](README_zh-CN.md) | English | [日本語](README_ja.md)

## Features

A web service that converts HTML, URLs, or hosted static websites to images, with image lifecycle management support.

## Environment Variables

- `PORT`: Service port, default is 8999
- `IMAGE_LIFETIME_HOURS`: Image lifetime in hours, default is 24 hours. Images older than this will be automatically cleaned up
- `STORAGE_BACKEND`: Image storage backend. Supports `local` (default), `s3`, and `r2`
- `WEB_ROOT`: Hosted website storage directory, default is `data/websites`
- `WEB_PUBLIC_URL_PREFIX`: External prefix used in returned website URLs; falls back to the current request origin
- `WEB_INTERNAL_URL_PREFIX`: Address Playwright uses inside the container, default is `http://127.0.0.1:${PORT}`
- `WEB_MAX_ARCHIVE_BYTES`: ZIP upload limit, default is 100 MiB
- `WEB_MAX_SITE_BYTES`: Extracted or cloned website size limit, default is 500 MiB
- `WEB_MAX_SITE_FILES`: File limit per website, default is 10000
- `WEB_GIT_TIMEOUT_SECONDS`: Shallow Git clone timeout, default is 120 seconds

### Cloudflare R2 / S3-compatible object storage

When running multiple replicas, JSON-mode images can be stored in one shared
S3-compatible bucket. This prevents a later image request from returning `404`
when it reaches a replica other than the one that rendered the image. API paths
and response formats remain unchanged.

```env
STORAGE_BACKEND=r2
S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
S3_BUCKET=astrbot-t2i
AWS_ACCESS_KEY_ID=<ACCESS_KEY_ID>
AWS_SECRET_ACCESS_KEY=<SECRET_ACCESS_KEY>
AWS_DEFAULT_REGION=auto
S3_PREFIX=images
```

Configure an object lifecycle rule on the bucket to expire old images.
`IMAGE_LIFETIME_HOURS` only cleans up local files and does not delete objects.

## API Endpoints

### POST /text2img/generate

Convert HTML to image

> Choose either html or tmpl. Provide tmpl and tmpldata together.

- `str` html: HTML text
- `str` tmpl: Jinja2 HTML template
- `dict` tmpldata: Jinja2 template data
- `bool` json: Whether to return JSON format (returns an id)
- `dict` `optional` options
  - timeout (float, optional): Screenshot timeout.
  - type (Literal["jpeg", "png"], optional): Screenshot image type.
  - quality (int, optional): Screenshot quality, only applicable to JPEG format.
  - omit_background (bool, optional): Whether to hide the default white background, allowing transparent screenshots (PNG only).
  - full_page (bool, optional): Whether to capture the entire page instead of just the viewport, default is True.
  - clip (FloatRect, optional): Area to clip after screenshot, xy is the starting point.
  - animations: (Literal["allow", "disabled"], optional): Whether to allow CSS animations.
  - caret: (Literal["hide", "initial"], optional): When set to `hide`, the text caret will be hidden during screenshot, default is `hide`.
  - scale: (Literal["css", "device"], optional): Page scaling settings. When set to `css`, device resolution maps 1:1 with CSS pixels, making screenshots smaller on high-DPI screens. When set to `device`, scales according to device screen scaling or the device_scale_factor parameter in the current Playwright Page/Context.
  - viewport_width (int, optional): Custom viewport width to control screenshot width. Resolved in priority order:
    1. Explicitly set in request options
    2. Auto-parsed from `<meta name="viewport" content="width=...">` in HTML
    3. Defaults to 800px if not specified and no meta tag found
  - viewport_height (int, optional): Custom viewport height to control screenshot height. Resolved in priority order:
    1. Explicitly set in request options
    2. Auto-parsed from `<meta name="viewport" content="height=...">` in HTML
    3. Defaults to 720px if not specified and no meta tag found
  - device_scale_factor_level (Literal["normal", "high", "ultra"], optional): Device pixel ratio level, default is "normal". Different levels use independent browser context pools for better performance and resource isolation.
    - `normal`: Device pixel ratio 1.0 (default)
    - `high`: Device pixel ratio 1.3
    - `ultra`: Device pixel ratio 1.8

### POST /url2img/generate

Navigate to an HTTP/HTTPS URL and convert the rendered page directly to an image.
This endpoint supports the same `options` and `json` fields as
`/text2img/generate`. URL rendering does not infer viewport dimensions from a
page's `<meta name="viewport">`; the default is 800×720 when none are supplied.

```json
{
  "url": "https://example.com",
  "json": false,
  "options": {
    "full_page": true,
    "viewport_width": 1200,
    "viewport_height": 800
  }
}
```

- `str` url: Required; only `http://` and `https://` URLs are accepted
- `bool` json: Whether to return a JSON image id, default is `false`
- `dict` `optional` options: Screenshot options, identical to `/text2img/generate`
  - `navigation_wait_until`: Navigation readiness condition; defaults to `load` and may be set to `networkidle`
  - `wait_after_load`: Additional delay in milliseconds; defaults to `1000` for URL rendering
  - `wait_for_selector`: CSS selector to wait for before taking the screenshot
  - `auto_scroll`: Automatically scroll to trigger lazy loading; defaults to `true` for URL rendering
  - `wait_for_network_idle`: Wait for network idle; defaults to `true` for URL rendering
  - `wait_for_images`: Wait for page images to finish loading; defaults to `true` for URL rendering

For pages that continue loading dynamically, increase the delay or wait for a
page-specific ready element:

```json
{
  "url": "https://example.com/dynamic-page",
  "options": {
    "wait_after_load": 3000,
    "wait_for_selector": ".page-ready",
    "auto_scroll": true,
    "wait_for_network_idle": true,
    "wait_for_images": true
  }
}
```

In JSON mode, retrieve the returned `data/{id}` from `GET /url2img/data/{id}`.

### POST /websites/import/git

Shallow-clone a static website from an HTTP/HTTPS Git repository. The repository
must contain browser-ready output. For React/Vue source repositories, set
`subdirectory` to a committed `dist` or `build` directory.

```json
{
  "repository_url": "https://github.com/example/static-site.git",
  "ref": "main",
  "subdirectory": "dist"
}
```

### POST /websites/import/zip

Upload an offline ZIP with `multipart/form-data`:

- `file`: Required ZIP file
- `subdirectory`: Optional static build directory inside the archive

Both import methods require `index.html` in the selected directory. Example response:

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "0123456789abcdef0123456789abcdef",
    "path": "/websites/0123456789abcdef0123456789abcdef/",
    "url": "https://t2i.example.com/websites/0123456789abcdef0123456789abcdef/"
  }
}
```

ZIP imports reject path traversal, symbolic links, encrypted entries, and content
over the configured limits. Git URLs may not contain embedded credentials.

### Website management

All management operations use `POST /websites/mgmt` with a JSON body. Browsing only
uses the trailing-slash `/websites/{id}/` URL, so `/websites/{id}` no longer has a
separate management meaning.

| Field | Required for | Description |
| --- | --- | --- |
| `action` | Always | `list`, `get`, `delete`, or `replace` |
| `id` | `get`, `delete`, `replace` | Target site id |
| `replacement_id` | `replace` | Newly imported replacement site id |

#### List

```json
{"action":"list"}
```

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "0123456789abcdef0123456789abcdef",
        "path": "/websites/0123456789abcdef0123456789abcdef/",
        "url": "https://t2i.example.com/websites/0123456789abcdef0123456789abcdef/"
      }
    ],
    "total": 1
  }
}
```

#### Get

```json
{"action":"get","id":"0123456789abcdef0123456789abcdef"}
```

#### Delete

```json
{"action":"delete","id":"0123456789abcdef0123456789abcdef"}
```

Deletion permanently removes static files but does not remove previously generated images.

#### Replace

First import the new build through `/websites/import/git` or `/websites/import/zip`, then
use the returned id as `replacement_id`:

```json
{
  "action": "replace",
  "id": "0123456789abcdef0123456789abcdef",
  "replacement_id": "fedcba9876543210fedcba9876543210"
}
```

The target id, path, and URL are preserved. The replacement id is consumed and removed.
Files are not merged, and failures leave the original site available. The two ids must differ.

#### Management status codes

| HTTP status | Meaning |
| --- | --- |
| `200` | List, lookup, replacement, or deletion succeeded |
| `400` | Required id fields are missing or both ids are equal |
| `404` | The target or replacement site does not exist |
| `422` | The action is missing/unsupported or JSON field types are invalid |
| `429` | The configured request rate limit was exceeded |

The service does not provide built-in user authentication. Protect management endpoints
with authentication, authorization, body-size limits, and audit logging at a reverse proxy
or API gateway when exposing them to an untrusted network.

### GET /websites/{id}/{path}

Serve a hosted website. Use the trailing-slash `/websites/{id}/` for its homepage.
Directories resolve to `index.html`; extensionless missing
paths fall back to the root `index.html` for SPA routing.

Build output should use relative asset paths or configure its base path to the
returned `/websites/{id}/`. Hosted JavaScript executes in the visitor's browser.
For untrusted uploads, use a separate origin for `WEB_PUBLIC_URL_PREFIX` and apply
authentication, request-size limits, and access policy at the reverse proxy.

### POST /websites/{id}/generate

Capture a hosted website or subpage with Playwright. It accepts the same dynamic
page readiness and screenshot options as `/url2img/generate`.

```json
{
  "path": "dashboard?theme=dark",
  "json": false,
  "options": {
    "viewport_width": 1200,
    "wait_for_selector": ".page-ready"
  }
}
```

### GET /text2img/data/{id}

Returns the corresponding image by id. `GET /url2img/data/{id}` is an equivalent alias.
