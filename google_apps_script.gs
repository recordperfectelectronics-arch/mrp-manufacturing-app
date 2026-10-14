/**
 * ============================================================================
 * MISSION: REAL-TIME MRP, OPEN ORDER & BOM SHORTAGE APPLICATION (InvenMRP)
 * Google Apps Script Web App - Production Ready Single-File Architecture
 * ============================================================================
 * 
 * LIVE GOOGLE SPREADSHEETS:
 * 1. Open Orders:  1Ek0rpo9sUDsStSo0pm1EF6oR3gCMmjvTa2TS-i8CzA0 (GID: 0)
 * 2. Master BOM:   1JKoQnYm1BSBkZUVSqYYXsb8VshuWo9tyar3dUtetnHk (GID: 199313343)
 * 3. Daily Stocks: 1mmIHjG_BKIiV_02duivofXyJpWyM3T_h_Fq670m7eaU (GID: 82202164)
 * 
 * DEPLOYMENT INSTRUCTIONS:
 * 1. Open Google Drive -> New -> More -> Google Apps Script (or inside Google Sheets -> Extensions -> Apps Script).
 * 2. Paste this entire code into 'Code.gs'.
 * 3. Create an HTML file named 'index.html' and paste the HTML content from 'mrp_dashboard.html'.
 * 4. Click 'Deploy' -> 'New Deployment'.
 * 5. Select type: 'Web App'.
 * 6. Set Description: "InvenMRP Production Shortage App".
 * 7. Set 'Execute as': 'Me' (your Google Account).
 * 8. Set 'Who has access': 'Anyone' (or 'Anyone within domain').
 * 9. Click 'Deploy' and copy your live Web App URL!
 * 
 * ACCESS AS LIVE JSON API:
 * Add ?action=json to your Web App URL to receive live JSON from all 3 sheets!
 */

// Global Configuration: Exact Spreadsheet IDs and Target GIDs
var SPREADSHEETS = {
  ORDERS: {
    id: "1Ek0rpo9sUDsStSo0pm1EF6oR3gCMmjvTa2TS-i8CzA0",
    gid: 0,
    name: "OPEN ORDER UPDATE FILE 2025"
  },
  BOM: {
    id: "1JKoQnYm1BSBkZUVSqYYXsb8VshuWo9tyar3dUtetnHk",
    gid: 199313343,
    name: "MASTER BOM-19.03.2026"
  },
  STOCKS: {
    id: "1mmIHjG_BKIiV_02duivofXyJpWyM3T_h_Fq670m7eaU",
    gid: 82202164,
    name: "Stocks (Daily Stock Updates)"
  }
};

/**
 * Web App Entry Point (doGet)
 */
function doGet(e) {
  // If called as API endpoint (?action=json or ?format=json)
  if (e && e.parameter && (e.parameter.action === 'json' || e.parameter.format === 'json')) {
    try {
      var mrpResults = runMRPCalculation();
      return ContentService.createTextOutput(JSON.stringify(mrpResults))
        .setMimeType(ContentService.MimeType.JSON);
    } catch (err) {
      return ContentService.createTextOutput(JSON.stringify({
        error: true,
        message: err.toString(),
        stack: err.stack
      })).setMimeType(ContentService.MimeType.JSON);
    }
  }

  // Render Full HTML5 Dashboard
  var template = HtmlService.createTemplateFromFile('index');
  try {
    template.serverPreload = JSON.stringify(runMRPCalculation());
  } catch (err) {
    template.serverPreload = JSON.stringify({ error: true, message: err.toString() });
  }

  return template.evaluate()
    .setTitle('InvenMRP — Production Shortage & Allocation Controller')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/**
 * Helper: Find Sheet Tab by GID (Sheet ID)
 */
function getSheetByGid(spreadsheet, targetGid) {
  var sheets = spreadsheet.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    if (sheets[i].getSheetId() == targetGid) {
      return sheets[i];
    }
  }
  return sheets[0]; // fallback to first tab
}

/**
 * Data Normalization Rules:
 * - Raw material codes: trim whitespace, collapse multiple spaces to single space, uppercase.
 * - Numbers: strip units (Kgs, Pcs, Nos, mtrs.), commas, and parse as float.
 */
function normalizePartNo(str) {
  if (str === null || str === undefined) return '';
  return String(str).trim().replace(/\s+/g, ' ').toUpperCase();
}

function cleanNumber(val) {
  if (val === null || val === undefined || val === '') return 0.0;
  if (typeof val === 'number') return isNaN(val) ? 0.0 : val;
  var cleaned = String(val).replace(/,/g, '').replace(/[^\d.-]/g, '');
  var num = parseFloat(cleaned);
  return isNaN(num) ? 0.0 : num;
}

/**
 * CORE COMPUTATIONAL & SHORTAGE ENGINE
 */
function runMRPCalculation() {
  var timestamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd MMM yyyy, hh:mm a");

  // 1. FETCH SHEET 1: Open Orders (CURRENT OPEN QTY > 0)
  var orderSS = SpreadsheetApp.openById(SPREADSHEETS.ORDERS.id);
  var orderSheet = getSheetByGid(orderSS, SPREADSHEETS.ORDERS.gid);
  var orderData = orderSheet.getDataRange().getValues();

  // Find column indices dynamically
  var colMapOrders = {
    customer: 1,
    itemCode: 2,
    desc: 3,
    tallyPart: 4,
    openQty: 30
  };

  // Check header row (row 1 or 2)
  for (var r = 0; r < Math.min(3, orderData.length); r++) {
    for (var c = 0; c < orderData[r].length; c++) {
      var header = String(orderData[r][c]).trim().toUpperCase();
      if (header.indexOf("CURRENT OPEN QTY") !== -1 || header === "OPEN QTY" || header === "PENDING QTY") colMapOrders.openQty = c;
      if (header.indexOf("CUSTOMER") !== -1) colMapOrders.customer = c;
      if (header === "ITEM" || header.indexOf("ITEM CODE") !== -1) colMapOrders.itemCode = c;
      if (header === "DESCRIPTION") colMapOrders.desc = c;
      if (header.indexOf("TALLY PART") !== -1 || header === "PART NO." || header === "PART #") colMapOrders.tallyPart = c;
    }
  }

  var activeOrders = [];
  var totalOpenFGQty = 0;

  for (var i = 2; i < orderData.length; i++) {
    var oRow = orderData[i];
    var tallyP = String(oRow[colMapOrders.tallyPart] || oRow[0] || '').trim();
    var cust = String(oRow[colMapOrders.customer] || '').trim();
    var desc = String(oRow[colMapOrders.desc] || '').trim();
    var itemCode = String(oRow[colMapOrders.itemCode] || '').trim();
    var openQty = cleanNumber(oRow[colMapOrders.openQty]);

    if (!tallyP && !itemCode) continue;
    if (tallyP === 'TOTAL' || cust.toUpperCase().indexOf('TOTAL') === 0) continue;

    if (openQty > 0) {
      var fgPartNo = normalizePartNo(tallyP || itemCode);
      totalOpenFGQty += openQty;
      activeOrders.push({
        partNo: fgPartNo,
        customer: cust,
        itemCode: itemCode,
        desc: desc,
        openQty: openQty
      });
    }
  }

  // 2. FETCH SHEET 2: Master BOM
  var bomSS = SpreadsheetApp.openById(SPREADSHEETS.BOM.id);
  var bomSheet = getSheetByGid(bomSS, SPREADSHEETS.BOM.gid);
  var bomData = bomSheet.getDataRange().getValues();

  var colMapBOM = {
    fgPart: 0,
    rmPart: 1,
    desc: 2,
    ratio: 3,
    unit: 4,
    category: 5
  };

  for (var b = 0; b < Math.min(3, bomData.length); b++) {
    for (var bc = 0; bc < bomData[b].length; bc++) {
      var bHeader = String(bomData[b][bc]).trim().toUpperCase();
      if (bHeader.indexOf("PART #") !== -1 || bHeader.indexOf("CUSTOMER PART") !== -1 || bHeader.indexOf("FG PART") !== -1) colMapBOM.fgPart = bc;
      if (bHeader.indexOf("RAW MATERIAL") !== -1 || bHeader.indexOf("RM PART") !== -1) colMapBOM.rmPart = bc;
      if (bHeader.indexOf("DESCRIPTION") !== -1 || bHeader.indexOf("TYPE") !== -1) colMapBOM.desc = bc;
      if (bHeader.indexOf("QTY") !== -1 || bHeader.indexOf("WEIGHT") !== -1 || bHeader.indexOf("USAGE") !== -1 || bHeader.indexOf("RATIO") !== -1) colMapBOM.ratio = bc;
      if (bHeader.indexOf("UNIT") !== -1) colMapBOM.unit = bc;
      if (bHeader.indexOf("CATEGORY") !== -1) colMapBOM.category = bc;
    }
  }

  var bomList = [];
  for (var j = 1; j < bomData.length; j++) {
    var bRow = bomData[j];
    var fgP = normalizePartNo(bRow[colMapBOM.fgPart]);
    var rmP = String(bRow[colMapBOM.rmPart] || '').trim();
    if (!fgP || !rmP) continue;

    var rmDesc = String(bRow[colMapBOM.desc] || '').trim();
    var ratio = cleanNumber(bRow[colMapBOM.ratio]) || 1.0;
    var unit = String(bRow[colMapBOM.unit] || 'Nos').trim();
    var category = String(bRow[colMapBOM.category] || '').trim();

    // Auto classify category if missing
    if (!category) {
      var lowDesc = rmDesc.toLowerCase();
      if (lowDesc.indexOf("bobbin") !== -1) category = "Bobbin";
      else if (lowDesc.indexOf("core") !== -1 || lowDesc.indexOf("ferrite") !== -1) category = "Core";
      else if (lowDesc.indexOf("wire") !== -1 || lowDesc.indexOf("tiw") !== -1) category = "Wire";
      else if (lowDesc.indexOf("tape") !== -1) category = "Tape";
      else if (lowDesc.indexOf("sleeve") !== -1) category = "Sleeve";
      else category = "Other";
    }

    bomList.push({
      fgPart: fgP,
      rmPart: rmP,
      rmNorm: normalizePartNo(rmP),
      desc: rmDesc,
      ratio: ratio,
      unit: unit,
      category: category
    });
  }

  // 3. FETCH SHEET 3: Stocks (Daily Stock Updates)
  var stockSS = SpreadsheetApp.openById(SPREADSHEETS.STOCKS.id);
  var stockSheet = getSheetByGid(stockSS, SPREADSHEETS.STOCKS.gid);
  var stockData = stockSheet.getDataRange().getValues();

  var colMapStocks = {
    desc: 0,
    qty: 1,
    rate: 2,
    val: 3,
    partNo: 4
  };

  for (var s = 0; s < Math.min(3, stockData.length); s++) {
    for (var sc = 0; sc < stockData[s].length; sc++) {
      var sHeader = String(stockData[s][sc]).trim().toUpperCase();
      if (sHeader === "PART NO" || sHeader === "PART NO." || sHeader === "PARTICULARS" || sHeader === "ITEM CODE") colMapStocks.partNo = sc;
      if (sHeader === "QUANTITY" || sHeader === "CLOSING BALANCE" || sHeader === "STOCK") colMapStocks.qty = sc;
      if (sHeader === "RATE") colMapStocks.rate = sc;
      if (sHeader === "VALUE") colMapStocks.val = sc;
    }
  }

  var stockMap = {};
  for (var k = 1; k < stockData.length; k++) {
    var sRow = stockData[k];
    var sPart = String(sRow[colMapStocks.partNo] || sRow[0] || '').trim();
    if (!sPart) continue;

    var sNorm = normalizePartNo(sPart);
    var sQty = cleanNumber(sRow[colMapStocks.qty]);
    stockMap[sNorm] = (stockMap[sNorm] || 0.0) + sQty;
  }

  // 4. COMPUTATIONAL SHORTAGE ENGINE
  // Part-Wise Order BOM Explosion
  var factoryDemand = {};
  var orderAllocations = [];
  var readyOrdersCount = 0;
  var blockedOrdersCount = 0;

  for (var oi = 0; oi < activeOrders.length; oi++) {
    var ord = activeOrders[oi];
    var orderComps = [];
    var orderHasShortage = false;
    var maxBuildable = Infinity;

    for (var bi = 0; bi < bomList.length; bi++) {
      if (bomList[bi].fgPart === ord.partNo) {
        orderComps.push(bomList[bi]);
      }
    }

    var explodedItems = [];
    for (var ci = 0; ci < orderComps.length; ci++) {
      var comp = orderComps[ci];
      var grossReq = ord.openQty * comp.ratio;
      var availStock = stockMap[comp.rmNorm] !== undefined ? stockMap[comp.rmNorm] : 0.0;
      
      var covStatus = "FULL";
      if (availStock <= 0) {
        covStatus = "ZERO_STOCK";
        orderHasShortage = true;
      } else if (availStock < grossReq) {
        covStatus = "PARTIAL";
        orderHasShortage = true;
      }

      var canBuild = Math.floor(availStock / comp.ratio);
      if (canBuild < maxBuildable) maxBuildable = canBuild;

      explodedItems.push({
        rmPart: comp.rmPart,
        rmNorm: comp.rmNorm,
        desc: comp.desc,
        category: comp.category,
        ratio: comp.ratio,
        grossRequired: grossReq,
        availableStock: availStock,
        deficit: Math.max(0, grossReq - availStock),
        surplus: Math.max(0, availStock - grossReq),
        unit: comp.unit,
        coverageStatus: covStatus,
        canBuild: canBuild
      });

      // Factory Consolidated Demand
      if (!factoryDemand[comp.rmNorm]) {
        factoryDemand[comp.rmNorm] = {
          rmPart: comp.rmPart,
          rmNorm: comp.rmNorm,
          desc: comp.desc,
          category: comp.category,
          unit: comp.unit,
          totalRequired: 0.0,
          availableStock: availStock,
          orders: []
        };
      }
      factoryDemand[comp.rmNorm].totalRequired += grossReq;
      factoryDemand[comp.rmNorm].orders.push({
        fgPart: ord.partNo,
        customer: ord.customer,
        orderQty: ord.openQty,
        grossRequired: grossReq
      });
    }

    if (orderComps.length === 0) {
      orderHasShortage = true;
      maxBuildable = 0;
    }
    if (maxBuildable === Infinity) maxBuildable = 0;

    if (orderHasShortage) blockedOrdersCount++;
    else readyOrdersCount++;

    orderAllocations.push({
      partNo: ord.partNo,
      customer: ord.customer,
      desc: ord.desc,
      itemCode: ord.itemCode,
      openQty: ord.openQty,
      hasShortage: orderHasShortage,
      maxBuildable: maxBuildable,
      statusLabel: orderHasShortage ? "Blocked by Shortage" : "Ready to Produce",
      components: explodedItems
    });
  }

  // 5. Overall Factory Shortage List (Consolidated Procurement Plan)
  var procurementList = [];
  var stockedCount = 0;
  var shortageCount = 0;

  for (var key in factoryDemand) {
    var item = factoryDemand[key];
    var netShortage = Math.max(0, item.totalRequired - item.availableStock);
    var freeStock = Math.max(0, item.availableStock - item.totalRequired);
    var coveragePct = item.totalRequired > 0 
      ? Math.round((item.availableStock / item.totalRequired) * 100) 
      : 100;

    var action = "STOCKED";
    if (netShortage > 0) {
      action = "BUY NEEDED";
      shortageCount++;
    } else {
      stockedCount++;
    }

    procurementList.push({
      rmPart: item.rmPart,
      rmNorm: item.rmNorm,
      desc: item.desc,
      category: item.category,
      unit: item.unit,
      totalRequired: item.totalRequired,
      availableStock: item.availableStock,
      netShortage: netShortage,
      freeStock: freeStock,
      coveragePct: coveragePct,
      action: action,
      impactedOrdersCount: item.orders.length,
      orders: item.orders
    });
  }

  // Sort by net shortage descending
  procurementList.sort(function(a, b) {
    return b.netShortage - a.netShortage;
  });

  return {
    success: true,
    timestamp: timestamp,
    kpi: {
      activeOpenOrdersCount: activeOrders.length,
      totalPendingFGUnits: totalOpenFGQty,
      uniqueRMPartsCount: procurementList.length,
      stockedMaterialsCount: stockedCount,
      shortageMaterialsCount: shortageCount,
      readyOrdersCount: readyOrdersCount,
      blockedOrdersCount: blockedOrdersCount
    },
    procurementSummary: procurementList,
    orderAllocations: orderAllocations
  };
}
