-- Binance Square 帖子：对应 binance_posts_state.json 中
--   posts.{author_slug}.{href} 扁平化一行。
-- 用途之一：先查库判断「正文详情是否已抓取」，已抓取则 Selenium 不再打开该帖详情页。
-- MySQL 8.0+，utf8mb4。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS binance_square_post (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    post_id             VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '从 href 解析的数字 id，如 .../post/317831052021106',
    href                VARCHAR(768)    NOT NULL COMMENT '帖子完整 URL，全局唯一',
    author_slug         VARCHAR(191)    NOT NULL DEFAULT '' COMMENT '桶键：关注者 slug',
    author              VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '展示用作者名',

    title               TEXT            NULL COMMENT '标题',
    raw_body            MEDIUMTEXT      NULL COMMENT '正文/摘要 raw',

    published_at        VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '展示用发布时间串',
    published_iso       VARCHAR(80)     NOT NULL DEFAULT '' COMMENT 'ISO8601 若有',
    time_label          VARCHAR(191)    NOT NULL DEFAULT '' COMMENT '相对时间文案',
    time_display        VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '原 JSON 字段 time',
    is_pinned           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否置顶',

    video_url               VARCHAR(2048) NOT NULL DEFAULT '',
    audio_m3u8_url          VARCHAR(2048) NOT NULL DEFAULT '',
    square_audio_replay_url VARCHAR(2048) NOT NULL DEFAULT '',

    image_urls          JSON            NULL COMMENT '远程配图 URL 列表',
    saved_image_paths   JSON            NULL COMMENT '本地已下载截图路径列表',

    gemini_direction    VARCHAR(32)     NOT NULL DEFAULT '',
    gemini_confidence   DECIMAL(8, 4)   NULL,
    gemini_reason       TEXT            NULL,
    gemini_bias_zh      VARCHAR(32)     NOT NULL DEFAULT '',

    signal_is_sign      TINYINT(1)      NULL,
    signal_star         INT             NULL,
    signal_content      MEDIUMTEXT      NULL,
    signal_raw_data     JSON            NULL,
    signal_error        VARCHAR(512)    NULL,
    signal_analyzed_at  VARCHAR(128)    NOT NULL DEFAULT '',
    signal_image_used   VARCHAR(1024)   NOT NULL DEFAULT '',
    signal_analyzed_ok  TINYINT(1)      NOT NULL DEFAULT 0,

    published_at_utc    DATETIME(3)     NULL COMMENT '解析后的发帖 UTC，便于时间窗查询',

    -- ========== 正文详情抓取（Selenium 打开 /square/post/ 补图、video 等）==========
    -- 业务判断：若 post_detail_fetch_ok=1 且无需因版本重跑，则跳过 _enrich_post_images_from_detail_pages 等。
    post_detail_fetch_ok      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '1=该帖详情页已成功抓取并写入本行',
    post_detail_fetched_at    DATETIME(3)     NULL COMMENT '详情抓取完成时间（建议写 UTC）',
    post_detail_fetch_error   VARCHAR(512)    NULL COMMENT '详情抓取失败原因，成功时 NULL',
    post_detail_fetch_version SMALLINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '抓取逻辑变更时递增，可强制重抓',

    state_version       INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '与 JSON 根 version 对齐',
    created_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    UNIQUE KEY uk_href (href),
    KEY idx_post_id (post_id),
    KEY idx_author_slug_updated (author_slug, updated_at),
    KEY idx_published_utc (published_at_utc),
    KEY idx_signal_ok_star (signal_analyzed_ok, signal_star),
    KEY idx_detail_fetch (post_detail_fetch_ok, post_detail_fetched_at, post_detail_fetch_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Binance Square 帖子；支持按库判断详情是否已抓取';

-- ---------------------------------------------------------------------------
-- 判断是否还要抓「详情」的查询示例（应用侧先执行再决定是否 driver.get(href)）：
--
--   SELECT post_detail_fetch_ok, post_detail_fetch_version, post_detail_fetched_at
--   FROM binance_square_post
--   WHERE post_id = ? AND post_detail_fetch_ok = 1 AND post_detail_fetch_version >= ?
--   LIMIT 1;
--
-- 或按 href：
--   SELECT ... FROM binance_square_post WHERE href = ? ...
-- ---------------------------------------------------------------------------
