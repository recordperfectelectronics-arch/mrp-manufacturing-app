"""
Sync Daily MRP, Master BOM (19.03.2026), Live Stocks & Open Orders (Col AE)
With 200% Domestic (D-Series) and Imported (I-Series) Dual Stock Tracking
Author: Antigravity Assistant
Last Synced: 2026-10-14
"""

import urllib.request
import csv
import json
import re
import math
import sys
import os
from datetime import datetime
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
app_dir = r"C:\Users\lenovo\Desktop\AppSheet_Manufacturing_App"

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Daily MRP & Stocks Live Sync with D-Series & I-Series Dual Tracking...")

# 1. Fetch Open Orders from OPEN ORDER UPDATE FILE 2025 (GID 0)
url_orders = 'https://docs.google.com/spreadsheets/d/1Ek0rpo9sUDsStSo0pm1EF6oR3gCMmjvTa2TS-i8CzA0/export?format=csv&gid=0'
print("1/4 Fetching live Open Orders (Col AE)...")
try:
    lines = urllib.request.urlopen(url_orders, timeout=15).read().decode('utf-8', errors='ignore').splitlines()
    order_reader = list(csv.reader(lines))
except Exception as e:
    print(f"Error reading Open Orders: {e}")
    with open(f"{app_dir}/open_orders_data.json", 'r', encoding='utf-8') as f:
        orders_data = json.load(f)
    order_reader = []

# Load customer mapping from Bom Helper GID 287335215
cust_map = {}
try:
    url_map = 'https://docs.google.com/spreadsheets/d/1D-QWZD6aP1VxT5MmzTBoVFV--8QDR5Z5sezI-KvkGXU/export?format=csv&gid=287335215'
    lines_map = urllib.request.urlopen(url_map, timeout=10).read().decode('utf-8', errors='ignore').splitlines()
    reader_map = list(csv.reader(lines_map))
    for r in reader_map[4:]:
        if len(r) >= 3 and r[0].strip() and r[2].strip() and r[2].strip() != '#N/A':
            cust_map[r[2].strip()] = r[0].strip()
except Exception as e:
    print(f"Note: Error reading customer mapping: {e}")

orders = []
if order_reader:
    for idx, r in enumerate(order_reader[2:], start=3):
        if not any(r): continue
        cust = r[0].strip() if len(r) > 0 else ""
        item_code = r[2].strip() if len(r) > 2 else ""
        desc = r[3].strip() if len(r) > 3 else ""
        tally_part = r[4].strip() if len(r) > 4 else ""
        open_ae_str = r[30].strip() if len(r) > 30 else ""
        
        if not tally_part and not item_code and not cust:
            continue
        if tally_part == 'TOTAL' or cust.startswith('TOTAL'):
            continue
            
        open_ae = 0.0
        if open_ae_str:
            try:
                open_ae = float(open_ae_str.replace(',', '').replace(' ', ''))
            except:
                pass
                
        p_no = tally_part if tally_part else item_code
        # Apply clean customer name if missing or same as part
        resolved_cust = cust
        if (not resolved_cust or resolved_cust == p_no) and p_no in cust_map:
            resolved_cust = cust_map[p_no]

        orders.append({
            'rowIdx': idx,
            'customer': resolved_cust,
            'itemCode': item_code,
            'desc': desc,
            'partNo': p_no,
            'openQty': open_ae,
            'fgStock': 0,
            'wipStock': 0
        })

    with open(f"{app_dir}/open_orders_data.json", 'w', encoding='utf-8') as f:
        json.dump(orders, f, indent=2)
    with open(f"{app_dir}/open_orders_data.js", 'w', encoding='utf-8') as f:
        f.write('window.rawOpenOrdersData = ' + json.dumps(orders) + ';')
    print(f"   -> Loaded {len(orders)} order records (Open parts: {len([o for o in orders if o['openQty'] > 0])})")
else:
    with open(f"{app_dir}/open_orders_data.json", 'r', encoding='utf-8') as f:
        orders = json.load(f)

# 2. Load Master BOM Matrix
print("2/4 Loading Master BOM (19.03.2026)...")
with open(f"{app_dir}/bom_data.json", 'r', encoding='utf-8') as f:
    bom_data = json.load(f)
print(f"   -> Loaded {len(bom_data)} BOM component records across 251 FG parts.")

# 3. Fetch Live Store Stocks from gid=115266892
url_stocks = 'https://docs.google.com/spreadsheets/d/1D-QWZD6aP1VxT5MmzTBoVFV--8QDR5Z5sezI-KvkGXU/export?format=csv&gid=115266892'
print("3/4 Fetching live Store Stocks from Google Sheet...")
lines_st = urllib.request.urlopen(url_stocks, timeout=15).read().decode('utf-8', errors='ignore').splitlines()
st_reader = list(csv.reader(lines_st))

stock_items = []
for r_idx, row in enumerate(st_reader[1:]):
    if not any(row): continue
    desc = row[0].strip() if len(row) > 0 else ''
    qty_raw = row[1].strip() if len(row) > 1 else ''
    rate_raw = row[2].strip() if len(row) > 2 else ''
    val_raw = row[3].strip() if len(row) > 3 else ''
    part_no = row[4].strip() if len(row) > 4 else ''
    
    match = re.match(r'^([\d,]+(?:\.\d+)?)\s*(.*)$', qty_raw)
    qty_num = float(match.group(1).replace(',', '')) if match else 0.0
    unit = match.group(2).strip() if match else ''
    rate_num = 0.0
    try: rate_num = float(rate_raw.replace(',', ''))
    except: pass
    
    # Classify Domestic (D-Series) vs Imported (I-Series)
    tokens = part_no.split()
    series = "OTHER"
    if len(tokens) >= 3:
        vcode = tokens[2].upper()
        if vcode.startswith('D'): series = "DOMESTIC"
        elif vcode.startswith('I'): series = "IMPORTED"
    elif ' D' in part_no: series = "DOMESTIC"
    elif ' I' in part_no: series = "IMPORTED"

    stock_items.append({
        'row': r_idx + 2,
        'desc': desc,
        'qty_num': qty_num,
        'unit': unit,
        'rate': rate_num,
        'part_no': part_no,
        'upper_part': part_no.upper().strip(),
        'series': series
    })
print(f"   -> Loaded {len(stock_items)} live store inventory rows.")

# 4. Calculate Netting, Commonality, and D-Series vs I-Series Stock Tracking
print("4/4 Calculating D-Series & I-Series Dual Stocks & Cumulative Netting...")
open_qty_map = {o['partNo']: o['openQty'] for o in orders}
rm_demand = defaultdict(float)
rm_usage = defaultdict(set)
rm_dict = {}

for b in bom_data:
    fg = b['fgPart']
    rm_p = b['rmPart']
    ratio = b['ratio']
    rm_usage[rm_p].add(fg)
    
    if rm_p not in rm_dict:
        rm_dict[rm_p] = {
            'rmPart': rm_p,
            'rmDesc': b['rmDesc'],
            'category': b['category'],
            'unit': b.get('unit', 'NUMBERS')
        }
    rm_demand[rm_p] += (open_qty_map.get(fg, 0.0) * ratio)

final_rm_data = []
for rm_p, info in rm_dict.items():
    p = rm_p.strip().upper()
    cat = info['category']
    desc = info['rmDesc']
    demand = rm_demand[rm_p]
    tokens = p.split()
    
    # Find all Domestic (D) and Imported (I) candidates in stock sheet
    d_cands = []
    i_cands = []
    
    if len(tokens) >= 2 and tokens[0].isdigit():
        base_prefix = f"{tokens[0]} {tokens[1]}"
        base_cat = tokens[0]
        
        # 1. Exact base prefix match (e.g. "4005 01", "1057 01")
        for st in stock_items:
            sp = st['upper_part']
            if sp.startswith(base_prefix):
                if st['series'] == 'DOMESTIC': d_cands.append(st)
                elif st['series'] == 'IMPORTED': i_cands.append(st)
                
        # 2. For Bobbin/Core, check same base category e.g. "1057", "3001" where D vs I might be 01 vs 02
        if cat in ('Bobbin', 'Core') or not (d_cands and i_cands):
            for st in stock_items:
                sp = st['upper_part']
                if sp.startswith(base_cat) and sp not in [x['upper_part'] for x in d_cands + i_cands]:
                    sdesc = st['desc'].lower()
                    mdesc = desc.lower()
                    if ('ee16' in mdesc and 'ee16' in sdesc) or \
                       ('efd20' in mdesc and 'efd20' in sdesc) or \
                       ('ee13' in mdesc and 'ee13' in sdesc) or \
                       ('uu9.8' in mdesc and 'uu9.8' in sdesc) or \
                       ('ft20' in mdesc and 'ft20' in sdesc) or \
                       ('ei22' in mdesc and 'ei22' in sdesc) or \
                       ('pq' in mdesc and 'pq' in sdesc):
                        if st['series'] == 'DOMESTIC': d_cands.append(st)
                        elif st['series'] == 'IMPORTED': i_cands.append(st)
    elif 'D' in p or 'I' in p:
        for st in stock_items:
            if st['upper_part'] == p:
                if 'D' in p: d_cands.append(st)
                else: i_cands.append(st)

    # De-duplicate candidate rows
    d_unique = {x['upper_part']: x for x in d_cands}
    i_unique = {x['upper_part']: x for x in i_cands}
    
    d_stock = sum(x['qty_num'] for x in d_unique.values())
    i_stock = sum(x['qty_num'] for x in i_unique.values())
    total_avail = d_stock + i_stock
    
    d_parts_str = ", ".join(sorted(list(d_unique.keys()))) if d_unique else "None"
    i_parts_str = ", ".join(sorted(list(i_unique.keys()))) if i_unique else "None"
    
    # Active Stock Source Description
    if d_stock > 0 and i_stock > 0:
        source_type = "BOTH_AVAILABLE"
        source_label = f"🟢 Both in Stock (D: {d_stock:,.1f} + I: {i_stock:,.1f})"
    elif d_stock > 0:
        source_type = "DOMESTIC_AVAILABLE"
        source_label = f"🟢 Domestic (D) in Stock ({d_stock:,.1f})"
    elif i_stock > 0:
        source_type = "IMPORTED_AVAILABLE"
        source_label = f"🟢 Imported (I) in Stock ({i_stock:,.1f})"
    else:
        source_type = "STOCKOUT"
        source_label = "🔴 Zero Stock (D & I Exhausted)"

    # Rates and Units
    all_cands = list(d_unique.values()) + list(i_unique.values())
    units = list(set(x['unit'] for x in all_cands if x['unit']))
    best_unit = units[0] if units else info['unit']
    
    pos_cands = [x for x in all_cands if x['qty_num'] > 0 and x['rate'] > 0]
    if pos_cands:
        avg_rate = sum(x['rate'] * x['qty_num'] for x in pos_cands) / sum(x['qty_num'] for x in pos_cands)
    else:
        rates = [x['rate'] for x in all_cands if x['rate'] > 0]
        avg_rate = rates[0] if rates else 0.0

    u_clean = best_unit.strip().upper()
    if 'KG' in u_clean: std_unit = 'Kgs'
    elif 'MTR' in u_clean or 'METER' in u_clean: std_unit = 'mtrs'
    elif 'ROLL' in u_clean: std_unit = 'Roll'
    elif 'PR' in u_clean or 'PAIR' in u_clean: std_unit = 'Prs'
    elif 'PC' in u_clean: std_unit = 'Pcs'
    elif 'NO' in u_clean: std_unit = 'Nos'
    else: std_unit = 'Nos'

    if cat in ('Bobbin', 'Core'):
        base_safety = max(500, round(demand * 0.15))
        base_moq = 1000 if demand > 2000 else 500
        base_rol = base_safety + max(500, round(demand * 0.25))
    elif cat == 'Wire':
        base_safety = max(2.0, round(demand * 0.15, 2))
        base_moq = 5.0 if demand > 10 else 2.0
        base_rol = round(base_safety + max(2.0, demand * 0.25), 2)
    elif cat == 'Tape':
        base_safety = max(5.0, round(demand * 0.15))
        base_moq = 5.0
        base_rol = base_safety + max(5.0, round(demand * 0.25))
    else:
        base_safety = max(20.0, round(demand * 0.15))
        base_moq = 50.0
        base_rol = base_safety + max(20.0, round(demand * 0.25))

    is_common = len(rm_usage[rm_p]) > 1
    final_rm_data.append({
        'rmPart': rm_p,
        'rmDesc': desc,
        'category': cat,
        'unit': std_unit,
        'stock': round(total_avail, 3),
        'domesticParts': d_parts_str,
        'domesticStock': round(d_stock, 3),
        'importedParts': i_parts_str,
        'importedStock': round(i_stock, 3),
        'stockSourceType': source_type,
        'stockSourceLabel': source_label,
        'rate': round(avg_rate, 2),
        'calcSafety': base_safety,
        'manualOverride': None,
        'rol': base_rol,
        'moq': base_moq,
        'isCommon': is_common,
        'usedInModelsCount': len(rm_usage[rm_p]),
        'usedInModels': sorted(list(rm_usage[rm_p])),
        'stockSource': f"Google Sheet 'Stocks' Live Sync [{datetime.now().strftime('%d-%b-%Y %H:%M')}]"
    })

# Save RM Data
with open(f"{app_dir}/rm_data.json", 'w', encoding='utf-8') as f:
    json.dump(final_rm_data, f, indent=2)
with open(f"{app_dir}/rm_data.js", 'w', encoding='utf-8') as f:
    f.write('window.rawRMData = ' + json.dumps(final_rm_data) + ';')

# Save Sync Status Metadata
sync_status = {
    'lastSyncTimestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'lastSyncDisplay': datetime.now().strftime('%d %b %Y, %I:%M %p'),
    'totalOrders': len(orders),
    'activeOpenOrders': len([o for o in orders if o['openQty'] > 0]),
    'totalOpenUnits': sum(o['openQty'] for o in orders),
    'totalBOMComponents': len(bom_data),
    'totalRawMaterials': len(final_rm_data),
    'commonMaterialsCount': sum(1 for r in final_rm_data if r['isCommon']),
    'individualMaterialsCount': sum(1 for r in final_rm_data if not r['isCommon']),
    'materialsWithStock': sum(1 for r in final_rm_data if r['stock'] > 0),
    'bothDomesticImportedCount': sum(1 for r in final_rm_data if r['stockSourceType'] == 'BOTH_AVAILABLE'),
    'domesticOnlyCount': sum(1 for r in final_rm_data if r['stockSourceType'] == 'DOMESTIC_AVAILABLE'),
    'importedOnlyCount': sum(1 for r in final_rm_data if r['stockSourceType'] == 'IMPORTED_AVAILABLE')
}

with open(f"{app_dir}/sync_status.json", 'w', encoding='utf-8') as f:
    json.dump(sync_status, f, indent=2)
with open(f"{app_dir}/sync_status.js", 'w', encoding='utf-8') as f:
    f.write('window.mrpSyncStatus = ' + json.dumps(sync_status) + ';')

print(f"\nSUCCESS! Daily MRP Sync Completed at {sync_status['lastSyncDisplay']}.")
print(f"  • In-Stock Materials: {sync_status['materialsWithStock']} / {sync_status['totalRawMaterials']}")
print(f"    - Both D & I in Stock: {sync_status['bothDomesticImportedCount']}")
print(f"    - Domestic (D) in Stock: {sync_status['domesticOnlyCount']}")
print(f"    - Imported (I) in Stock: {sync_status['importedOnlyCount']}")
