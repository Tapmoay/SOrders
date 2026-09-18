import sys, pkgutil, importlib
sys.path.insert(0, "/opt/SOrders/backend")
import sqlalchemy as sa
from app.database import engine

# 加载 app.models 下所有子模块（触发 Base.metadata 注册）
import app.models as m
for mod in pkgutil.iter_modules(m.__path__):
    if mod.name.startswith("_"): continue
    try: importlib.import_module(f"app.models.{mod.name}")
    except Exception as e: print("skip", mod.name, e)
from app.models.base import Base

insp = sa.inspect(engine)
tables = insp.get_table_names()
print("real tables:", len(tables))
issues = []
for table in Base.metadata.tables.values():
    tname = table.name
    if tname not in tables:
        issues.append("MISSING_TABLE " + tname)
        continue
    real = {c["name"] for c in insp.get_columns(tname)}
    for col in table.columns:
        if col.name not in real:
            ctype = str(col.type)
            nullable = "NULL" if col.nullable else "NOT NULL"
            issues.append("ALTER TABLE " + tname + " ADD COLUMN " + col.name + " " + ctype + " " + nullable)

print("ISSUES:", len(issues))
for i in issues: print(i)