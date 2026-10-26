# -*- coding: utf-8 -*-
"""
数据源抽象层：把「上传 Excel/CSV」扩展为「可插拔的数据源连接」。

设计目标（对应第 1 项需求：数据接入）：
- 定义统一的数据源协议，任何收银/进销存系统只要实现一个连接器，
  就能把「销售、库存、会员」三类交易数据拉进来，喂给现有分析链路。
- 数据拉取是「增量」的：记录每个数据源的 last_sync 游标，
  下次只拉新增数据，降低重复拉取。
- 拉到的数据统一成三张标准表（销售明细 / 库存快照 / 会员），
  字段名按标准约定输出，下游分析（app.py）无需改代码。

数据落本地 SQLite 持久化（对应「先单机跑通」的后端选型）：
- 数据源的元信息、增量游标、拉取到的数据快照都存进一个本地 SQLite 文件，
  关掉再打开还在，不用每次重新上传。

关键抽象：
- DataSource：一个连接器的实例，负责 connect / fetch(since) / health。
- fetch 返回 {sales, inventory, members} 三张 pandas DataFrame（或 None）。
- 连接器用装饰器 @register_source("name") 注册，界面按名字列出。

标准输出表字段约定（下游按这些列名取数）：
  销售明细：订单号/日期/时间/SKU/名称/品类/数量/单价/金额/成本/会员编号/门店编码
  库存快照：SKU/名称/品类/期末库存/在途/保质期天/单位成本/门店编码/日期
  会员：会员编号/最近购买/购买频次/累计金额/门店编码
"""
from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import pandas as pd

# 标准销售明细列（连接器尽量对齐这些名字；对不齐由 _normalize 映射）
SALES_COLS = ["订单号", "日期", "时间", "SKU", "名称", "品类", "数量",
              "单价", "金额", "成本", "会员编号", "门店编码"]
INVENTORY_COLS = ["SKU", "名称", "品类", "期末库存", "在途", "保质期天",
                  "单位成本", "门店编码", "日期"]
MEMBER_COLS = ["会员编号", "最近购买", "购买频次", "累计金额", "门店编码"]


class DataSource(ABC):
    """数据源连接器基类。实现一个具体系统时继承它，填 connect/fetch/health。"""

    key: str = "base"          # 唯一标识，注册时用
    label: str = "未命名数据源"

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    def fetch(self, since: str | None = None) -> dict[str, pd.DataFrame | None]:
        """拉取数据。since 为增量游标（ISO 日期时间），None 表示全量。

        返回 {'sales': df|None, 'inventory': df|None, 'members': df|None}。
        各表若该数据源不提供，返回 None。
        """

    def health(self) -> dict:
        """自检：返回 {'ok': bool, 'msg': str}。默认认为可用，子类可覆盖。"""
        return {"ok": True, "msg": f"{self.label} 可用"}

    def normalize(self, fetched: dict[str, pd.DataFrame | None]) -> dict[str, pd.DataFrame | None]:
        """把连接器吐出的字段对齐到标准列名（容错：缺失列填 NaN）。"""
        out = {}
        spec = {"sales": SALES_COLS, "inventory": INVENTORY_COLS, "members": MEMBER_COLS}
        for name, cols in spec.items():
            df = fetched.get(name)
            if df is None or df.empty:
                out[name] = None
                continue
            d = df.copy()
            for c in cols:
                if c not in d.columns:
                    d[c] = None
            out[name] = d[cols]
        return out


# ---------------- 连接器注册表 ----------------
_REGISTRY: dict[str, type] = {}


def register_source(cls):
    """装饰器：把一个 DataSource 子类注册到全局表，界面按 key 列出。"""
    _REGISTRY[cls.key] = cls
    return cls


def available_sources() -> list[dict]:
    """列出所有已注册的连接器（名称、标识、说明）。"""
    return [{"key": cls.key, "label": cls.label} for cls in _REGISTRY.values()]


def create_source(key: str, config: dict | None = None) -> DataSource:
    cls = _REGISTRY.get(key)
    if cls is None:
        raise KeyError(f"未注册的数据源：{key}。可用：{list(_REGISTRY)}")
    return cls(config)


# ---------------- 本地 SQLite 持久化 ----------------
DEFAULT_DB = Path(__file__).resolve().parent / "data" / "stores.db"


class Store:
    """本地 SQLite 存储：数据源元信息、增量游标、数据快照、门店与任务。

    单机先跑通多门店/数据接入；后续要上云时，把这里换成远端 DB 即可，
    上层 DataSource / scheduler / stores 的调用协议不变。
    """

    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._init_schema()

    def _init_schema(self):
        c = self._conn
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                key TEXT PRIMARY KEY,
                label TEXT,
                config TEXT,
                last_sync TEXT
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                source_key TEXT,
                kind TEXT,            -- sales / inventory / members
                fetched_at TEXT,
                rows INTEGER,
                payload TEXT          -- JSON 序列化的数据（先单机，规模大时换 Parquet）
            );
            CREATE TABLE IF NOT EXISTS stores (
                code TEXT PRIMARY KEY,      -- 门店编码
                name TEXT,
                region TEXT,                -- 区域
                parent TEXT                 -- 上级（区域/总部）
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT,
                role TEXT,                 -- boss / region_manager / store_manager
                scope TEXT                 -- 可见范围：门店编码或区域名
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                topic TEXT,               -- 异常预警 / 日报 / 周报
                channel TEXT,             -- wecom / email / local
                rule TEXT                 -- JSON 规则
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                schedule TEXT,            -- cron / interval
                source_key TEXT,
                enabled INTEGER DEFAULT 1
            );
            """
        )
        self._conn.commit()

    def close(self):
        self._conn.close()

    # ---- 数据源游标 ----
    def get_since(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT last_sync FROM sources WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_since(self, key: str, label: str, config: dict, ts: str):
        self._conn.execute(
            "INSERT INTO sources(key,label,config,last_sync) VALUES(?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET label=excluded.label,"
            "config=excluded.config,last_sync=excluded.last_sync",
            (key, label, json.dumps(config, ensure_ascii=False), ts))
        self._conn.commit()

    def save_snapshot(self, source_key: str, kind: str, df: pd.DataFrame):
        if df is None or df.empty:
            return
        self._conn.execute(
            "INSERT INTO snapshots(source_key,kind,fetched_at,rows,payload) "
            "VALUES(?,?,?,?,?)",
            (source_key, kind, datetime.now().isoformat(timespec="seconds"),
             len(df), df.to_json(orient="records", force_ascii=False)))
        self._conn.commit()

    def load_snapshot(self, source_key: str, kind: str) -> pd.DataFrame:
        row = self._conn.execute(
            "SELECT payload FROM snapshots WHERE source_key=? AND kind=? "
            "ORDER BY fetched_at DESC LIMIT 1", (source_key, kind)).fetchone()
        if not row:
            return pd.DataFrame()
        # pandas 新版的 read_json 对「字符串参数」默认当文件路径处理，
        # 这里显式用 StringIO 包起来，避免把它误当路径读
        import io as _io
        return pd.read_json(_io.StringIO(row[0]), orient="records")
