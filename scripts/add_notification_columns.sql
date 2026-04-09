-- MySQL：为已有库补充消息中心字段（若已存在可忽略报错）
ALTER TABLE notifications ADD COLUMN category VARCHAR(32) NOT NULL DEFAULT 'order' AFTER recipient_id;
ALTER TABLE notifications ADD COLUMN speech_important TINYINT(1) NOT NULL DEFAULT 0 AFTER type;
