-- SOrders 迁移：挂账单位 / 库存 / 订单支付
-- MySQL 8 执行（已有库升级用；新库直接跑 init_tables.py 即可，SQLite 开发库删除重建）

-- 1) 挂账单位表
CREATE TABLE IF NOT EXISTS arrears_units (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL UNIQUE,
    phone VARCHAR(32) NOT NULL DEFAULT '',
    remark VARCHAR(256) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_arrears_units_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2) 库存流水表
CREATE TABLE IF NOT EXISTS inventory_movements (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    `change` INT NOT NULL,
    note VARCHAR(256) NOT NULL DEFAULT '',
    operator_id INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_inventory_movements_product_id (product_id),
    CONSTRAINT fk_inventory_product FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT fk_inventory_operator FOREIGN KEY (operator_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3) 商品加库存列与成本价列（毛利率报表用）
ALTER TABLE products
    ADD COLUMN stock INT NOT NULL DEFAULT 0,
    ADD COLUMN cost_price DECIMAL(14,4) NOT NULL DEFAULT 0;

-- 4) 用户加会员标记（会员=高级货主）
ALTER TABLE users ADD COLUMN is_member TINYINT(1) NOT NULL DEFAULT 0;

-- 5) 订单加支付列
ALTER TABLE orders
    ADD COLUMN payment_method VARCHAR(16) NOT NULL DEFAULT 'cash',
    ADD COLUMN paid TINYINT(1) NOT NULL DEFAULT 0,
    ADD COLUMN arrears_unit_id INT NULL,
    ADD COLUMN arrears_unit_name VARCHAR(128) NOT NULL DEFAULT '',
    ADD CONSTRAINT fk_order_arrears_unit FOREIGN KEY (arrears_unit_id) REFERENCES arrears_units (id);
