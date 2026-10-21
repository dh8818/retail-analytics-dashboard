# -*- coding: utf-8 -*-
"""
时区归位：带 UTC 偏移的时间戳（2026-01-01T20:00:00Z / +00:00）按 UTC 日期分组会错一天，
这里统一换算成目标时区（默认 Asia/Shanghai）的本地时间，再交给后续聚合。

只处理「确实带时区」的列；本地时间（无偏移）原样不动。
"""
import re

import pandas as pd

_TZ_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})\s*$", re.I)


def _has_offset(series, sample=200):
    v = series.dropna().astype(str).head(sample)
    if v.empty:
        return False
    return bool(v.str.contains(_TZ_RE, regex=True).mean() > 0.6)


def to_local_dates(df, tz="Asia/Shanghai"):
    """把带时区的列换算到本地时区并去掉时区信息。返回 (新表, 处理过的列名)。"""
    if df is None or len(df.columns) == 0:
        return df, []
    out = df.copy()
    fixed = []

    for c in out.columns:
        s = out[c]
        # 已经是带时区的 datetime
        if pd.api.types.is_datetime64_any_dtype(s):
            try:
                if getattr(s.dt, "tz", None) is not None:
                    out[c] = s.dt.tz_convert(tz).dt.tz_localize(None)
                    fixed.append(str(c))
            except Exception:
                pass
            continue

        # 字符串里带 Z / +08:00 这类偏移
        if pd.api.types.is_string_dtype(s) or s.dtype == object:
            if not _has_offset(s):
                continue
            parsed = pd.to_datetime(s, errors="coerce", utc=True)
            if parsed.notna().mean() > 0.8:
                out[c] = parsed.dt.tz_convert(tz).dt.tz_localize(None)
                fixed.append(str(c))

    return out, fixed
