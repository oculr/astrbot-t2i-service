# AstrBot Text2Image Service

中文 | [English](README.md) | [日本語](README_ja.md)

## 功能

一个简单的将 HTML/模板转换为图片的 Web 服务，支持图片生命周期管理。

## 环境变量配置

- `PORT`: 服务端口，默认 8999
- `IMAGE_LIFETIME_HOURS`: 图片生命时间（小时），默认 24 小时。超过此时间的图片文件将被自动清理
- `STORAGE_BACKEND`: 图片存储后端，支持 `local`（默认）、`s3` 和 `r2`

### Cloudflare R2 / S3 兼容对象存储

多副本部署时，可以将 JSON 模式生成的图片写入同一个 S3 兼容存储桶，
避免图片生成请求和后续读取请求落在不同实例时返回 `404`。API 路径和响应格式保持不变。

```env
STORAGE_BACKEND=r2
S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
S3_BUCKET=astrbot-t2i
AWS_ACCESS_KEY_ID=<ACCESS_KEY_ID>
AWS_SECRET_ACCESS_KEY=<SECRET_ACCESS_KEY>
AWS_DEFAULT_REGION=auto
S3_PREFIX=images
```

建议为存储桶配置对象生命周期规则以自动删除过期图片。
`IMAGE_LIFETIME_HOURS` 只清理本地文件，不会删除对象存储中的图片。

## API 接口

### POST /text2img/generate

html 转 img

> html 和 tmpl 任选一个。tmpl 和 tmpldata 一起提供。

- `str` html: html 文本
- `str` tmpl: jinja2 html 模板
- `dict` tmpldata: jinja2 模板 data
- `bool` json: 是否返回 json 格式（返回一个 id）
- `dict` `optional` options
  - timeout (float, optional): 截图超时时间.
  - type (Literal["jpeg", "png"], optional): 截图图片类型.
  - quality (int, optional): 截图质量，仅适用于 JPEG 格式图片.
  - omit_background (bool, optional): 是否允许隐藏默认的白色背景，这样就可以截透明图了，仅适用于 PNG 格式
  - full_page (bool, optional): 是否截整个页面而不是仅设置的视口大小，默认为 True.
  - clip (FloatRect, optional): 截图后裁切的区域，xy为起点.
  - animations: (Literal["allow", "disabled"], optional): 是否允许播放 CSS 动画.
  - caret: (Literal["hide", "initial"], optional): 当设置为 `hide` 时，截图时将隐藏文本插入符号，默认为 `hide`.
    - scale: (Literal["css", "device"], optional): 页面缩放设置. 当设置为 `css` 时，则将设备分辨率与 CSS 中的像素一一对应，在高分屏上会使得截图变小. 当设置为 `device` 时，则根据设备的屏幕缩放设置或当前 Playwright 的 Page/Context 中的 device_scale_factor 参数来缩放.
    - viewport_width (int, optional): 自定义视口宽度，用于控制截图宽度. 优先级顺序：
      1. 在请求 options 中显式指定
      2. 从 HTML 的 `<meta name="viewport" content="width=...">` 自动解析
      3. 未指定时默认为 800px
    - viewport_height (int, optional): 自定义视口高度，用于控制截图高度. 优先级顺序：
      1. 在请求 options 中显式指定
      2. 从 HTML 的 `<meta name="viewport" content="height=...">` 自动解析
      3. 未指定时默认为 720px
    - device_scale_factor_level (Literal["normal", "high", "ultra"], optional): 设备像素比等级，默认为 "normal". 不同等级使用独立的浏览器上下文池，提供更好的性能和资源隔离.
      - `normal`: 设备像素比 1.0（默认）
      - `high`: 设备像素比 1.3
      - `ultra`: 设备像素比 1.8

### POST /url2img/generate

访问 HTTP/HTTPS URL，并将渲染后的页面直接转换为图片。支持与
`/text2img/generate` 相同的 `options` 和 `json` 参数；URL 模式不会从页面的
`<meta name="viewport">` 推断视口大小，未指定时使用 800×720。

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

- `str` url: 必填，只支持 `http://` 或 `https://` URL
- `bool` json: 是否返回 JSON 格式的图片 ID，默认为 `false`
- `dict` `optional` options: 截图参数，与 `/text2img/generate` 相同

JSON 模式返回的 `data/{id}` 可通过 `GET /url2img/data/{id}` 获取。

### GET /text2img/data/{id}

根据 id 返回对应的图像。`GET /url2img/data/{id}` 是功能相同的别名。
