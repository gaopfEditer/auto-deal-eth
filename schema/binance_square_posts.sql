-- Binance Square 帖子状态表：对应 binance_posts_state.json 中
--   posts.{author_slug}.{href} 的扁平化一行存储。
-- 字符集 utf8mb4，便于中文标题/正文与 emoji。
-- MySQL 8.0+ 推荐（使用 JSON 类型）。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS binance_square_post (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    post_id             VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '从 href 解析的帖子数字 id，如 .../post/317087106759233',
    href                VARCHAR(768)    NOT NULL COMMENT '帖子完整 URL，全局唯一',
    author_slug         VARCHAR(191)    NOT NULL DEFAULT '' COMMENT '桶键：关注者 slug，未知桶可为 _unknown 等',
    author              VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '展示用作者名',

    title               TEXT            NULL COMMENT '标题',
    raw_body            MEDIUMTEXT      NULL COMMENT '正文/摘要 raw',

    published_at        VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '展示用发布时间串，如「2026-04-28 00:48:47 北京时间」',
    published_iso       VARCHAR(80)     NOT NULL DEFAULT '' COMMENT 'ISO8601 若有',
    time_label          VARCHAR(191)    NOT NULL DEFAULT '' COMMENT '相对时间文案',
    time_display        VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '原 JSON 字段 time',
    is_pinned           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否置顶',

    video_url               VARCHAR(2048) NOT NULL DEFAULT '',
    audio_m3u8_url          VARCHAR(2048) NOT NULL DEFAULT '',
    square_audio_replay_url VARCHAR(2048) NOT NULL DEFAULT '',

    -- 列表型字段用 JSON 存，与 Python list 一一对应
    image_urls          JSON            NULL COMMENT '远程配图 URL 列表',
    saved_image_paths   JSON            NULL COMMENT '本地已下载截图路径列表',

    gemini_direction    VARCHAR(32)     NOT NULL DEFAULT '' COMMENT 'bullish/bearish/unclear 等',
    gemini_confidence   DECIMAL(8, 4)   NULL COMMENT '置信度',
    gemini_reason       TEXT            NULL COMMENT 'Gemini 理由',
    gemini_bias_zh      VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '中文多空摘要',

    signal_is_sign      TINYINT(1)      NULL COMMENT '本地信号 API：是否有效信号',
    signal_star         INT             NULL COMMENT '星级，0 表示过滤档',
    signal_content      MEDIUMTEXT      NULL COMMENT '信号说明正文',
    signal_raw_data     JSON            NULL COMMENT '接口原始 JSON（整包）',
    signal_error        VARCHAR(512)    NULL COMMENT '分析失败时的错误码/文案',
    signal_analyzed_at  VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '分析完成时间（北京时间串）',
    signal_image_used   VARCHAR(1024)   NOT NULL DEFAULT '' COMMENT '分析时使用的本地图路径',
    signal_analyzed_ok  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否已成功分析',

    -- 便于按时间窗口查询、排序（可由应用从 published_iso / published_at 解析后写入）
    published_at_utc    DATETIME(3)     NULL COMMENT '发帖时间 UTC，可空',

    state_version       INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '与 JSON 根 version 对齐',
    created_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    UNIQUE KEY uk_href (href),
    KEY idx_author_slug_updated (author_slug, updated_at),
    KEY idx_post_id (post_id),
    KEY idx_published_utc (published_at_utc),
    KEY idx_signal_ok_star (signal_analyzed_ok, signal_star)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Binance Square 帖子持久化（等价 binance_posts_state.posts 嵌套结构扁平化）';
