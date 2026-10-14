# InvenMRP — Real-Time Manufacturing MRP, Open Order & BOM Shortage Controller

A standalone, responsive manufacturing dashboard modeled after GitHub open-source MRP platforms (InvenTree and ERPNext) that connects to Google Sheets, explodes the Bill of Materials (BOM), matches live warehouse stock, and calculates raw material shortages in real time.

---

## 🚀 Quick Start

### 1. Run on This PC
Double-click `LAUNCH_MRP_DASHBOARD.bat` or run:
```bash
python -m http.server 8080 --bind 0.0.0.0
```
Then open: [http://localhost:8080](http://localhost:8080)

### 2. Open from Another PC, Laptop, Tablet, or Mobile Phone
When connected to the same Wi-Fi or office network, open your browser and go to:
```
http://<HOST_IP_ADDRESS>:8080
```
*(Example: `http://192.168.1.24:8080`)*

---

## 🌐 Free Cloud Hosting with GitHub Pages
1. Push this repository to your GitHub account.
2. In your GitHub repository, go to **Settings** → **Pages**.
3. Under **Branch**, select `main` (root) and click **Save**.
4. Your application will be live at:
```
https://<your-username>.github.io/<repository-name>/
```
Any system worldwide can access it directly without running a local server!

---

## 📊 Live Google Sheets Data Sources
- **Customer Demand (Open Orders Col AE)**: `GID 0`
- **Master BOM (19.03.2026)**: `GID 199313343`
- **Daily Warehouse Stocks (Domestic & Imported)**: `GID 82202164`

---

## 🛠️ Features
- **High-Density Compact View**: Compact/Comfortable density toggle.
- **Top KPI Metrics Strip**: Active demand, unique RM parts, stocked items, and critical shortage alerts.
- **Tab 1 — Master Procurement Shortage Summary**: Filter by Category (Bobbin, Core, Wire, Tape, Sleeve), instant search, stock coverage progress bars, and one-click CSV export.
- **Tab 2 — Compact Orders Feasibility Register**: 62-order backlog summary with status badges (`🟢 Ready to Produce` vs `🔴 Blocked`) and instant component BOM modals.
- **Horizontal Smooth Scroll**: Dedicated left/right scroll controller buttons and sticky frozen part columns.
