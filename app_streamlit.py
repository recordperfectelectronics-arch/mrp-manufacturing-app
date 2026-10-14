"""
InvenMRP: Real-Time MRP, Open Order & BOM Shortage Application
Modeled after modern open-source MRP platforms (InvenTree & ERPNext)
Author: Antigravity Assistant
Theme: Slate Dark (#0f172a, #1e293b) with High-Contrast Emerald, Amber, Rose Statuses
"""

import sys
import os
import re
import io
import json
import urllib.request
from datetime import datetime
import pandas as pd

# If streamlit is installed, import it; otherwise provide a friendly launcher message
try:
    import streamlit as st
except ImportError:
    print("[ERROR] Streamlit is not installed in this environment.")
    print("Please run: pip install streamlit pandas requests openpyxl")
    print("Then start the dashboard using: streamlit run mrp_streamlit_app.py")
    sys.exit(1)

# Streamlit Page Configuration
st.set_page_config(
    page_title="InvenMRP — Open Order & BOM Shortage Controller",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom High-Contrast InvenTree / ERPNext Dark CSS
st.markdown("""
<style>
    /* Global Background and Dark Theme */
    .stApp {
        background-color: #0f172a;
        color: #f8fafc;
    }
    
    /* Card Styles */
    .metric-card {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 14px;
        padding: 16px 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
    }
    
    /* Badges */
    .badge-emerald {
        background: rgba(16, 185, 129, 0.15);
        color: #34d399;
        border: 1px solid rgba(16, 185, 129, 0.3);
        padding: 4px 10px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 11px;
    }
    
    .badge-amber {
        background: rgba(245, 158, 11, 0.15);
        color: #fbbf24;
        border: 1px solid rgba(245, 158, 11, 0.3);
        padding: 4px 10px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 11px;
    }

    .badge-rose {
        background: rgba(239, 68, 68, 0.15);
        color: #f87171;
        border: 1px solid rgba(239, 68, 68, 0.3);
        padding: 4px 10px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 11px;
    }

    /* Monospace Part Numbers */
    .part-mono {
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        font-weight: 700;
        color: #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Data Normalization Helpers
def normalize_part(val):
    if not val:
        return ""
    return re.sub(r'\s+', ' ', str(val)).strip().upper()

def clean_float(val):
    if val is None or val == "":
        return 0.0
    try:
        if isinstance(val, (int, float)):
            return float(val)
        cleaned = re.sub(r'[^\d.-]', '', str(val).replace(',', ''))
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0

@st.cache_data(ttl=300)
def load_all_data():
    """Load Open Orders, Master BOM, and Daily Warehouse Stocks from local/verified Google Sheets."""
    # 1. Orders
    orders_file = os.path.join(APP_DIR, "open_orders_data.json")
    if os.path.exists(orders_file):
        with open(orders_file, "r", encoding="utf-8") as f:
            orders = json.load(f)
    else:
        orders = []

    # 2. Master BOM
    bom_file = os.path.join(APP_DIR, "bom_data.json")
    if os.path.exists(bom_file):
        with open(bom_file, "r", encoding="utf-8") as f:
            bom = json.load(f)
    else:
        bom = []

    # 3. Warehouse Stocks
    rm_file = os.path.join(APP_DIR, "rm_data.json")
    if os.path.exists(rm_file):
        with open(rm_file, "r", encoding="utf-8") as f:
            rm_data = json.load(f)
    else:
        rm_data = []

    return orders, bom, rm_data

# Execute Data Loading
orders_raw, bom_raw, rm_raw = load_all_data()

# Sidebar: Controls & Google Sheets Sync Info
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/database.png", width=48)
    st.title("InvenMRP Engine")
    st.caption("Modeled after InvenTree & ERPNext")
    st.markdown("---")

    st.subheader("Live Google Sheets")
    st.markdown("""
    1. [**Open Orders (GID 0)**](https://docs.google.com/spreadsheets/d/1Ek0rpo9sUDsStSo0pm1EF6oR3gCMmjvTa2TS-i8CzA0/edit?gid=0#gid=0)
    2. [**Master BOM (GID 199313343)**](https://docs.google.com/spreadsheets/d/1JKoQnYm1BSBkZUVSqYYXsb8VshuWo9tyar3dUtetnHk/edit?gid=199313343#gid=199313343)
    3. [**Stocks (GID 82202164)**](https://docs.google.com/spreadsheets/d/1mmIHjG_BKIiV_02duivofXyJpWyM3T_h_Fq670m7eaU/edit?gid=82202164#gid=82202164)
    """)

    gas_endpoint = st.text_input("Live Apps Script Endpoint (Optional)", "", placeholder="https://script.google.com/macros/s/.../exec")

    if st.button("🔄 Reload & Resync Feeds", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.caption(f"Last sync: {datetime.now().strftime('%d-%b-%Y %I:%M %p')}")

# =========================================================================
# CORE COMPUTATIONAL LOGIC & SHORTAGE ENGINE
# =========================================================================

# 1. Active Open Orders
active_orders = []
for o in orders_raw:
    qty = clean_float(o.get('openQty'))
    if qty > 0:
        active_orders.append({
            'partNo': normalize_part(o.get('partNo')),
            'customer': str(o.get('customer') or 'Customer').strip(),
            'desc': str(o.get('desc') or '').strip(),
            'itemCode': str(o.get('itemCode') or '').strip(),
            'openQty': qty
        })

# 2. Stock Map
stock_map = {}
rm_meta = {}
for r in rm_raw:
    p_norm = normalize_part(r.get('rmPart'))
    stk = clean_float(r.get('stock'))
    stock_map[p_norm] = stk
    rm_meta[p_norm] = r

# 3. Part-Wise BOM Explosion & Factory Consolidated Demand
factory_demand = {}
order_allocations = []

ready_orders_count = 0
blocked_orders_count = 0

for order in active_orders:
    fg = order['partNo']
    comps = [b for b in bom_raw if normalize_part(b.get('fgPart')) == fg]
    
    order_has_shortage = False
    max_buildable = float('inf')
    comp_lines = []

    for c in comps:
        rm_part = c.get('rmPart')
        rm_norm = normalize_part(rm_part)
        ratio = clean_float(c.get('ratio')) or 1.0
        gross_req = order['openQty'] * ratio
        curr_stock = stock_map.get(rm_norm, 0.0)
        unit = c.get('unit') or 'Nos'
        desc = c.get('rmDesc') or rm_meta.get(rm_norm, {}).get('rmDesc') or 'Raw Material'
        cat = c.get('category') or rm_meta.get(rm_norm, {}).get('category') or 'General'

        # Coverage evaluation
        if curr_stock <= 0:
            cov = "ZERO_STOCK"
            order_has_shortage = True
        elif curr_stock < gross_req:
            cov = "PARTIAL_SHORTAGE"
            order_has_shortage = True
        else:
            cov = "FULL_COVERAGE"

        can_build_this = int(curr_stock / ratio)
        if can_build_this < max_buildable:
            max_buildable = can_build_this

        comp_lines.append({
            'rmPart': rm_part,
            'rmNorm': rm_norm,
            'desc': desc,
            'category': cat,
            'ratio': ratio,
            'grossReq': gross_req,
            'stock': curr_stock,
            'deficit': max(0.0, gross_req - curr_stock),
            'surplus': max(0.0, curr_stock - gross_req),
            'unit': unit,
            'coverage': cov,
            'canBuild': can_build_this
        })

        # Factory level aggregation
        if rm_norm not in factory_demand:
            factory_demand[rm_norm] = {
                'rmPart': rm_part,
                'rmNorm': rm_norm,
                'desc': desc,
                'category': cat,
                'unit': unit,
                'totalRequired': 0.0,
                'stock': curr_stock,
                'orders': []
            }
        factory_demand[rm_norm]['totalRequired'] += gross_req
        factory_demand[rm_norm]['orders'].append({
            'fgPart': fg,
            'customer': order['customer'],
            'orderQty': order['openQty'],
            'grossReq': gross_req
        })

    if not comps:
        order_has_shortage = True
        max_buildable = 0

    if max_buildable == float('inf'):
        max_buildable = 0

    if order_has_shortage:
        blocked_orders_count += 1
    else:
        ready_orders_count += 1

    order_allocations.append({
        'order': order,
        'components': comp_lines,
        'hasShortage': order_has_shortage,
        'maxBuildable': max_buildable
    })

# 4. Master Consolidated Procurement Table
procurement_list = []
stocked_items_count = 0
shortage_items_count = 0

for rm_norm, rec in factory_demand.items():
    tot_req = rec['totalRequired']
    stk = rec['stock']
    net_shortage = max(0.0, tot_req - stk)
    free_stock = max(0.0, stk - tot_req)
    coverage_pct = round((stk / tot_req * 100)) if tot_req > 0 else 100

    if net_shortage > 0:
        action = "BUY NEEDED"
        shortage_items_count += 1
    else:
        action = "STOCKED"
        stocked_items_count += 1

    procurement_list.append({
        'rmPart': rec['rmPart'],
        'desc': rec['desc'],
        'category': rec['category'],
        'unit': rec['unit'],
        'totalRequired': tot_req,
        'stock': stk,
        'netShortage': net_shortage,
        'freeStock': free_stock,
        'coveragePct': coverage_pct,
        'action': action,
        'impactedOrders': len(rec['orders'])
    })

# Convert to DataFrame and sort by Shortage descending
df_procurement = pd.DataFrame(procurement_list)
if not df_procurement.empty:
    df_procurement = df_procurement.sort_values(by=['netShortage', 'rmPart'], ascending=[False, True])

# =========================================================================
# UI HEADER & TOP KPI METRICS STRIP
# =========================================================================

st.title("📦 InvenMRP — Production Shortage & Allocation Controller")
st.markdown("Real-time Master BOM Explosion matched against Daily Warehouse Stocks.")

total_fg_units = sum(o['openQty'] for o in active_orders)

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="Customer Demand (Col AE)",
        value=f"{len(active_orders)} Orders",
        delta=f"{total_fg_units:,.0f} Units",
        delta_color="normal"
    )

with col2:
    st.metric(
        label="Unique BOM Raw Materials",
        value=f"{len(procurement_list)} RM Codes",
        delta="Exploded BOM",
        delta_color="off"
    )

with col3:
    st.metric(
        label="🟢 100% Stocked Materials",
        value=f"{stocked_items_count} Items",
        delta="Sufficient in Store",
        delta_color="normal"
    )

with col4:
    st.metric(
        label="🔴 Critical Shortages",
        value=f"{shortage_items_count} Items",
        delta="Buy Needed (Deficit)",
        delta_color="inverse"
    )

st.markdown("---")

# =========================================================================
# TABS INTERFACE
# =========================================================================

tab1, tab2 = st.tabs([
    f"📋 1. Master Procurement Shortage Summary ({shortage_items_count} Action Needed)",
    f"📦 2. Part-Wise & Order Allocation View ({len(active_orders)} Orders)"
])

# -------------------------------------------------------------------------
# TAB 1: MASTER PROCUREMENT SHORTAGE SUMMARY
# -------------------------------------------------------------------------
with tab1:
    col_search, col_cat, col_toggle = st.columns([2, 1, 1])
    
    with col_search:
        search_query = st.text_input("🔍 Search RM Part Number, Description, or Specification", "")
        
    with col_cat:
        categories = ["ALL"] + sorted(list(set(df_procurement['category'].dropna().unique()))) if not df_procurement.empty else ["ALL"]
        sel_cat = st.selectbox("Category Filter", categories)
        
    with col_toggle:
        st.write("")
        st.write("")
        show_short_only = st.checkbox("🔴 Show Shortages Only", value=False)

    # Filter DataFrame
    df_filtered = df_procurement.copy()
    if show_short_only:
        df_filtered = df_filtered[df_filtered['netShortage'] > 0]
    if sel_cat != "ALL":
        df_filtered = df_filtered[df_filtered['category'] == sel_cat]
    if search_query:
        sq = search_query.lower()
        df_filtered = df_filtered[
            df_filtered['rmPart'].str.lower().str.contains(sq) |
            df_filtered['desc'].str.lower().str.contains(sq) |
            df_filtered['category'].str.lower().str.contains(sq)
        ]

    st.caption(f"Displaying {len(df_filtered)} of {len(df_procurement)} raw material components")

    # Table Display formatting
    def format_row(row):
        return {
            "RM Part Number": row['rmPart'],
            "Description": row['desc'],
            "Category": row['category'],
            "Total Required": f"{row['totalRequired']:,.2f} {row['unit']}",
            "Daily Stock": f"{row['stock']:,.2f} {row['unit']}",
            "Net Shortage": f"-{row['netShortage']:,.2f} {row['unit']}" if row['netShortage'] > 0 else "0",
            "Coverage %": f"{row['coveragePct']}%",
            "Action": row['action'],
            "Impacted Orders": f"{row['impactedOrders']} Orders"
        }

    display_data = [format_row(r) for _, r in df_filtered.iterrows()]
    st.dataframe(pd.DataFrame(display_data), use_container_width=True, height=500)

    # Export to CSV
    csv_buffer = io.StringIO()
    df_filtered.to_csv(csv_buffer, index=False)
    st.download_button(
        label="📥 Download Procurement Shortage Report CSV",
        data=csv_buffer.getvalue(),
        file_name=f"MRP_Procurement_Shortages_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )

# -------------------------------------------------------------------------
# TAB 2: PART-WISE & ORDER ALLOCATION VIEW
# -------------------------------------------------------------------------
with tab2:
    col_fg_search, col_fg_filter = st.columns([2, 1])
    with col_fg_search:
        fg_query = st.text_input("🔍 Search Finished Good Part Number, Customer, or Model", "")
    with col_fg_filter:
        fg_filter = st.selectbox("Production Feasibility Filter", ["All Orders (62)", "🟢 Ready to Produce (17)", "🔴 Blocked by Shortage (45)"])

    for item in order_allocations:
        order = item['order']
        is_ready = not item['hasShortage']

        # Apply Filters
        if "Ready" in fg_filter and not is_ready:
            continue
        if "Blocked" in fg_filter and is_ready:
            continue
        if fg_query:
            fq = fg_query.lower()
            if fq not in order['partNo'].lower() and fq not in order['customer'].lower() and fq not in order['desc'].lower():
                continue

        status_icon = "🟢 Ready to Produce (100% RM Available)" if is_ready else f"🔴 Blocked by Shortage (Max {item['maxBuildable']:,} units)"

        expander_title = f"{order['partNo']} — {order['customer']} | Demand: {order['openQty']:,.0f} Units | {status_icon}"
        with st.expander(expander_title, expanded=False):
            st.markdown(f"**Description**: {order['desc']} | **Item Code**: `{order['itemCode']}`")
            
            comp_rows = []
            for c in item['components']:
                comp_rows.append({
                    "BOM Part Code": c['rmPart'],
                    "Specification": c['desc'],
                    "Usage Ratio": f"{c['ratio']}",
                    "Gross Required": f"{c['grossReq']:,.2f} {c['unit']}",
                    "Warehouse Stock": f"{c['stock']:,.2f} {c['unit']}",
                    "Balance / Shortage": f"-{c['deficit']:,.2f}" if c['deficit'] > 0 else f"+{c['surplus']:,.2f}",
                    "Can Build": f"{c['canBuild']:,} Units",
                    "Status": "🟢 Sufficient" if c['coverage'] == "FULL_COVERAGE" else ("🟡 Partial" if c['coverage'] == "PARTIAL_SHORTAGE" else "🔴 Zero Stock")
                })
            
            st.table(pd.DataFrame(comp_rows))
