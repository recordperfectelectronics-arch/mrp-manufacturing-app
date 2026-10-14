"""
Factory LAN Real-Time MRP & RM Shortage Engine
Streamlit Application (app.py)

Production Netting Logic:
  Total Available FG = Daily FG Stock + Daily WIP Stock
  Net FG To Produce = max(0, Open Order Qty - Total Available FG)
  Gross RM Required = Net FG To Produce * BOM Usage
  Net RM Shortage = max(0, Total Factory RM Demand - Current Warehouse Stock)
  Coverage % = min(100%, (Current Warehouse Stock / Total Factory RM Demand) * 100)
"""

import os
import re
import json
import logging
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

import streamlit as st
import pandas as pd

# Try importing gspread and google oauth
try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("InvenMRP")

# -----------------------------------------------------------------------------
# 1. APPLICATION & UI SETUP
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Factory LAN Real-Time MRP & RM Shortage Engine",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Dark slate aesthetic CSS injection
st.markdown("""
<style>
    /* Dark Theme Base Styling */
    .stApp {
        background-color: #0b0f19;
        color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Top Header Strip */
    .mrp-header-container {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
        border: 1px solid #312e81;
        border-radius: 16px;
        padding: 20px 24px;
        margin-bottom: 24px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
    }
    .mrp-title {
        color: #ffffff;
        font-size: 24px;
        font-weight: 800;
        letter-spacing: -0.025em;
        margin: 0;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .mrp-subtitle {
        color: #94a3b8;
        font-size: 13px;
        margin-top: 4px;
    }
    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 700;
        background-color: rgba(16, 185, 129, 0.15);
        color: #34d399;
        border: 1px solid rgba(16, 185, 129, 0.3);
    }
    
    /* KPI Metric Cards */
    .kpi-card {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 14px;
        padding: 16px 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .kpi-card:hover {
        border-color: #6366f1;
        transform: translateY(-2px);
    }
    .kpi-label {
        color: #94a3b8;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 6px;
    }
    .kpi-value {
        font-size: 28px;
        font-weight: 800;
        line-height: 1.1;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    .kpi-subtext {
        font-size: 12px;
        color: #64748b;
        margin-top: 6px;
    }
    
    /* Highlight Badges */
    .badge-completed {
        background-color: rgba(16, 185, 129, 0.2);
        color: #10b981;
        border: 1px solid #10b981;
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 11px;
    }
    .badge-partial {
        background-color: rgba(245, 158, 11, 0.2);
        color: #f59e0b;
        border: 1px solid #f59e0b;
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 11px;
    }
    .badge-shortage {
        background-color: rgba(239, 68, 68, 0.2);
        color: #ef4444;
        border: 1px solid #ef4444;
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 11px;
    }
    
    /* Streamlit Tab Customization */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #0f172a;
        padding: 6px;
        border-radius: 12px;
        border: 1px solid #1e293b;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        color: #94a3b8;
        font-weight: 600;
        font-size: 13px;
        padding: 8px 16px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #312e81 !important;
        color: #ffffff !important;
    }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 2. DATA CLEANING & NORMALIZATION UTILITIES
# -----------------------------------------------------------------------------
def clean_numeric(val: Any) -> float:
    """Strip currency, commas, unit suffixes (Kgs, Nos, Pcs, mtrs) to float."""
    if val is None or pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip().replace(',', '')
    match = re.search(r"[-+]?\d*\.?\d+", val_str)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return 0.0
    return 0.0

def normalize_part_no(part: Any) -> str:
    """Normalize finished goods or WIP code to primary part key."""
    if part is None or pd.isna(part):
        return ""
    p_str = str(part).strip()
    if p_str.upper().startswith("WIP_"):
        p_str = p_str[4:].strip()
    # Find patterns like 9010-8452 or 9096-8371
    match = re.search(r"\b(\d{4}[-\s]\d{4}[A-Za-z]?)\b", p_str)
    if match:
        return match.group(1).replace(" ", "-").upper()
    return p_str.upper()

def normalize_rm_code(code: Any) -> str:
    """Normalize raw material part number for strict matching."""
    if code is None or pd.isna(code):
        return ""
    code_str = str(code).strip()
    code_str = re.sub(r"\s+", " ", code_str)
    return code_str.upper()


# -----------------------------------------------------------------------------
# 3. GOOGLE SHEETS & LOCAL DATA INGESTION ENGINE
# -----------------------------------------------------------------------------
SHEETS_CONFIG = {
    "ORDERS": {
        "url": "https://docs.google.com/spreadsheets/d/1-bVdXQ7eDiRF3876wHDdaD94kbVRII7Mq3DU37e4EGg/edit",
        "tab": "14-10-2026",
        "gid": 0
    },
    "FG_STOCK": {
        "url": "https://docs.google.com/spreadsheets/d/1F7a15XQvWvRBjFOWRO2-gSiMfj3vw16c0FWUW28XCa4/edit",
        "tab": "14-10-2026",
        "gid": 0
    },
    "WIP_STOCK": {
        "url": "https://docs.google.com/spreadsheets/d/112padFLp9mRsSuN39Xy3umFOsjUmSOMvHPtnyIauNik/edit",
        "tab": "14-10-2026",
        "gid": 0
    },
    "BOM": {
        "url": "https://docs.google.com/spreadsheets/d/1JKoQnYm1BSBkZUVSqYYXsb8VshuWo9tyar3dUtetnHk/edit",
        "tab": "MASTER BOM-19.03.2026",
        "gid": 199313343
    },
    "STOCKS": {
        "url": "https://docs.google.com/spreadsheets/d/1mmIHjG_BKIiV_02duivofXyJpWyM3T_h_Fq670m7eaU/edit",
        "tab": "Stocks",
        "gid": 82202164
    }
}

def get_gspread_client() -> Optional[Any]:
    """Authenticates gspread using local service_account.json if present."""
    if not HAS_GSPREAD:
        return None
    cred_paths = ["service_account.json", "credentials.json"]
    for path in cred_paths:
        if os.path.exists(path):
            try:
                scopes = [
                    "https://www.googleapis.com/auth/spreadsheets.readonly",
                    "https://www.googleapis.com/auth/drive.readonly"
                ]
                creds = Credentials.from_service_account_file(path, scopes=scopes)
                return gspread.authorize(creds)
            except Exception as e:
                logger.error(f"Error authenticating with {path}: {e}")
    return None

def fetch_sheet_as_df(client: Any, url: str, tab_name: str) -> Optional[pd.DataFrame]:
    """Reads a specific worksheet into pandas DataFrame."""
    try:
        sh = client.open_by_url(url)
        try:
            ws = sh.worksheet(tab_name)
        except Exception:
            ws = sh.get_worksheet(0)
        data = ws.get_all_values()
        if not data or len(data) < 2:
            return None
        # Try finding header in first 3 rows
        header_idx = 0
        for i in range(min(3, len(data))):
            row_vals = [str(x).strip().upper() for x in data[i]]
            if any("PARTICULARS" in v or "PART #" in v or "PART NO" in v or "ITEM" in v for v in row_vals):
                header_idx = i
                break
        headers = [str(c).strip() for c in data[header_idx]]
        df = pd.DataFrame(data[header_idx + 1:], columns=headers)
        return df
    except Exception as e:
        logger.warning(f"Failed to fetch {url} ({tab_name}): {e}")
        return None

@st.cache_data(ttl=600, show_spinner="Connecting to Data Engine & Ingesting Sheets...")
def load_all_mrp_data() -> Tuple[pd.DataFrame, Dict[str, float], Dict[str, float], pd.DataFrame, Dict[str, float], str]:
    """
    Loads Orders, FG Stocks, WIP Stocks, Master BOM, and RM Warehouse Stocks.
    Falls back gracefully to high-precision local synchronized store if service account is unavailable.
    """
    client = get_gspread_client()
    data_source_mode = "LIVE Google Sheets (via gspread)" if client else "Synchronized Production Cache"
    
    orders_df = None
    fg_stock_map: Dict[str, float] = {}
    wip_stock_map: Dict[str, float] = {}
    bom_df = None
    rm_stock_map: Dict[str, float] = {}
    
    # 1. ATTEMPT LIVE FETCH VIA GSPREAD
    if client:
        try:
            # 1.1 Open Orders
            raw_orders_df = fetch_sheet_as_df(client, SHEETS_CONFIG["ORDERS"]["url"], SHEETS_CONFIG["ORDERS"]["tab"])
            if raw_orders_df is not None:
                # Find columns
                part_col = next((c for c in raw_orders_df.columns if "PARTICULAR" in c.upper() or "PART" in c.upper() or "ITEM" in c.upper()), raw_orders_df.columns[0])
                qty_col = next((c for c in raw_orders_df.columns if "QTY" in c.upper() or "QUANTITY" in c.upper() or "OPEN" in c.upper()), raw_orders_df.columns[-1])
                
                parsed_orders = []
                for _, r in raw_orders_df.iterrows():
                    raw_p = str(r[part_col])
                    qty = clean_numeric(r[qty_col])
                    if qty > 0 and raw_p:
                        norm_p = normalize_part_no(raw_p)
                        parsed_orders.append({
                            "partNo": norm_p,
                            "desc": raw_p,
                            "customer": r.get("Customer", "") or r.get("CUSTOMER", ""),
                            "openQty": qty
                        })
                if parsed_orders:
                    orders_df = pd.DataFrame(parsed_orders)
            
            # 1.2 Daily FG Stock
            raw_fg_df = fetch_sheet_as_df(client, SHEETS_CONFIG["FG_STOCK"]["url"], SHEETS_CONFIG["FG_STOCK"]["tab"])
            if raw_fg_df is not None:
                part_col = next((c for c in raw_fg_df.columns if "PARTICULAR" in c.upper() or "PART" in c.upper()), raw_fg_df.columns[0])
                qty_col = next((c for c in raw_fg_df.columns if "QTY" in c.upper() or "BALANCE" in c.upper() or "STOCK" in c.upper()), raw_fg_df.columns[-1])
                for _, r in raw_fg_df.iterrows():
                    p = normalize_part_no(r[part_col])
                    q = clean_numeric(r[qty_col])
                    if p:
                        fg_stock_map[p] = fg_stock_map.get(p, 0.0) + q
                        
            # 1.3 Daily WIP Stock
            raw_wip_df = fetch_sheet_as_df(client, SHEETS_CONFIG["WIP_STOCK"]["url"], SHEETS_CONFIG["WIP_STOCK"]["tab"])
            if raw_wip_df is not None:
                part_col = next((c for c in raw_wip_df.columns if "PARTICULAR" in c.upper() or "PART" in c.upper()), raw_wip_df.columns[0])
                qty_col = next((c for c in raw_wip_df.columns if "QTY" in c.upper() or "WIP" in c.upper() or "BALANCE" in c.upper()), raw_wip_df.columns[-1])
                for _, r in raw_wip_df.iterrows():
                    p = normalize_part_no(r[part_col])
                    q = clean_numeric(r[qty_col])
                    if p:
                        wip_stock_map[p] = wip_stock_map.get(p, 0.0) + q
                        
            # 1.4 Master BOM
            raw_bom_df = fetch_sheet_as_df(client, SHEETS_CONFIG["BOM"]["url"], SHEETS_CONFIG["BOM"]["tab"])
            if raw_bom_df is not None:
                fg_col = next((c for c in raw_bom_df.columns if "PART #" in c.upper() or "CUSTOMER PART" in c.upper() or "FG" in c.upper()), raw_bom_df.columns[0])
                rm_col = next((c for c in raw_bom_df.columns if "RAW MATERIAL" in c.upper() or "RM PART" in c.upper()), raw_bom_df.columns[1])
                desc_col = next((c for c in raw_bom_df.columns if "DESC" in c.upper()), "Description")
                usage_col = next((c for c in raw_bom_df.columns if "USAGE" in c.upper() or "WEIGHT" in c.upper() or "QTY" in c.upper() or "RATIO" in c.upper()), raw_bom_df.columns[3])
                unit_col = next((c for c in raw_bom_df.columns if "UNIT" in c.upper()), "Unit")
                
                boms = []
                for _, r in raw_bom_df.iterrows():
                    fg_p = normalize_part_no(r[fg_col])
                    rm_p = normalize_rm_code(r[rm_col])
                    ratio = clean_numeric(r[usage_col])
                    if fg_p and rm_p and ratio > 0:
                        boms.append({
                            "fgPart": fg_p,
                            "rmPart": rm_p,
                            "rmDesc": str(r.get(desc_col, "")).strip(),
                            "ratio": ratio,
                            "unit": str(r.get(unit_col, "Nos")).strip()
                        })
                if boms:
                    bom_df = pd.DataFrame(boms)
                    
            # 1.5 RM Stocks
            raw_stocks_df = fetch_sheet_as_df(client, SHEETS_CONFIG["STOCKS"]["url"], SHEETS_CONFIG["STOCKS"]["tab"])
            if raw_stocks_df is not None:
                part_col = next((c for c in raw_stocks_df.columns if "PART" in c.upper() or "PARTICULAR" in c.upper() or "ITEM" in c.upper()), raw_stocks_df.columns[0])
                qty_col = next((c for c in raw_stocks_df.columns if "QTY" in c.upper() or "CLOSING" in c.upper() or "STOCK" in c.upper()), raw_stocks_df.columns[1])
                for _, r in raw_stocks_df.iterrows():
                    rm_c = normalize_rm_code(r[part_col])
                    sqty = clean_numeric(r[qty_col])
                    if rm_c:
                        rm_stock_map[rm_c] = rm_stock_map.get(rm_c, 0.0) + sqty
        except Exception as e:
            logger.error(f"Live GSpread error: {e}")
            data_source_mode = "Synchronized Production Cache (Fallback)"
            
    # 2. LOCAL SYNC FALLBACK IF GSPREAD IS OFFLINE / UNAUTHORIZED
    if orders_df is None or bom_df is None or len(rm_stock_map) == 0:
        data_source_mode = "Synchronized Production Cache (Direct Local Sync)"
        
        # Load Orders
        if os.path.exists("open_orders_data.json"):
            with open("open_orders_data.json", "r", encoding="utf-8") as f:
                raw_orders = json.load(f)
                valid_orders = []
                for o in raw_orders:
                    open_q = clean_numeric(o.get("openQty", 0))
                    if open_q > 0:
                        p_norm = normalize_part_no(o.get("partNo") or o.get("itemCode"))
                        fg_s = clean_numeric(o.get("fgStock", 0))
                        wip_s = clean_numeric(o.get("wipStock", 0))
                        if fg_s > 0 and p_norm not in fg_stock_map:
                            fg_stock_map[p_norm] = fg_s
                        if wip_s > 0 and p_norm not in wip_stock_map:
                            wip_stock_map[p_norm] = wip_s
                        valid_orders.append({
                            "partNo": p_norm,
                            "desc": o.get("desc") or o.get("partNo"),
                            "customer": o.get("customer", "Direct Client"),
                            "openQty": open_q
                        })
                orders_df = pd.DataFrame(valid_orders)
                
        # Load BOM
        if os.path.exists("bom_data.json"):
            with open("bom_data.json", "r", encoding="utf-8") as f:
                boms = json.load(f)
                cleaned_boms = []
                for b in boms:
                    cleaned_boms.append({
                        "fgPart": normalize_part_no(b.get("fgPart")),
                        "rmPart": normalize_rm_code(b.get("rmPart")),
                        "rmDesc": b.get("rmDesc", ""),
                        "category": b.get("category", "General"),
                        "ratio": clean_numeric(b.get("ratio", 1.0)),
                        "unit": b.get("unit", "Nos")
                    })
                bom_df = pd.DataFrame(cleaned_boms)
                
        # Load RM Stocks
        if os.path.exists("rm_data.json"):
            with open("rm_data.json", "r", encoding="utf-8") as f:
                rms = json.load(f)
                for r in rms:
                    rm_code = normalize_rm_code(r.get("rmPart"))
                    stk = clean_numeric(r.get("stock", 0.0))
                    rm_stock_map[rm_code] = stk
                    # Check domestic parts aliasing
                    if "domesticParts" in r and r["domesticParts"]:
                        for d_part in str(r["domesticParts"]).split(','):
                            d_norm = normalize_rm_code(d_part)
                            if d_norm and d_norm not in rm_stock_map:
                                rm_stock_map[d_norm] = clean_numeric(r.get("domesticStock", stk))

    return orders_df, fg_stock_map, wip_stock_map, bom_df, rm_stock_map, data_source_mode


# -----------------------------------------------------------------------------
# 4. CORE MRP CALCULATION & NETTING PIPELINE
# -----------------------------------------------------------------------------
def run_mrp_engine(
    orders_df: pd.DataFrame,
    fg_stock_map: Dict[str, float],
    wip_stock_map: Dict[str, float],
    bom_df: pd.DataFrame,
    rm_stock_map: Dict[str, float]
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Executes the 3-step production netting and BOM raw material explosion.
    """
    if orders_df is None or orders_df.empty:
        return pd.DataFrame(), pd.DataFrame(), {}

    # STEP 1: ORDER NETTING
    netted_orders = []
    total_open_units = 0.0
    total_covered_units = 0.0
    total_net_units = 0.0
    ready_orders_count = 0
    shortage_orders_count = 0

    for _, row in orders_df.iterrows():
        p_no = row["partNo"]
        open_q = row["openQty"]
        total_open_units += open_q
        
        fg_s = fg_stock_map.get(p_no, 0.0)
        wip_s = wip_stock_map.get(p_no, 0.0)
        total_avail_fg = fg_s + wip_s
        
        net_fg_needed = max(0.0, open_q - total_avail_fg)
        covered_q = open_q - net_fg_needed
        total_covered_units += covered_q
        total_net_units += net_fg_needed
        
        if net_fg_needed == 0:
            status = "COMPLETED"
            status_badge = "🟢 READY / COMPLETED"
            ready_orders_count += 1
        elif total_avail_fg > 0:
            status = "PARTIAL"
            status_badge = "🟡 PARTIAL STOCK"
            shortage_orders_count += 1
        else:
            status = "SHORTAGE"
            status_badge = "🔴 ZERO FG STOCK"
            shortage_orders_count += 1
            
        netted_orders.append({
            "FG Part Code": p_no,
            "Customer": row.get("customer", "-"),
            "Description": row.get("desc", p_no),
            "Open Qty": open_q,
            "Daily FG Stock": fg_s,
            "Daily WIP Stock": wip_s,
            "Total Available FG": total_avail_fg,
            "Net Needed to Build": net_fg_needed,
            "Status": status,
            "Status Display": status_badge
        })

    netted_orders_df = pd.DataFrame(netted_orders)

    # STEP 2 & 3: BOM EXPLOSION ON NET DEFICIT ONLY
    demand_accumulator: Dict[str, Dict[str, Any]] = {}
    
    # Pre-index BOM by FG Part
    bom_by_fg = {}
    if bom_df is not None and not bom_df.empty:
        for _, b in bom_df.iterrows():
            fg_key = b["fgPart"]
            if fg_key not in bom_by_fg:
                bom_by_fg[fg_key] = []
            bom_by_fg[fg_key].append(b)

    for o in netted_orders:
        net_needed = o["Net Needed to Build"]
        fg_code = o["FG Part Code"]
        
        if net_needed <= 0:
            continue
            
        components = bom_by_fg.get(fg_code, [])
        for comp in components:
            rm_code = comp["rmPart"]
            ratio = comp["ratio"]
            unit = comp.get("unit", "Nos")
            desc = comp.get("rmDesc", "")
            cat = comp.get("category", "General")
            
            gross_req = net_needed * ratio
            
            if rm_code not in demand_accumulator:
                avail_stk = rm_stock_map.get(rm_code, 0.0)
                demand_accumulator[rm_code] = {
                    "RM Part Code": rm_code,
                    "Description": desc,
                    "Category": cat,
                    "Unit": unit,
                    "Total Factory RM Demand": 0.0,
                    "Current Warehouse RM Stock": avail_stk,
                    "Impacted Orders Count": 0,
                    "Impacted Orders": []
                }
            demand_accumulator[rm_code]["Total Factory RM Demand"] += gross_req
            demand_accumulator[rm_code]["ImpactedOrdersCount"] = demand_accumulator[rm_code].get("ImpactedOrdersCount", 0) + 1
            demand_accumulator[rm_code]["Impacted Orders"].append(f"{fg_code} ({net_needed:,.0f} units)")

    # Build Requisition Plan
    rm_shortages = []
    critical_shortages_count = 0
    total_shortage_cost_items = 0

    for rm_code, item in demand_accumulator.items():
        tot_demand = item["Total Factory RM Demand"]
        curr_stock = item["Current Warehouse RM Stock"]
        net_shortage = max(0.0, tot_demand - curr_stock)
        
        if tot_demand > 0:
            cov_pct = min(100.0, (curr_stock / tot_demand) * 100.0)
        else:
            cov_pct = 100.0
            
        if net_shortage > 0:
            critical_shortages_count += 1
            action = "🚨 CREATE PO NOW"
        else:
            action = "✅ STOCK ADEQUATE"

        rm_shortages.append({
            "RM Part Code": rm_code,
            "Description": item["Description"],
            "Category": item["Category"],
            "Unit": item["Unit"],
            "Total Demand": tot_demand,
            "Warehouse Stock": curr_stock,
            "Net Shortage": net_shortage,
            "Coverage %": cov_pct,
            "Action Requisition": action,
            "Orders Impacted": len(set(item["Impacted Orders"]))
        })

    rm_shortages_df = pd.DataFrame(rm_shortages)
    if not rm_shortages_df.empty:
        rm_shortages_df = rm_shortages_df.sort_values(by=["Net Shortage", "Coverage %"], ascending=[False, True])

    kpis = {
        "total_orders": len(netted_orders_df),
        "total_open_units": total_open_units,
        "total_covered_units": total_covered_units,
        "total_net_units": total_net_units,
        "ready_orders_count": ready_orders_count,
        "shortage_orders_count": shortage_orders_count,
        "critical_rm_count": critical_shortages_count,
        "total_rm_evaluated": len(rm_shortages_df)
    }

    return netted_orders_df, rm_shortages_df, kpis


# -----------------------------------------------------------------------------
# 5. STREAMLIT APPLICATION MAIN VIEW
# -----------------------------------------------------------------------------
def main():
    # 5.1 Top Banner & Header Strip
    st.markdown("""
    <div class="mrp-header-container">
        <div>
            <div class="mrp-title">
                🏭 Factory LAN Real-Time MRP &amp; RM Shortage Engine
            </div>
            <div class="mrp-subtitle">
                Automated Production Netting, Live BOM Explosion &amp; Warehouse Procurement Requisition
            </div>
        </div>
        <div style="display: flex; align-items: center; gap: 14px;">
            <div class="status-badge">
                <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #10b981;"></span>
                LAN Active: Port 8501
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 5.2 Control Row: Reload & Cache Reset
    col_ctrl_left, col_ctrl_right = st.columns([8, 2])
    with col_ctrl_right:
        if st.button("🔄 Reload Data", use_container_width=True, type="primary"):
            st.cache_data.clear()
            st.rerun()

    # Load Data
    orders_df, fg_stock_map, wip_stock_map, bom_df, rm_stock_map, source_mode = load_all_mrp_data()
    netted_orders_df, rm_shortages_df, kpis = run_mrp_engine(
        orders_df, fg_stock_map, wip_stock_map, bom_df, rm_stock_map
    )

    with col_ctrl_left:
        st.caption(f"📡 **Data Pipeline Source:** `{source_mode}` | **Last Refreshed:** `{datetime.now().strftime('%d %b %Y, %I:%M:%S %p')}`")

    # 5.3 KPI Summary Metric Cards (Top Row)
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">Open Orders Demand</div>
            <div class="kpi-value" style="color: #6366f1;">{kpis.get('total_open_units', 0):,.0f}</div>
            <div class="kpi-subtext">{kpis.get('total_orders', 0)} Active Customer Orders</div>
        </div>
        """, unsafe_allow_html=True)
    with k2:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">Covered by FG / WIP</div>
            <div class="kpi-value" style="color: #10b981;">{kpis.get('total_covered_units', 0):,.0f}</div>
            <div class="kpi-subtext">{kpis.get('ready_orders_count', 0)} Orders 100% Satisfied</div>
        </div>
        """, unsafe_allow_html=True)
    with k3:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">Net Production Target</div>
            <div class="kpi-value" style="color: #f59e0b;">{kpis.get('total_net_units', 0):,.0f}</div>
            <div class="kpi-subtext">Deficit Triggering BOM Demand</div>
        </div>
        """, unsafe_allow_html=True)
    with k4:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">Critical RM Shortages</div>
            <div class="kpi-value" style="color: #ef4444;">{kpis.get('critical_rm_count', 0)}</div>
            <div class="kpi-subtext">Materials Requiring Purchase Orders</div>
        </div>
        """, unsafe_allow_html=True)

    st.write("") # vertical spacing

    # 5.4 Main Navigation Tabs
    tab_procure, tab_prod, tab_setup = st.tabs([
        "📦 Tab 1: Factory RM Shortage & Requisition (Primary Procurement)",
        "📋 Tab 2: Order Netting & Feasibility (Production Planning)",
        "⚙️ Tab 3: Google Sheets & LAN Configuration"
    ])

    # -------------------------------------------------------------------------
    # TAB 1: FACTORY RM SHORTAGE & PROCUREMENT REQUISITIONS
    # -------------------------------------------------------------------------
    with tab_procure:
        st.subheader("Factory Raw Material Procurement Shortage Register")
        st.caption("Aggregated raw material requirements exploded strictly on Net Production Deficits (Open Qty - FG Stock - WIP Stock).")

        filter_c1, filter_c2, filter_c3 = st.columns([5, 3, 2])
        with filter_c1:
            search_query = st.text_input("🔍 Instant Material Search (Part Code, Wire Gauge, Bobbin, Core, Tape):", "")
        with filter_c2:
            show_shortages_only = st.checkbox("🚨 Show Shortages Only (Critical)", value=True)
        with filter_c3:
            # Requisition CSV Download
            if not rm_shortages_df.empty:
                csv_data = rm_shortages_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download PO Requisition (CSV)",
                    data=csv_data,
                    file_name=f"Factory_RM_Shortage_Requisition_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )

        # Apply Filtering
        filtered_rm = rm_shortages_df.copy()
        if show_shortages_only:
            filtered_rm = filtered_rm[filtered_rm["Net Shortage"] > 0]
        if search_query.strip():
            q = search_query.strip().lower()
            filtered_rm = filtered_rm[
                filtered_rm["RM Part Code"].str.lower().str.contains(q, na=False) |
                filtered_rm["Description"].str.lower().str.contains(q, na=False) |
                filtered_rm["Category"].str.lower().str.contains(q, na=False)
            ]

        # Display Dataframe with high-visibility formatting
        if not filtered_rm.empty:
            # Prepare formatted columns for display
            disp_rm = filtered_rm.copy()
            disp_rm["Total Demand"] = disp_rm["Total Demand"].map("{:,.2f}".format)
            disp_rm["Warehouse Stock"] = disp_rm["Warehouse Stock"].map("{:,.2f}".format)
            disp_rm["Net Shortage"] = disp_rm["Net Shortage"].map("{:,.2f}".format)
            disp_rm["Coverage %"] = disp_rm["Coverage %"].map("{:,.1f}%".format)

            st.dataframe(
                disp_rm[[
                    "RM Part Code", "Description", "Category", "Unit", 
                    "Total Demand", "Warehouse Stock", "Net Shortage", 
                    "Coverage %", "Action Requisition", "Orders Impacted"
                ]],
                use_container_width=True,
                height=520,
                hide_index=True
            )
            st.info(f"Showing **{len(filtered_rm)}** material requisition line items.")
        else:
            st.success("🎉 No material shortages found matching your filter criteria!")

    # -------------------------------------------------------------------------
    # TAB 2: ORDER NETTING & FEASIBILITY (PRODUCTION VIEW)
    # -------------------------------------------------------------------------
    with tab_prod:
        st.subheader("Customer Open Orders Production Netting Register")
        st.caption("Net production target is calculated per order: **Net Needed = max(0, Open Qty - (FG Stock + WIP Stock))**")

        op_c1, op_c2 = st.columns([6, 4])
        with op_c1:
            order_search = st.text_input("🔍 Filter Orders by FG Code or Customer:", "")
        with op_c2:
            status_filter = st.selectbox(
                "Filter by Feasibility Status:",
                ["All Orders", "Shortage / Incomplete", "Ready / Completed (100% Stock)"]
            )

        filtered_orders = netted_orders_df.copy()
        if status_filter == "Shortage / Incomplete":
            filtered_orders = filtered_orders[filtered_orders["Net Needed to Build"] > 0]
        elif status_filter == "Ready / Completed (100% Stock)":
            filtered_orders = filtered_orders[filtered_orders["Net Needed to Build"] == 0]

        if order_search.strip():
            oq = order_search.strip().lower()
            filtered_orders = filtered_orders[
                filtered_orders["FG Part Code"].str.lower().str.contains(oq, na=False) |
                filtered_orders["Customer"].str.lower().str.contains(oq, na=False) |
                filtered_orders["Description"].str.lower().str.contains(oq, na=False)
            ]

        if not filtered_orders.empty:
            disp_orders = filtered_orders.copy()
            disp_orders["Open Qty"] = disp_orders["Open Qty"].map("{:,.0f}".format)
            disp_orders["Daily FG Stock"] = disp_orders["Daily FG Stock"].map("{:,.0f}".format)
            disp_orders["Daily WIP Stock"] = disp_orders["Daily WIP Stock"].map("{:,.0f}".format)
            disp_orders["Total Available FG"] = disp_orders["Total Available FG"].map("{:,.0f}".format)
            disp_orders["Net Needed to Build"] = disp_orders["Net Needed to Build"].map("{:,.0f}".format)

            st.dataframe(
                disp_orders[[
                    "FG Part Code", "Customer", "Description", 
                    "Open Qty", "Daily FG Stock", "Daily WIP Stock", 
                    "Total Available FG", "Net Needed to Build", "Status Display"
                ]],
                use_container_width=True,
                height=520,
                hide_index=True
            )
            st.info(f"Showing **{len(filtered_orders)}** finished goods orders.")
        else:
            st.warning("No orders found matching the criteria.")

    # -------------------------------------------------------------------------
    # TAB 3: LAN & GOOGLE CLOUD CONFIGURATION
    # -------------------------------------------------------------------------
    with tab_setup:
        st.subheader("🏭 Factory LAN Server & Google Cloud Configuration")
        
        cfg_col1, cfg_col2 = st.columns(2)
        with cfg_col1:
            st.markdown("""
            ### 🌐 How to Access Across Factory LAN / Wi-Fi
            To allow supervisors, store managers, and assembly operators on the factory floor to open this dashboard:
            
            1. Find this host machine's local IP address by running `ipconfig` in PowerShell (e.g. `192.168.1.24`).
            2. Run Streamlit bound to all network interfaces:
            ```powershell
            streamlit run app.py --server.port 8501 --server.address 0.0.0.0
            ```
            3. Any mobile, tablet, or PC connected to factory Wi-Fi/LAN can now access:
            ```text
            http://<HOST_IP>:8501
            e.g.: http://192.168.1.24:8501
            ```
            """)
            
        with cfg_col2:
            st.markdown("""
            ### 🔑 Google Service Account Setup (For Direct Live Fetch)
            To pull live changes from Google Sheets directly without Apps Script:
            
            1. Create a Google Service Account in Google Cloud Console.
            2. Download the JSON key file and rename it to `service_account.json`.
            3. Place `service_account.json` into this folder:
            ```text
            C:\\Users\\lenovo\\Desktop\\AppSheet_Manufacturing_App\\service_account.json
            ```
            4. Share the 5 Google Sheets with your Service Account email (Viewer access):
               - `OPEN ORDER FG (14-10-2026)`
               - `DAILY FG STOCK (14-10-2026)`
               - `DAILY WIP STOCK (14-10-2026)`
               - `MASTER BOM-19.03.2026`
               - `Stocks (Raw Material Warehouse)`
            5. Click **🔄 Reload Data** in the top right to start streaming live.
            """)

if __name__ == "__main__":
    main()
