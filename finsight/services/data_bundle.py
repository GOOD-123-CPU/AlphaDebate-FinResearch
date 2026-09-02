"""结构化行情数据服务：基于 AkShare 抓取 A 股行情/财务/行业快照，带本地 JSON 缓存。

数据来源：
- AkShare（开源财经数据接口，数据来自公开交易所/东财页面）
- 东方财富公开搜索接口（兜底）
仅使用公开数据，抓取行为遵守来源站点公开访问约定。
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List
from urllib import request

try:
    import akshare as ak  # noqa: N813
    import pandas as pd
except ImportError as _exc:  # pragma: no cover
    raise ImportError(
        "缺少数据抓取依赖。请先安装: pip install akshare pandas"
    ) from _exc

from finsight.config import config

logger = logging.getLogger(__name__)

CACHE_DIR = config.CACHE_DIR
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL_MINUTES = config.CACHE_TTL_MINUTES

WEB_FALLBACK_URLS = {
    "eastmoney_quote": "https://quote.eastmoney.com/concept/",
    "xueqiu_stock": "https://xueqiu.com/S/",
    "eastmoney_search_api": "https://searchapi.eastmoney.com/api/suggest/get",
}

SH_CODE_PREFIXES = ("600", "601", "603", "605", "688")
SZ_CODE_PREFIXES = ("000", "001", "002", "003", "300")
BJ_CODE_PREFIXES = (
    "430", "830", "831", "832", "833", "834", "835", "836", "837", "838", "839",
    "870", "871", "872", "873", "874", "875", "876", "877", "878", "879",
)


def normalize_stock_code(stock_code: str) -> Dict[str, str]:
    raw = (stock_code or "").strip().upper()
    if not raw:
        raise ValueError("stock_code 不能为空")

    token = raw.replace(".", "")
    pure = "".join(ch for ch in token if ch.isdigit())
    pure = pure[-6:] if len(pure) >= 6 else pure

    if pure.startswith(SH_CODE_PREFIXES):
        market, ak_prefix, xq_prefix = "SH", "sh", "SH"
    elif pure.startswith(SZ_CODE_PREFIXES):
        market, ak_prefix, xq_prefix = "SZ", "sz", "SZ"
    elif pure.startswith(BJ_CODE_PREFIXES):
        market, ak_prefix, xq_prefix = "BJ", "bj", "BJ"
    else:
        market, ak_prefix, xq_prefix = "UNKNOWN", "", ""

    return {
        "raw": raw,
        "pure": pure,
        "market": market,
        "full_code": f"{pure}.{market}" if market != "UNKNOWN" else pure,
        "ak_code": pure,
        "prefixed_code": f"{ak_prefix}{pure}" if ak_prefix else pure,
        "xq_code": f"{xq_prefix}{pure}" if xq_prefix else pure,
    }


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_float(value: Any) -> Any:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return value


def _safe_int(value: Any) -> Any:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return value


def _component_cache_path(pure_code: str, component: str) -> Path:
    return CACHE_DIR / f"{pure_code}_{component}.json"


def _bundle_cache_path(pure_code: str) -> Path:
    return CACHE_DIR / f"{pure_code}.json"


def _is_cache_valid(generated_at: str) -> bool:
    if not generated_at:
        return False
    try:
        created = datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return False
    return datetime.now() - created <= timedelta(minutes=CACHE_TTL_MINUTES)


def _load_json_cache(cache_path: Path) -> Dict[str, Any]:
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("读取缓存失败 %s: %s", cache_path.name, exc)
        return {}


def _save_json_cache(cache_path: Path, payload: Dict[str, Any]) -> None:
    try:
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("写入缓存失败 %s: %s", cache_path.name, exc)


def _default_component_payload(component: str, cache_path: Path) -> Dict[str, Any]:
    defaults = {
        "spot": {},
        "history": {"records": [], "summary": {}},
        "financial": {"latest": {}, "records": []},
        "industry": {},
        "web_search": {"records": [], "summary": {}},
    }
    return {
        "component": component,
        "data": defaults[component],
        "generated_at": "",
        "success": False,
        "used_cache": False,
        "cache_path": str(cache_path),
        "error": "",
    }


def _load_component_cache(pure_code: str, component: str) -> Dict[str, Any]:
    cache_path = _component_cache_path(pure_code, component)
    payload = _load_json_cache(cache_path)
    if not payload or not _is_cache_valid(payload.get("generated_at", "")):
        return _default_component_payload(component, cache_path)
    payload.setdefault("component", component)
    payload.setdefault("cache_path", str(cache_path))
    payload["used_cache"] = True
    return payload


def _save_component_cache(
    pure_code: str, component: str, data: Dict[str, Any], success: bool, error_message: str
) -> Dict[str, Any]:
    cache_path = _component_cache_path(pure_code, component)
    payload = {
        "component": component,
        "data": data,
        "generated_at": _now_str(),
        "success": success,
        "used_cache": False,
        "cache_path": str(cache_path),
        "error": error_message,
    }
    _save_json_cache(cache_path, payload)
    return payload


def _error_message(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _fetch_component_with_cache(
    stock_code: str,
    component: str,
    fetcher: Callable[[str], Dict[str, Any]],
    force_refresh: bool,
) -> Dict[str, Any]:
    normalized = normalize_stock_code(stock_code)
    if not force_refresh:
        cached = _load_component_cache(normalized["pure"], component)
        if cached.get("used_cache"):
            return cached

    try:
        data = fetcher(stock_code)
        return _save_component_cache(normalized["pure"], component, data, True, "")
    except Exception as exc:
        logger.warning("获取 %s 失败: %s", component, exc)
        cached = _load_component_cache(normalized["pure"], component)
        if cached.get("used_cache"):
            cached["error"] = _error_message(exc)
            return cached
        fallback_data = _default_component_payload(
            component, _component_cache_path(normalized["pure"], component)
        )["data"]
        return _save_component_cache(normalized["pure"], component, fallback_data, False, _error_message(exc))


def _select_spot_row(df: pd.DataFrame, pure_code: str) -> Dict[str, Any]:
    if df.empty:
        raise ValueError(f"实时行情为空: {pure_code}")
    code_series = df["代码"].astype(str).str.zfill(6)
    matched = df.loc[code_series == pure_code]
    if matched.empty:
        raise ValueError(f"未在实时行情中找到股票: {pure_code}")
    return matched.iloc[0].to_dict()


def _fetch_spot_dataframe(normalized: Dict[str, str]) -> pd.DataFrame:
    market = normalized["market"]
    if market == "SH":
        return ak.stock_sh_a_spot_em()
    if market == "SZ":
        return ak.stock_sz_a_spot_em()
    if market == "BJ":
        return ak.stock_bj_a_spot_em()
    return ak.stock_zh_a_spot_em()


def _safe_get_individual_info(symbol: str) -> Dict[str, Any]:
    try:
        info_df = ak.stock_individual_info_em(symbol=symbol)
    except Exception as exc:
        logger.warning("获取个股信息失败 %s: %s", symbol, exc)
        return {}
    if info_df.empty or "item" not in info_df.columns or "value" not in info_df.columns:
        return {}
    return {str(row["item"]): row["value"] for _, row in info_df.iterrows()}


def _safe_get_company_profile(normalized: Dict[str, str]) -> Dict[str, Any]:
    try:
        profile_df = ak.stock_individual_basic_info_xq(symbol=normalized["xq_code"])
    except Exception as exc:
        logger.warning("获取公司概况失败 %s: %s", normalized["xq_code"], exc)
        return {}
    if profile_df.empty or "item" not in profile_df.columns or "value" not in profile_df.columns:
        return {}
    return {str(row["item"]): row["value"] for _, row in profile_df.iterrows()}


def _http_get_json(url: str) -> Dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        },
        method="GET",
    )
    opener = request.build_opener(request.ProxyHandler({}))
    with opener.open(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _safe_get_eastmoney_search(normalized: Dict[str, str]) -> Dict[str, Any]:
    secid = f"{1 if normalized['market'] == 'SH' else 0}.{normalized['pure']}"
    url = (
        f"{WEB_FALLBACK_URLS['eastmoney_search_api']}?input={normalized['pure']}&type=14"
        "&token=D43BF722C8E33BDC906FB84D85E326E8"
    )
    try:
        payload = _http_get_json(url)
    except Exception as exc:
        logger.warning("Eastmoney search fallback failed %s: %s", normalized["pure"], exc)
        return {"query_url": url, "secid": secid, "matches": []}

    matches = payload.get("QuotationCodeTable", {}).get("Data", []) or []
    simplified = []
    for item in matches[:5]:
        simplified.append(
            {
                "code": item.get("Code"),
                "name": item.get("Name"),
                "pin_yin": item.get("PinYin"),
                "market": item.get("SecurityTypeName"),
                "quote_id": item.get("QuoteID"),
            }
        )
    return {"query_url": url, "secid": secid, "matches": simplified}


def fetch_stock_spot(stock_code: str) -> Dict[str, Any]:
    normalized = normalize_stock_code(stock_code)
    spot_df = _fetch_spot_dataframe(normalized)
    row = _select_spot_row(spot_df, normalized["pure"])
    info_map = _safe_get_individual_info(normalized["pure"])

    latest_price = _safe_float(row.get("最新价"))
    total_market_value = _safe_float(row.get("总市值") or info_map.get("总市值"))
    circulating_market_value = _safe_float(row.get("流通市值") or info_map.get("流通市值"))

    return {
        "代码": normalized["pure"],
        "名称": row.get("名称") or info_map.get("股票简称") or "",
        "最新价": latest_price,
        "涨跌幅": _safe_float(row.get("涨跌幅")),
        "换手率": _safe_float(row.get("换手率")),
        "总市值": total_market_value,
        "流通市值": circulating_market_value,
        "市盈率-动态": _safe_float(row.get("市盈率-动态")),
        "市净率": _safe_float(row.get("市净率")),
        "涨跌额": _safe_float(row.get("涨跌额")),
        "成交量": _safe_float(row.get("成交量")),
        "成交额": _safe_float(row.get("成交额")),
        "振幅": _safe_float(row.get("振幅")),
        "最高": _safe_float(row.get("最高")),
        "最低": _safe_float(row.get("最低")),
        "今开": _safe_float(row.get("今开")),
        "昨收": _safe_float(row.get("昨收")),
        "量比": _safe_float(row.get("量比")),
        "60日涨跌幅": _safe_float(row.get("60日涨跌幅")),
        "年初至今涨跌幅": _safe_float(row.get("年初至今涨跌幅")),
        "总股本": _safe_float(info_map.get("总股本")),
        "流通股": _safe_float(info_map.get("流通股")),
        "行业": info_map.get("行业", ""),
        "上市时间": str(info_map.get("上市时间", "")),
    }


def fetch_stock_history(stock_code: str, days: int = 180) -> Dict[str, Any]:
    normalized = normalize_stock_code(stock_code)
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")
    df = ak.stock_zh_a_hist(
        symbol=normalized["pure"],
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",
    )

    if df.empty:
        raise ValueError(f"历史行情为空: {normalized['pure']}")

    numeric_columns = ["开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    first_close = _safe_float(df.iloc[0]["收盘"])
    last_close = _safe_float(df.iloc[-1]["收盘"])
    pct_change = None
    if isinstance(first_close, float) and first_close:
        pct_change = round((last_close - first_close) / first_close * 100, 2)

    summary = {
        "start_date": str(df.iloc[0]["日期"]),
        "end_date": str(df.iloc[-1]["日期"]),
        "first_close": first_close,
        "last_close": last_close,
        "period_pct_change": pct_change,
        "period_high": _safe_float(df["最高"].max()),
        "period_low": _safe_float(df["最低"].min()),
        "avg_amount": _safe_float(df["成交额"].tail(20).mean()),
        "avg_pct_change": _safe_float(df["涨跌幅"].tail(20).mean()),
    }
    records = df.tail(30).to_dict(orient="records")
    return {
        "records": json.loads(json.dumps(records, ensure_ascii=False, default=str)),
        "summary": summary,
    }


def fetch_financial_summary(stock_code: str) -> Dict[str, Any]:
    normalized = normalize_stock_code(stock_code)
    info_map = _safe_get_individual_info(normalized["pure"])
    profile_map = _safe_get_company_profile(normalized)

    latest = {
        "股票代码": normalized["pure"],
        "股票简称": info_map.get("股票简称", ""),
        "行业": info_map.get("行业", ""),
        "总股本": _safe_float(info_map.get("总股本")),
        "流通股": _safe_float(info_map.get("流通股")),
        "总市值": _safe_float(info_map.get("总市值")),
        "流通市值": _safe_float(info_map.get("流通市值")),
        "上市时间": str(info_map.get("上市时间", "")),
        "公司名称": profile_map.get("org_name_cn") or profile_map.get("org_short_name_cn") or info_map.get("股票简称", ""),
        "英文名称": profile_map.get("org_name_en"),
        "主营业务": profile_map.get("main_operation_business"),
        "经营范围": profile_map.get("operating_scope"),
        "公司简介": profile_map.get("org_cn_introduction"),
        "法定代表人": profile_map.get("legal_representative"),
        "总经理": profile_map.get("general_manager"),
        "董事长": profile_map.get("chairman"),
        "员工人数": _safe_int(profile_map.get("staff_num")),
        "注册资本": _safe_float(profile_map.get("reg_asset")),
        "注册地址": profile_map.get("reg_address_cn"),
        "办公地址": profile_map.get("office_address_cn"),
        "电话": profile_map.get("telephone"),
        "邮箱": profile_map.get("email"),
        "官网": profile_map.get("org_website"),
        "实际控制人": profile_map.get("actual_controller"),
        "企业性质": profile_map.get("classi_name"),
        "所属地区": profile_map.get("provincial_name"),
        "上市日期": str(profile_map.get("listed_date", "")),
        "发行价格": _safe_float(profile_map.get("issue_price")),
        "发行数量": _safe_float(profile_map.get("actual_issue_vol")),
        "募集资金净额": _safe_float(profile_map.get("actual_rc_net_amt")),
        "发行后市盈率": _safe_float(profile_map.get("pe_after_issuing")),
    }

    records = [{"item": key, "value": value} for key, value in latest.items() if value not in (None, "")]
    if not records:
        raise ValueError(f"财务/公司概况为空: {normalized['pure']}")

    return {
        "latest": json.loads(json.dumps(latest, ensure_ascii=False, default=str)),
        "records": json.loads(json.dumps(records, ensure_ascii=False, default=str)),
    }


def fetch_industry_snapshot(stock_code: str) -> Dict[str, Any]:
    normalized = normalize_stock_code(stock_code)
    spot_payload = _load_component_cache(normalized["pure"], "spot")
    financial_payload = _load_component_cache(normalized["pure"], "financial")
    web_payload = _load_component_cache(normalized["pure"], "web_search")
    spot = spot_payload.get("data", {}) if spot_payload.get("success") else {}
    financial = financial_payload.get("data", {}) if financial_payload.get("success") else {}
    latest = financial.get("latest", {})
    web_summary = web_payload.get("data", {}).get("summary", {}) if web_payload.get("success") else {}

    if not spot and not latest and not web_summary:
        raise ValueError(f"行业快照依赖行情/公司资料，但可用数据为空: {normalized['pure']}")

    return {
        "name": latest.get("行业") or spot.get("行业") or web_summary.get("company_name", ""),
        "code": normalized["full_code"],
        "company_name": latest.get("公司名称") or spot.get("名称") or web_summary.get("company_name", ""),
        "main_business": latest.get("主营业务") or web_summary.get("main_business"),
        "company_intro": latest.get("公司简介") or web_summary.get("notes"),
        "pe_dynamic": spot.get("市盈率-动态"),
        "pb": spot.get("市净率"),
        "turnover_rate": spot.get("换手率"),
        "total_market_value": spot.get("总市值") or web_summary.get("market_value_hint"),
        "circulating_market_value": spot.get("流通市值"),
        "actual_controller": latest.get("实际控制人"),
        "company_type": latest.get("企业性质"),
        "region": latest.get("所属地区"),
    }


def fetch_web_search_snapshot(stock_code: str) -> Dict[str, Any]:
    normalized = normalize_stock_code(stock_code)
    quote_url = f"{WEB_FALLBACK_URLS['eastmoney_quote']}{normalized['prefixed_code']}.html"
    xq_url = f"{WEB_FALLBACK_URLS['xueqiu_stock']}{normalized['xq_code']}"
    eastmoney_search = _safe_get_eastmoney_search(normalized)
    best_match = eastmoney_search.get("matches", [{}])[0] if eastmoney_search.get("matches") else {}

    records = [
        {
            "source": "eastmoney_quote_page",
            "url": quote_url,
            "description": "可用于补充个股行情页、公司简称、部分基础资料",
        },
        {
            "source": "xueqiu_stock_page",
            "url": xq_url,
            "description": "可用于补充公司概况、主营业务、管理层与市场关注点",
        },
        {
            "source": "eastmoney_search_api",
            "url": eastmoney_search.get("query_url"),
            "description": "自动搜索返回的候选证券信息，可辅助校验公司全称和市场类别",
            "matches": eastmoney_search.get("matches", []),
        },
    ]
    summary = {
        "fallback_enabled": True,
        "message": "当 AkShare 接口抓取失败时，可基于这些网页入口和搜索结果补充公司名称、市场类别、主营业务等公开信息。",
        "stock_code": normalized["full_code"],
        "company_name": best_match.get("name", ""),
        "market_type": best_match.get("market", ""),
        "market_value_hint": None,
        "main_business": None,
        "notes": "网页补充数据以公开页面为准，使用时需交叉验证。",
    }
    return {
        "records": records,
        "summary": summary,
    }


def _build_component_status(component_payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "success": bool(component_payload.get("success")),
        "used_cache": bool(component_payload.get("used_cache")),
        "generated_at": component_payload.get("generated_at", ""),
        "cache_path": component_payload.get("cache_path", ""),
        "error": component_payload.get("error", ""),
    }


def build_stock_data_bundle(stock_code: str, stock_name: str, force_refresh: bool = False) -> Dict[str, Any]:
    """抓取并组装一只股票的全部结构化数据（行情/历史/财务/行业/网页兜底）。"""
    normalized = normalize_stock_code(stock_code)
    components = {
        "spot": _fetch_component_with_cache(stock_code, "spot", fetch_stock_spot, force_refresh),
        "history": _fetch_component_with_cache(stock_code, "history", fetch_stock_history, force_refresh),
        "financial": _fetch_component_with_cache(stock_code, "financial", fetch_financial_summary, force_refresh),
        "industry": _fetch_component_with_cache(stock_code, "industry", fetch_industry_snapshot, force_refresh),
        "web_search": _fetch_component_with_cache(stock_code, "web_search", fetch_web_search_snapshot, force_refresh),
    }

    component_status = {name: _build_component_status(payload) for name, payload in components.items()}
    used_cache = any(status["used_cache"] for status in component_status.values())
    failed_components = [name for name, status in component_status.items() if not status["success"]]

    bundle = {
        "stock": {
            "stock_code": normalized["full_code"],
            "stock_name": stock_name,
            "pure_code": normalized["pure"],
            "market": normalized["market"],
        },
        "spot": components["spot"]["data"],
        "history": components["history"]["data"],
        "financial": components["financial"]["data"],
        "industry": components["industry"]["data"],
        "web_search": components["web_search"]["data"],
        "source": "akshare",
        "generated_at": _now_str(),
        "cache_info": {
            "used_cache": used_cache,
            "cache_path": str(_bundle_cache_path(normalized["pure"])),
            "cache_ttl_minutes": CACHE_TTL_MINUTES,
            "components": component_status,
            "failed_components": failed_components,
        },
    }
    _save_json_cache(_bundle_cache_path(normalized["pure"]), bundle)
    return bundle


# ---------------------------------------------------------------------------
# 全市场股票搜索（供前端股票搜索框使用）
# ---------------------------------------------------------------------------

_SEARCH_CACHE_PATH = CACHE_DIR / "stock_search_cache.json"
_SEARCH_CACHE_TTL_SECONDS = 6 * 3600  # 搜索底表 6 小时刷新一次
_SEARCH_SPOT_FUNCS = (
    ("SH", ak.stock_sh_a_spot_em),
    ("SZ", ak.stock_sz_a_spot_em),
    ("BJ", ak.stock_bj_a_spot_em),
)


def _load_search_cache() -> Dict[str, Any]:
    try:
        payload = json.loads(_SEARCH_CACHE_PATH.read_text(encoding="utf-8"))
        generated_at = payload.get("generated_at", "")
        age = datetime.now() - datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S")
        if age.total_seconds() < _SEARCH_CACHE_TTL_SECONDS:
            return payload
    except Exception:
        pass
    return {}


def _save_search_cache(payload: Dict[str, Any]) -> None:
    try:
        _SEARCH_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def _build_search_table() -> List[Dict[str, Any]]:
    """构建全市场 A 股代码/名称底表（沪+深+北，带 6 小时缓存）。"""
    cached = _load_search_cache()
    if cached.get("stocks"):
        return cached["stocks"]

    table: List[Dict[str, Any]] = []
    for market, fetch in _SEARCH_SPOT_FUNCS:
        try:
            df = fetch()
            if df is None or df.empty or "代码" not in df.columns:
                continue
            for _, row in df.iterrows():
                code = str(row.get("代码", "")).zfill(6)
                name = str(row.get("名称", "")).strip()
                if not code or not name:
                    continue
                table.append({
                    "code": code,
                    "name": name,
                    "market": market,
                    "price": _safe_float(row.get("最新价")),
                    "pct_change": _safe_float(row.get("涨跌幅")),
                })
        except Exception as exc:
            logger.warning("构建股票搜索底表(%s)失败: %s", market, exc)

    if table:
        _save_search_cache({"generated_at": _now_str(), "stocks": table})
    return table


def search_stocks(keyword: str, limit: int = 20) -> Dict[str, Any]:
    """按代码或名称关键词模糊搜索全市场 A 股。

    纯数字关键词优先做代码前缀匹配；否则做名称包含匹配。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"keyword": keyword, "results": [], "total": 0}

    table = _build_search_table()
    if not table:
        return {"keyword": keyword, "results": [], "total": 0, "error": "搜索底表暂不可用（行情接口暂时不可达）"}

    kw_upper = keyword.upper()
    is_numeric = kw_upper.isdigit()
    results: List[Dict[str, Any]] = []

    for item in table:
        if is_numeric:
            if item["code"].startswith(kw_upper):
                results.append(item)
        else:
            if kw_upper in item["name"].upper():
                results.append(item)
        if len(results) >= limit:
            break

    return {"keyword": keyword, "results": results, "total": len(results)}
