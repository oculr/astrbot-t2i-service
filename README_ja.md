# AstrBot Text2Image Service

[中文](README_zh-CN.md) | [English](README.md) | 日本語

## 機能

HTMLやテンプレートを画像に変換するシンプルなWebサービスで、画像のライフサイクル管理をサポートしています。

## 環境変数設定

- `PORT`: サービスポート、デフォルトは8999
- `IMAGE_LIFETIME_HOURS`: 画像の保持時間（時間単位）、デフォルトは24時間。この時間を超えた画像ファイルは自動的にクリーンアップされます
- `STORAGE_BACKEND`: 画像ストレージバックエンド。`local`（デフォルト）、`s3`、`r2`をサポートします

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

### GET /text2img/data/{id}

idに対応する画像を返します。`GET /url2img/data/{id}` は同じ機能のエイリアスです。
