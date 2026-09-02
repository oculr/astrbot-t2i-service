# AstrBot Text2Image Service

[中文](README_zh-CN.md) | [English](README.md) | 日本語

## 機能

HTML、URL、またはホストした静的サイトを画像に変換し、画像のライフサイクル管理をサポートするWebサービスです。

## 環境変数設定

- `PORT`: サービスポート、デフォルトは8999
- `IMAGE_LIFETIME_HOURS`: 画像の保持時間（時間単位）、デフォルトは24時間。この時間を超えた画像ファイルは自動的にクリーンアップされます
- `STORAGE_BACKEND`: 画像ストレージバックエンド。`local`（デフォルト）、`s3`、`r2`をサポートします
- `WEB_ROOT`: ホストするWebサイトの保存先。デフォルトは `data/websites`
- `WEB_PUBLIC_URL_PREFIX`: 返却するWebサイトURLの外部アクセスプレフィックス。未設定時は現在のリクエスト元を使用
- `WEB_INTERNAL_URL_PREFIX`: Playwrightがコンテナ内からアクセスするURL。デフォルトは `http://127.0.0.1:${PORT}`
- `WEB_MAX_ARCHIVE_BYTES`: ZIPアップロード上限。デフォルトは100 MiB
- `WEB_MAX_SITE_BYTES`: 展開またはGit取得後のサイトサイズ上限。デフォルトは500 MiB
- `WEB_MAX_SITE_FILES`: 1サイトのファイル数上限。デフォルトは10000
- `WEB_GIT_TIMEOUT_SECONDS`: Git shallow cloneのタイムアウト。デフォルトは120秒

### Cloudflare R2 / S3互換オブジェクトストレージ

複数のレプリカを実行する場合、JSONモードで生成された画像を共通の
S3互換バケットに保存できます。これにより、画像の取得リクエストが
生成元とは異なるレプリカに到達しても`404`になることを防ぎます。
APIのパスとレスポンス形式は変更されません。

```env
STORAGE_BACKEND=r2
S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
S3_BUCKET=astrbot-t2i
AWS_ACCESS_KEY_ID=<ACCESS_KEY_ID>
AWS_SECRET_ACCESS_KEY=<SECRET_ACCESS_KEY>
AWS_DEFAULT_REGION=auto
S3_PREFIX=images
```

古い画像を自動削除するには、バケットにオブジェクトライフサイクルルールを設定してください。
`IMAGE_LIFETIME_HOURS`はローカルファイルのみを削除し、オブジェクトストレージには適用されません。

## API エンドポイント

### POST /text2img/generate

HTMLを画像に変換

> htmlとtmplのいずれかを選択してください。tmplとtmpldataは一緒に提供してください。

- `str` html: HTMLテキスト
- `str` tmpl: Jinja2 HTMLテンプレート
- `dict` tmpldata: Jinja2テンプレートデータ
- `bool` json: JSON形式で返すかどうか（idを返します）
- `dict` `optional` options
  - timeout (float, optional): スクリーンショットのタイムアウト時間。
  - type (Literal["jpeg", "png"], optional): スクリーンショットの画像タイプ。
  - quality (int, optional): スクリーンショットの品質、JPEG形式のみ適用されます。
  - omit_background (bool, optional): デフォルトの白い背景を非表示にするかどうか。これにより透明なスクリーンショットが可能になります（PNG形式のみ）。
  - full_page (bool, optional): ビューポートサイズだけでなく、ページ全体をキャプチャするかどうか、デフォルトはTrue。
  - clip (FloatRect, optional): スクリーンショット後にクリップする領域、xyは開始点です。
  - animations: (Literal["allow", "disabled"], optional): CSSアニメーションを許可するかどうか。
  - caret: (Literal["hide", "initial"], optional): `hide`に設定すると、スクリーンショット時にテキストキャレットが非表示になります。デフォルトは`hide`。
    - scale: (Literal["css", "device"], optional): ページのスケール設定。`css`に設定すると、デバイス解像度とCSSピクセルが1:1で対応し、高解像度画面ではスクリーンショットが小さくなります。`device`に設定すると、デバイスの画面スケール設定または現在のPlaywright Page/Contextのdevice_scale_factorパラメータに従ってスケールされます。
    - viewport_width (int, optional): スクリーンショットの幅を制御するカスタムビューポート幅。優先順位順：
      1. リクエストオプションで明示的に指定
      2. HTMLの`<meta name="viewport" content="width=...">` から自動解析
      3. 指定されていない場合、デフォルトは800px
    - viewport_height (int, optional): スクリーンショットの高さを制御するカスタムビューポート高さ。優先順位順：
      1. リクエストオプションで明示的に指定
      2. HTMLの`<meta name="viewport" content="height=...">` から自動解析
      3. 指定されていない場合、デフォルトは720px
    - device_scale_factor_level (Literal["normal", "high", "ultra"], optional): デバイスピクセル比レベル、デフォルトは"normal"。異なるレベルは独立したブラウザコンテキストプールを使用し、より良いパフォーマンスとリソース分離を提供します。
      - `normal`: デバイスピクセル比 1.0（デフォルト）
      - `high`: デバイスピクセル比 1.3
      - `ultra`: デバイスピクセル比 1.8

### POST /url2img/generate

HTTP/HTTPS URLにアクセスし、レンダリングされたページを直接画像に変換します。
`/text2img/generate` と同じ `options` および `json` フィールドを使用できます。
URLモードではページの `<meta name="viewport">` からビューポートサイズを推測せず、
未指定の場合は800×720を使用します。

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

- `str` url: 必須。`http://` または `https://` URLのみ対応
- `bool` json: JSON形式の画像IDを返すかどうか。デフォルトは `false`
- `dict` `optional` options: `/text2img/generate` と同じスクリーンショット設定
  - `navigation_wait_until`: ナビゲーション完了条件。デフォルトは `load`、`networkidle` も指定可能
  - `wait_after_load`: ナビゲーション完了後の追加待機時間（ミリ秒）。URLモードのデフォルトは `1000`
  - `wait_for_selector`: スクリーンショット前に待機するCSSセレクター
  - `auto_scroll`: 遅延読み込みを開始するための自動スクロール。URLモードのデフォルトは `true`
  - `wait_for_network_idle`: ネットワークのアイドル状態を待機。URLモードのデフォルトは `true`
  - `wait_for_images`: ページ内画像の読み込み完了を待機。URLモードのデフォルトは `true`

動的な読み込みが続くページでは、待機時間を増やすか、準備完了を示す要素を指定します。

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

JSONモードで返された `data/{id}` は `GET /url2img/data/{id}` から取得できます。

### POST /websites/import/git

HTTP/HTTPS Gitリポジトリから静的サイトをshallow cloneします。リポジトリにはブラウザで
直接表示できる成果物が必要です。React/Vueなどのソースでは、コミット済みの `dist` または
`build` を `subdirectory` に指定します。

```json
{
  "repository_url": "https://github.com/example/static-site.git",
  "ref": "main",
  "subdirectory": "dist"
}
```

### POST /websites/import/zip

`multipart/form-data` でオフラインZIPをアップロードします。

- `file`: 必須のZIPファイル
- `subdirectory`: ZIP内の静的ビルドディレクトリ（任意）

どちらの方法でも選択先に `index.html` が必要です。成功レスポンス例：

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

ZIPではパストラバーサル、シンボリックリンク、暗号化エントリ、上限超過を拒否します。
Git URLに認証情報を埋め込むことはできません。

### Webサイト管理

すべての管理操作はJSON本文を使用する `POST /websites/mgmt` に統一されています。
閲覧には末尾スラッシュ付きの `/websites/{id}/` のみを使用します。

| フィールド | 必須条件 | 説明 |
| --- | --- | --- |
| `action` | 常に必須 | `list`、`get`、`delete`、`replace` |
| `id` | `get`、`delete`、`replace` | 対象サイトID |
| `replacement_id` | `replace` | 新しくインポートした置換サイトID |

#### 一覧

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

#### 取得

```json
{"action":"get","id":"0123456789abcdef0123456789abcdef"}
```

#### 削除

```json
{"action":"delete","id":"0123456789abcdef0123456789abcdef"}
```

静的ファイルを完全に削除しますが、以前生成した画像は削除しません。

#### 置換

最初にGitまたはZIPインポートAPIで新しいビルドを取得し、そのIDを `replacement_id` に指定します。

```json
{
  "action": "replace",
  "id": "0123456789abcdef0123456789abcdef",
  "replacement_id": "fedcba9876543210fedcba9876543210"
}
```

対象のID、path、URLは維持され、置換IDは消費されて削除されます。ファイルはマージされず、
失敗時は元サイトが維持されます。2つのIDを同じ値にはできません。

#### 管理APIステータスコード

| HTTPステータス | 意味 |
| --- | --- |
| `200` | 一覧、取得、置換、削除に成功 |
| `400` | 必須IDが不足、または2つのIDが同一 |
| `404` | 対象サイトまたは置換サイトが存在しない |
| `422` | actionが不足/未対応、またはJSONフィールド型が不正 |
| `429` | 設定されたリクエストレート制限を超過 |

サービスにはユーザー認証が組み込まれていません。信頼できないネットワークへ公開する場合、
リバースプロキシまたはAPIゲートウェイで認証、認可、本文サイズ制限、監査ログを設定してください。

### GET /websites/{id}/{path}

ホストしたサイトを配信します。ホームページには末尾スラッシュ付きの `/websites/{id}/` を
使用します。ディレクトリは `index.html` を返し、拡張子のない未知の
パスはSPAルーティング用にルートの `index.html` へフォールバックします。

ビルド成果物では相対アセットパスを使用するか、返却された `/websites/{id}/` をbaseに
設定してください。ホストされたJavaScriptは閲覧者のブラウザで実行されます。信頼できない
アップロードを受け付ける場合は、`WEB_PUBLIC_URL_PREFIX` に別オリジンを使用し、
リバースプロキシで認証、リクエストサイズ制限、アクセスポリシーを設定してください。

### POST /websites/{id}/generate

Playwrightでホストしたサイトまたはサブページを撮影します。`/url2img/generate` と同じ
動的ページ待機とスクリーンショット設定を使用できます。

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

idに対応する画像を返します。`GET /url2img/data/{id}` は同じ機能のエイリアスです。
