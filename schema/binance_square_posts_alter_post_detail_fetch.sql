-- 若你已按旧版 schema 建过 binance_square_post（无详情抓取字段），执行本脚本升级。
-- MySQL 8.0+

SET NAMES utf8mb4;

ALTER TABLE binance_square_post
    ADD COLUMN post_detail_fetch_ok TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '1=该帖详情页已成功抓取并写入本行' AFTER published_at_utc,
    ADD COLUMN post_detail_fetched_at DATETIME(3) NULL
        COMMENT '详情抓取完成时间（建议 UTC）' AFTER post_detail_fetch_ok,
    ADD COLUMN post_detail_fetch_error VARCHAR(512) NULL
        COMMENT '详情抓取失败原因' AFTER post_detail_fetched_at,
    ADD COLUMN post_detail_fetch_version SMALLINT UNSIGNED NOT NULL DEFAULT 1
        COMMENT '抓取逻辑变更时递增，可强制重抓' AFTER post_detail_fetch_error;

ALTER TABLE binance_square_post
    ADD KEY idx_detail_fetch (post_detail_fetch_ok, post_detail_fetched_at, post_detail_fetch_version);

-- 若旧表没有 uk_post_id，可取消下一行注释（确保 post_id 无重复脏数据后再加唯一索引）
-- ALTER TABLE binance_square_post ADD UNIQUE KEY uk_post_id (post_id);
