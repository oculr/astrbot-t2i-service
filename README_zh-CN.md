# AstrBot Text2Image Service

中文 | [English](README.md) | [日本語](README_ja.md)

## 功能

一个将 HTML、URL 或托管静态网站转换为图片的 Web 服务，支持图片生命周期管理。

## 环境变量配置

- `PORT`: 服务端口，默认 8999
- `IMAGE_LIFETIME_HOURS`: 图片生命时间（小时），默认 24 小时。超过此时间的图片文件将被自动清理
- `STORAGE_BACKEND`: 图片存储后端，支持 `local`（默认）、`s3` 和 `r2`
- `WEB_ROOT`: 托管网站存储目录，默认 `data/websites`
- `WEB_PUBLIC_URL_PREFIX`: 返回网站完整 URL 时使用的外部访问前缀；未设置时使用当前请求地址
- `WEB_INTERNAL_URL_PREFIX`: Playwright 在容器内访问托管网站的地址，默认 `http://127.0.0.1:${PORT}`
- `WEB_MAX_ARCHIVE_BYTES`: ZIP 上传大小上限，默认 100 MiB
- `WEB_MAX_SITE_BYTES`: 解压后或 Git 导入后的网站大小上限，默认 500 MiB
- `WEB_MAX_SITE_FILES`: 单个网站文件数量上限，默认 10000
- `WEB_GIT_TIMEOUT_SECONDS`: Git 浅克隆超时，默认 120 秒

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
  - `navigation_wait_until`: 导航完成条件，默认为 `load`，可设为 `networkidle`
  - `wait_after_load`: 导航完成后额外等待的毫秒数，URL 模式默认为 `1000`
  - `wait_for_selector`: 截图前等待出现的 CSS 选择器
  - `auto_scroll`: 自动滚动以触发懒加载，URL 模式默认为 `true`
  - `wait_for_network_idle`: 等待网络空闲，URL 模式默认为 `true`
  - `wait_for_images`: 等待页面图片完成加载，URL 模式默认为 `true`

对于持续加载的动态页面，可增加等待时间或指定页面就绪元素：

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

JSON 模式返回的 `data/{id}` 可通过 `GET /url2img/data/{id}` 获取。

### POST /websites/import/git

从 HTTP/HTTPS Git 仓库浅克隆静态网站。仓库必须包含可直接浏览的构建产物；
对于 React/Vue 等源码仓库，通过 `subdirectory` 指向已经提交的 `dist` 或 `build`。

```json
{
  "repository_url": "https://github.com/example/static-site.git",
  "ref": "main",
  "subdirectory": "dist"
}
```

### POST /websites/import/zip

使用 `multipart/form-data` 上传离线 ZIP 包：

- `file`: 必填的 ZIP 文件
- `subdirectory`: 可选，指定压缩包内的静态构建目录

ZIP 和 Git 导入都会要求目标目录存在 `index.html`。成功响应示例：

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

ZIP 导入会阻止路径穿越、符号链接、加密条目和超限内容；Git URL 不允许内嵌凭据。

### GET /websites/{id}/{path}

访问已托管的网站资源。目录默认返回 `index.html`；没有扩展名的未知路径会回退到
根目录 `index.html`，支持前端 SPA 路由。

前端构建产物应使用相对资源路径，或将构建 base 配置为返回的 `/websites/{id}/`。
托管页面会执行其中的 JavaScript；接收不可信用户上传时，建议使用独立域名作为
`WEB_PUBLIC_URL_PREFIX`，并在反向代理层配置身份验证、上传大小限制和访问策略。

### POST /websites/{id}/generate

使用 Playwright 截取已托管网站或其子页面，支持与 `/url2img/generate` 相同的动态
页面等待和截图参数。

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

根据 id 返回对应的图像。`GET /url2img/data/{id}` 是功能相同的别名。
