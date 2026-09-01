# AstrBot Text2Image Service

[中文](README_zh-CN.md) | English | [日本語](README_ja.md)

## Features

A simple web service that converts HTML/templates to images, with image lifecycle management support.

## Environment Variables

- `PORT`: Service port, default is 8999
- `IMAGE_LIFETIME_HOURS`: Image lifetime in hours, default is 24 hours. Images older than this will be automatically cleaned up
- `STORAGE_BACKEND`: Image storage backend. Supports `local` (default), `s3`, and `r2`

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

In JSON mode, retrieve the returned `data/{id}` from `GET /url2img/data/{id}`.

### GET /text2img/data/{id}

Returns the corresponding image by id. `GET /url2img/data/{id}` is an equivalent alias.
