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
    id: "1-bVdXQ7eDiRF3876wHDdaD94kbVRII7Mq3DU37e4EGg", // open order FG(14.10.2026)
    gid: 0,
    name: "open order FG(14.10.2026)"
  },
  FG_STOCKS: {
    id: "1F7a15XQvWvRBjFOWRO2-gSiMfj3vw16c0FWUW28XCa4", // Daily FG stock (14.10.2026)
    gid: 0,
    name: "Daily FG stock (14.10.2026)"
  },
  WIP_STOCKS: {
    id: "112padFLp9mRsSuN39Xy3umFOsjUmSOMvHPtnyIauNik", // Daily wip Stock
    gid: 0,
    name: "Daily wip Stock"
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

  // 4. FETCH SHEET 4: Daily FG Stock (14.10.2026)
  var fgStockMap = {};
  try {
    var fgSS = SpreadsheetApp.openById(SPREADSHEETS.FG_STOCKS.id);
    var fgSheet = getSheetByGid(fgSS, SPREADSHEETS.FG_STOCKS.gid);
    var fgData = fgSheet.getDataRange().getValues();
    var colMapFG = { partNo: -1, tallyPart: -1, qty: -1 };
    
    // Scan headers in first 3 rows
    for (var fgr = 0; fgr < Math.min(3, fgData.length); fgr++) {
      for (var fgc = 0; fgc < fgData[fgr].length; fgc++) {
        var fgh = String(fgData[fgr][fgc]).trim().toUpperCase();
        if (fgh.indexOf("TALLY") !== -1) colMapFG.tallyPart = fgc;
        else if (fgh.indexOf("PART") !== -1 || fgh.indexOf("ITEM") !== -1 || fgh.indexOf("CODE") !== -1) {
          if (colMapFG.partNo === -1) colMapFG.partNo = fgc;
        }
        if (fgh.indexOf("QTY") !== -1 || fgh.indexOf("STOCK") !== -1 || fgh.indexOf("BALANCE") !== -1 || fgh.indexOf("CLOSING") !== -1) colMapFG.qty = fgc;
      }
    }
    if (colMapFG.partNo === -1) colMapFG.partNo = 0;
    if (colMapFG.qty === -1) colMapFG.qty = 1;

    for (var fi = 1; fi < fgData.length; fi++) {
      var fRow = fgData[fi];
      var fPart = normalizePartNo(fRow[colMapFG.partNo]);
      var fTally = colMapFG.tallyPart !== -1 ? normalizePartNo(fRow[colMapFG.tallyPart]) : '';
      var fQty = cleanNumber(fRow[colMapFG.qty]);

      if (fPart) fgStockMap[fPart] = (fgStockMap[fPart] || 0.0) + fQty;
      if (fTally && fTally !== fPart) fgStockMap[fTally] = (fgStockMap[fTally] || 0.0) + fQty;
    }
  } catch (errFG) {
    Logger.log("Notice: Error reading FG Stock sheet: " + errFG.toString());
  }

  // 5. FETCH SHEET 5: Daily WIP Stock
  var wipStockMap = {};
  try {
    var wipSS = SpreadsheetApp.openById(SPREADSHEETS.WIP_STOCKS.id);
    var wipSheet = getSheetByGid(wipSS, SPREADSHEETS.WIP_STOCKS.gid);
    var wipData = wipSheet.getDataRange().getValues();
    var colMapWIP = { partNo: -1, tallyPart: -1, qty: -1 };
    
    // Scan headers in first 3 rows
    for (var wr = 0; wr < Math.min(3, wipData.length); wr++) {
      for (var wc = 0; wc < wipData[wr].length; wc++) {
        var wh = String(wipData[wr][wc]).trim().toUpperCase();
        if (wh.indexOf("TALLY") !== -1) colMapWIP.tallyPart = wc;
        else if (wh.indexOf("PART") !== -1 || wh.indexOf("ITEM") !== -1 || wh.indexOf("CODE") !== -1) {
          if (colMapWIP.partNo === -1) colMapWIP.partNo = wc;
        }
        if (wh.indexOf("QTY") !== -1 || wh.indexOf("STOCK") !== -1 || wh.indexOf("WIP") !== -1 || wh.indexOf("BALANCE") !== -1) colMapWIP.qty = wc;
      }
    }
    if (colMapWIP.partNo === -1) colMapWIP.partNo = 0;
    if (colMapWIP.qty === -1) colMapWIP.qty = 1;

    for (var wi = 1; wi < wipData.length; wi++) {
      var wRow = wipData[wi];
      var wPart = normalizePartNo(wRow[colMapWIP.partNo]);
      var wTally = colMapWIP.tallyPart !== -1 ? normalizePartNo(wRow[colMapWIP.tallyPart]) : '';
      var wQty = cleanNumber(wRow[colMapWIP.qty]);

      if (wPart) wipStockMap[wPart] = (wipStockMap[wPart] || 0.0) + wQty;
      if (wTally && wTally !== wPart) wipStockMap[wTally] = (wipStockMap[wTally] || 0.0) + wQty;
    }
  } catch (errWIP) {
    Logger.log("Notice: Error reading WIP Stock sheet: " + errWIP.toString());
  }

  // 6. COMPUTATIONAL SHORTAGE ENGINE (WITH DUAL PART NO & TALLY PART NO STOCK NETTING)
  // Formula: Actual Open Order FG Qty = Math.max(0, Open Qty - (Daily FG Stock + Daily WIP Stock))
  var factoryDemand = {};
  var orderAllocations = [];
  var readyOrdersCount = 0;
  var blockedOrdersCount = 0;
  var totalBalanceQty = 0;

  for (var oi = 0; oi < activeOrders.length; oi++) {
    var ord = activeOrders[oi];
    var normP = ord.partNo;
    var normItem = normalizePartNo(ord.itemCode);

    // Dual match on both Part No and Tally Part No / Item Code
    var fgStock = fgStockMap[normP] !== undefined ? fgStockMap[normP] : (normItem && fgStockMap[normItem] !== undefined ? fgStockMap[normItem] : 0.0);
    var wipStock = wipStockMap[normP] !== undefined ? wipStockMap[normP] : (normItem && wipStockMap[normItem] !== undefined ? wipStockMap[normItem] : 0.0);
    var balanceQty = Math.max(0, ord.openQty - (fgStock + wipStock));
    totalBalanceQty += balanceQty;

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
      // Raw Material Demand is strictly based on Balance Qty
      var grossReq = balanceQty * comp.ratio;
      var availStock = stockMap[comp.rmNorm] !== undefined ? stockMap[comp.rmNorm] : 0.0;
      
      var covStatus = "FULL";
      if (balanceQty === 0) {
        covStatus = "COVERED_BY_FG";
      } else if (availStock <= 0) {
        covStatus = "ZERO_STOCK";
        orderHasShortage = true;
      } else if (availStock < grossReq) {
        covStatus = "PARTIAL";
        orderHasShortage = true;
      }

      var canBuild = comp.ratio > 0 ? Math.floor(availStock / comp.ratio) : 0;
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

      // Factory Consolidated Demand (Only if balanceQty > 0)
      if (grossReq > 0) {
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
          balanceQty: balanceQty,
          grossRequired: grossReq
        });
      }
    }

    if (balanceQty === 0) {
      // Order is already fully satisfied by FG Stock and WIP Stock!
      orderHasShortage = false;
      maxBuildable = ord.openQty;
      readyOrdersCount++;
    } else {
      if (orderComps.length === 0) {
        orderHasShortage = true;
        maxBuildable = 0;
      }
      if (maxBuildable === Infinity) maxBuildable = 0;

      if (orderHasShortage) blockedOrdersCount++;
      else readyOrdersCount++;
    }

    var statusLabel = "Ready to Produce";
    if (balanceQty === 0) {
      statusLabel = "Fully Covered by FG/WIP Stock";
    } else if (orderHasShortage) {
      statusLabel = "Blocked by Shortage";
    }

    orderAllocations.push({
      partNo: ord.partNo,
      customer: ord.customer,
      desc: ord.desc,
      itemCode: ord.itemCode,
      openQty: ord.openQty,
      fgStock: fgStock,
      wipStock: wipStock,
      balanceQty: balanceQty,
      hasShortage: orderHasShortage,
      maxBuildable: maxBuildable,
      statusLabel: statusLabel,
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
