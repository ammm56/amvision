-- 工业单帧结果交付全链样例使用的 SQLite 建表脚本。
-- 当前 custom.output.local-db-upsert 不负责自动建表，导入 workflow 前应先在目标 SQLite 文件上执行本脚本。

CREATE TABLE IF NOT EXISTS inspection_results (
    record_id TEXT PRIMARY KEY,
    work_order_id TEXT,
    station_id TEXT,
    line_id TEXT,
    trace_id TEXT,
    ok_ng TEXT NOT NULL,
    ok INTEGER NOT NULL,
    reason TEXT,
    coverage_ratio REAL,
    offset_distance_pixels REAL,
    alarm_active INTEGER,
    signal_write_failed_count INTEGER,
    json_result_path TEXT,
    csv_result_path TEXT
);
