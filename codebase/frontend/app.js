/* ==========================================================================
   SkyBill Smartphone Simulator — Interactive Logic & Backend Integration
   ========================================================================== */

(function () {
  "use strict";

  const STORAGE_KEY = "skybill_receipts_v1";
  const CONFIRMED_CAPTURES_KEY = "skybill_confirmed_captures_v1";
  const CATEGORIES = [
    "Ăn uống",
    "Di chuyển",
    "Mua sắm",
    "Hóa đơn & Nhà ở",
    "Giải trí",
    "Sức khỏe",
    "Khác",
    "không rõ",
  ];

  const SEED_RECEIPTS = [
    {
      id: "HD-1101",
      date: "2026-11-03",
      time: "12:15",
      merchant: "Bếp Cơm Mẫu 01",
      category: "Ăn uống",
      date_source: "Từ hóa đơn",
      total: 48000,
      items: [{ name: "Suất cơm trưa", price: 48000 }],
    },
    {
      id: "HD-1102",
      date: "2026-11-08",
      time: "17:20",
      merchant: "Nhà Thuốc An Tâm",
      category: "Sức khỏe",
      date_source: "Từ hóa đơn",
      total: 130000,
      items: [{ name: "Vitamin C & Khẩu trang", price: 130000 }],
    },
    {
      id: "HD-1103",
      date: "2026-11-15",
      time: "10:10",
      merchant: "Internet & Điện Mẫu",
      category: "Hóa đơn & Nhà ở",
      date_source: "Từ hóa đơn",
      total: 570000,
      items: [{ name: "Điện + Internet tháng 11", price: 570000 }],
    },
    {
      id: "HD-1104",
      date: "2026-11-20",
      time: "08:15",
      merchant: "Cà Phê Bầu Trời",
      category: "Ăn uống",
      date_source: "Từ hóa đơn",
      total: 39000,
      items: [{ name: "Bạc xỉu đá", price: 39000 }],
    },
    {
      id: "HD-1105",
      date: "2026-11-20",
      time: "19:45",
      merchant: "Siêu Thị Mini B",
      category: "Mua sắm",
      date_source: "Từ hóa đơn",
      total: 233000,
      items: [{ name: "Sữa tươi & Bình giữ nhiệt", price: 233000 }],
    },
    {
      id: "HD-1108",
      date: "2026-11-25",
      time: "20:10",
      merchant: "Lẩu Nướng Nhóm",
      category: "Ăn uống",
      date_source: "Từ hóa đơn",
      total: 210000,
      items: [{ name: "Liên hoan nhóm", price: 210000 }],
    },
    {
      id: "HD-1111",
      date: "2026-11-27",
      time: "12:05",
      merchant: "Quán Cơm Gà Mẫu",
      category: "Ăn uống",
      date_source: "Từ hóa đơn",
      total: 65000,
      items: [{ name: "Cơm gà xối mỡ", price: 65000 }],
    },
  ];

  // State
  const state = {
    receipts: [],
    confirmedCaptures: new Set(),
    backendOnline: false,
    todayIso: getLocalTodayIso(),
    calYear: 2026,
    calMonth: 11,
    selectedDate: "",
    dayExpanded: false,
    analyticsPeriod: "month",
    analyticsAnchor: "2026-11-28",
    activeCaptureId: "",
    lastSubmittedCaptureId: "",
    currentImageDataUrl: "",
    currentDraft: null,
    selectedCategory: "Ăn uống",
    cameraStream: null,
    toastTimer: null,
  };

  // DOM helpers
  const $ = (id) => document.getElementById(id);

  function getLocalTodayIso() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function formatVnd(n) {
    return `${Math.round(Number(n) || 0).toLocaleString("vi-VN")} ₫`;
  }

  // Ô lịch: hiện đủ số tiền, không làm tròn (75.500 chứ không phải 76k).
  function formatCompactVnd(n) {
    const v = Math.round(Number(n) || 0);
    return v > 0 ? v.toLocaleString("vi-VN") : "";
  }

  function formatDateVi(iso) {
    if (!iso || iso.length < 10) return iso || "—";
    const [y, m, d] = iso.slice(0, 10).split("-");
    return `${d}/${m}/${y}`;
  }

  function showToast(msg) {
    const el = $("phone-toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => el.classList.add("hidden"), 2800);
  }

  function newCaptureId() {
    return "CAP-" + Math.random().toString(36).slice(2, 8).toUpperCase();
  }

  function saveLocalCache() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.receipts));
      localStorage.setItem(
        CONFIRMED_CAPTURES_KEY,
        JSON.stringify(Array.from(state.confirmedCaptures))
      );
    } catch (_) {}
  }

  function loadLocalCache() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length) state.receipts = parsed;
      }
      const caps = localStorage.getItem(CONFIRMED_CAPTURES_KEY);
      if (caps) {
        const parsedCaps = JSON.parse(caps);
        if (Array.isArray(parsedCaps)) state.confirmedCaptures = new Set(parsedCaps);
      }
    } catch (_) {}
    if (!state.receipts.length) {
      state.receipts = SEED_RECEIPTS.map((r) => ({ ...r }));
    }
  }

  // =========================================================================
  // Backend Sync
  // =========================================================================
  async function initBackend() {
    const pill = $("backend-status-pill");
    const ocrEl = $("rail-ocr-status");
    try {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error("offline");
      const health = await res.json();
      state.backendOnline = true;
      if (pill) {
        pill.textContent = "Backend ON";
        pill.classList.add("online");
      }
      if (ocrEl) {
        ocrEl.textContent = health.ocr?.engine_ready ? `OCR: ${health.ocr.engine_version}` : "OCR chưa sẵn sàng";
      }
      const rRes = await fetch("/api/receipts");
      if (rRes.ok) {
        const data = await rRes.json();
        if (Array.isArray(data.receipts)) {
          state.receipts = data.receipts;
          data.receipts.forEach((r) => {
            if (r.capture_id) state.confirmedCaptures.add(r.capture_id);
          });
          saveLocalCache();
        }
      }
    } catch (_) {
      state.backendOnline = false;
      if (pill) pill.textContent = "Chế độ Tĩnh (Local)";
      if (ocrEl) ocrEl.textContent = "Demo OCR cục bộ";
      loadLocalCache();
    }
  }

  // =========================================================================
  // Navigation & Clock
  // =========================================================================
  function switchScreen(name) {
    document.querySelectorAll(".app-screen").forEach((s) => s.classList.remove("active"));
    const target = $(`screen-${name}`);
    if (target) target.classList.add("active");

    document.querySelectorAll(".tab-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.screen === name);
    });

    if (name === "calendar") renderCalendar();
    if (name === "analytics") renderAnalytics();
  }

  function updateClock() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    const clock = $("phone-clock");
    if (clock) clock.textContent = `${hh}:${mm}`;
  }

  // =========================================================================
  // Screen 1: Calendar & Day Detail
  // =========================================================================
  function renderCalendar() {
    const ym = `${state.calYear}-${String(state.calMonth).padStart(2, "0")}`;
    $("calendar-month-label").textContent = `Tháng ${String(state.calMonth).padStart(2, "0")}/${state.calYear}`;

    const monthReceipts = state.receipts.filter((r) => String(r.date || "").startsWith(ym));
    const dayTotals = {};
    monthReceipts.forEach((r) => {
      dayTotals[r.date] = (dayTotals[r.date] || 0) + (Number(r.total) || 0);
    });

    const monthSum = monthReceipts.reduce((s, r) => s + (Number(r.total) || 0), 0);
    $("stat-month-spend").textContent = formatVnd(monthSum);
    $("stat-total-receipts").textContent = String(monthReceipts.length);

    let peakDate = "—";
    let peakVal = 0;
    Object.entries(dayTotals).forEach(([d, val]) => {
      if (val > peakVal) {
        peakVal = val;
        peakDate = d.slice(8, 10) + "/" + d.slice(5, 7);
      }
    });
    $("stat-peak-day").textContent = peakVal > 0 ? `${peakDate}` : "—";

    const railCount = $("rail-receipt-count");
    if (railCount) railCount.textContent = String(state.receipts.length);

    // Build 42-cell grid (Monday first)
    const firstDay = new Date(state.calYear, state.calMonth - 1, 1);
    const startOffset = (firstDay.getDay() + 6) % 7; // Mon=0..Sun=6
    const daysInMonth = new Date(state.calYear, state.calMonth, 0).getDate();
    const prevMonthDays = new Date(state.calYear, state.calMonth - 1, 0).getDate();

    const grid = $("calendar-grid");
    grid.innerHTML = "";

    for (let i = 0; i < 42; i++) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cal-cell";

      let cellIso = "";
      let dayNum = 0;
      let isOutside = false;

      if (i < startOffset) {
        dayNum = prevMonthDays - startOffset + i + 1;
        isOutside = true;
      } else if (i >= startOffset + daysInMonth) {
        dayNum = i - startOffset - daysInMonth + 1;
        isOutside = true;
      } else {
        dayNum = i - startOffset + 1;
        cellIso = `${ym}-${String(dayNum).padStart(2, "0")}`;
      }

      if (isOutside) {
        btn.classList.add("outside");
        btn.disabled = true;
        btn.innerHTML = `<span class="cal-day-num">${dayNum}</span><span class="cal-amt"></span>`;
      } else {
        const amt = dayTotals[cellIso] || 0;
        if (amt > 0 && amt < 150000) btn.classList.add("lvl-1");
        else if (amt >= 150000 && amt < 400000) btn.classList.add("lvl-2");
        else if (amt >= 400000 && amt < 800000) btn.classList.add("lvl-3");
        else if (amt >= 800000) btn.classList.add("lvl-4");

        if (cellIso === state.selectedDate) btn.classList.add("selected");
        if (cellIso === state.todayIso) btn.classList.add("today");

        btn.innerHTML = `
          <span class="cal-day-num">${dayNum}</span>
          <span class="cal-amt">${formatCompactVnd(amt)}</span>
        `;
        btn.addEventListener("click", () => {
          state.selectedDate = cellIso;
          state.dayExpanded = false;
          renderCalendar();
        });
      }
      grid.appendChild(btn);
    }

    renderDayDetail();
  }

  function buildReceiptPreviewSvg(receipt) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="420" viewBox="0 0 320 420">
      <rect width="320" height="420" fill="#ffffff"/>
      <rect x="16" y="16" width="288" height="388" rx="12" fill="#f8fafc" stroke="#cbd5e1"/>
      <text x="160" y="54" text-anchor="middle" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a">${escapeXml(receipt.merchant || "Hóa đơn")}</text>
      <text x="160" y="76" text-anchor="middle" font-family="monospace" font-size="12" fill="#64748b">${escapeXml(receipt.date)} ${escapeXml(receipt.time || "")}</text>
      <line x1="36" y1="96" x2="284" y2="96" stroke="#cbd5e1" stroke-dasharray="4 4"/>
      <text x="36" y="132" font-family="sans-serif" font-size="13" fill="#334155">Nhóm: ${escapeXml(receipt.category || "Khác")}</text>
      <text x="36" y="160" font-family="sans-serif" font-size="13" fill="#334155">Mã: ${escapeXml(receipt.id || "")}</text>
      <line x1="36" y1="300" x2="284" y2="300" stroke="#cbd5e1" stroke-dasharray="4 4"/>
      <text x="36" y="336" font-family="sans-serif" font-size="14" font-weight="bold" fill="#0f172a">TỔNG THỰC TRẢ</text>
      <text x="284" y="336" text-anchor="end" font-family="sans-serif" font-size="18" font-weight="bold" fill="#0284c7">${escapeXml(formatVnd(receipt.total))}</text>
    </svg>`;
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  }

  function escapeXml(s) {
    return String(s || "").replace(/[<>&'"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" }[c]));
  }

  function renderDayDetail() {
    const iso = state.selectedDate;
    $("day-detail-title").textContent = formatDateVi(iso);
    $("day-detail-badge").textContent = iso === state.todayIso ? "Hôm nay" : "Ngày đã chọn";

    const list = state.receipts.filter((r) => r.date === iso);
    const total = list.reduce((s, r) => s + (Number(r.total) || 0), 0);
    $("day-total-spend").textContent = formatVnd(total);

    if (!list.length) {
      $("day-empty-state").classList.remove("hidden");
      $("day-has-data").classList.add("hidden");
      return;
    }

    $("day-empty-state").classList.add("hidden");
    $("day-has-data").classList.remove("hidden");

    // Category breakdown
    const byCat = {};
    list.forEach((r) => {
      const c = r.category || "không rõ";
      byCat[c] = (byCat[c] || 0) + (Number(r.total) || 0);
    });
    const catBox = $("day-category-breakdown");
    catBox.innerHTML = "";
    Object.entries(byCat)
      .sort((a, b) => b[1] - a[1])
      .forEach(([cat, amt]) => {
        const pct = total > 0 ? Math.round((amt / total) * 100) : 0;
        const row = document.createElement("div");
        row.className = "cat-row";
        row.innerHTML = `
          <div class="cat-row-top"><span>${cat}</span><span>${formatVnd(amt)} (${pct}%)</span></div>
          <div class="cat-bar-bg"><div class="cat-bar-fill" style="width:${pct}%"></div></div>
        `;
        catBox.appendChild(row);
      });

    // Toggle button
    const toggleBtn = $("btn-toggle-day-items");
    const itemsList = $("day-receipts-list");
    toggleBtn.classList.toggle("open", state.dayExpanded);
    itemsList.classList.toggle("hidden", !state.dayExpanded);
    $("see-more-label").textContent = state.dayExpanded
      ? `Thu gọn (${list.length} khoản)`
      : `Xem thêm (${list.length} khoản & ảnh hóa đơn)`;

    itemsList.innerHTML = "";
    list.forEach((r) => {
      const imgSrc = r.image_data_url
        ? r.image_data_url
        : r.image_path
        ? `/csdl/images/${encodeURIComponent(r.image_path)}`
        : buildReceiptPreviewSvg(r);

      const card = document.createElement("div");
      card.className = "receipt-item-card";
      card.innerHTML = `
        <button type="button" class="receipt-thumb-btn" title="Xem ảnh hóa đơn gốc">
          <img src="${imgSrc}" alt="Hóa đơn ${escapeXml(r.merchant)}" />
        </button>
        <div class="receipt-info">
          <div class="receipt-merchant">${escapeXml(r.merchant || "Không rõ nơi mua")}</div>
          <div class="receipt-meta">${escapeXml(r.category)} · ${escapeXml(r.date_source || "Từ hóa đơn")}</div>
        </div>
        <div class="receipt-right">
          <span class="receipt-amt">${formatVnd(r.total)}</span>
          <button type="button" class="receipt-del-btn">Xoá</button>
        </div>
      `;

      card.querySelector(".receipt-thumb-btn").addEventListener("click", () => {
        $("photo-modal-img").src = imgSrc;
        $("photo-modal-caption").textContent = `${r.merchant} · ${formatDateVi(r.date)} · ${formatVnd(r.total)}`;
        $("photo-modal").classList.remove("hidden");
      });

      card.querySelector(".receipt-del-btn").addEventListener("click", () => deleteReceipt(r.id));
      itemsList.appendChild(card);
    });
  }

  async function deleteReceipt(id) {
    if (state.backendOnline) {
      try {
        await fetch(`/api/receipts/${encodeURIComponent(id)}`, { method: "DELETE" });
      } catch (_) {}
    }
    state.receipts = state.receipts.filter((r) => r.id !== id);
    saveLocalCache();
    renderCalendar();
    showToast("Đã xoá khoản chi khỏi sổ");
    refreshInsights();
  }

  // =========================================================================
  // Camera & Receipt Capture Sheet (+ Flow)
  // =========================================================================
  function openCaptureSheet(targetDate) {
    state.activeCaptureId = newCaptureId();
    state.currentImageDataUrl = "";
    state.currentDraft = null;
    $("capture-id-badge").textContent = state.activeCaptureId;
    $("rail-last-capture").textContent = state.activeCaptureId;
    $("capture-target-date").value = targetDate || state.selectedDate || state.todayIso;

    showSheetStep("camera");
    $("capture-preview").classList.add("hidden");
    $("viewfinder-placeholder").classList.remove("hidden");
    $("btn-run-ocr").disabled = true;
    $("capture-sheet").classList.remove("hidden");
  }

  function closeCaptureSheet() {
    stopCamera();
    $("capture-sheet").classList.add("hidden");
  }

  function showSheetStep(step) {
    $("step-camera").classList.toggle("hidden", step !== "camera");
    $("step-reread").classList.toggle("hidden", step !== "reread");
    $("step-draft").classList.toggle("hidden", step !== "draft");
    if (step === "camera") $("sheet-title").textContent = "Chụp hóa đơn mới";
    if (step === "reread") $("sheet-title").textContent = "Cần đọc lại hóa đơn";
    if (step === "draft") $("sheet-title").textContent = "Bản xem nhanh (Draft)";
  }

  async function toggleCamera() {
    if (state.cameraStream) {
      stopCamera();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      state.cameraStream = stream;
      const video = $("camera-video");
      video.srcObject = stream;
      video.classList.remove("hidden");
      $("capture-preview").classList.add("hidden");
      $("viewfinder-placeholder").classList.add("hidden");
      $("btn-shutter").disabled = false;
      $("btn-toggle-cam").textContent = "Tắt cam";
    } catch (_) {
      showToast("Không truy cập được camera — hãy dùng Tải ảnh hoặc Ảnh mẫu");
    }
  }

  function stopCamera() {
    if (state.cameraStream) {
      state.cameraStream.getTracks().forEach((t) => t.stop());
      state.cameraStream = null;
    }
    $("camera-video").classList.add("hidden");
    $("btn-shutter").disabled = true;
    $("btn-toggle-cam").textContent = "Bật camera";
  }

  function takePhoto() {
    const video = $("camera-video");
    const canvas = $("camera-canvas");
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    setCapturedImage(canvas.toDataURL("image/jpeg", 0.9));
    stopCamera();
  }

  function setCapturedImage(dataUrl) {
    state.currentImageDataUrl = dataUrl;
    const prev = $("capture-preview");
    prev.src = dataUrl;
    prev.classList.remove("hidden");
    $("viewfinder-placeholder").classList.add("hidden");
    $("btn-run-ocr").disabled = false;
  }

  function generateSampleReceiptImage(mode) {
    const canvas = document.createElement("canvas");
    canvas.width = 420;
    canvas.height = 540;
    const ctx = canvas.getContext("2d");

    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, 420, 540);

    if (mode === "blurry") {
      ctx.filter = "blur(5px)";
      ctx.fillStyle = "#94a3b8";
    } else {
      ctx.fillStyle = "#0f172a";
    }

    ctx.font = "bold 22px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(mode === "blurry" ? "HOA DON MO..." : "HIGHLANDS COFFEE", 210, 64);

    ctx.font = "15px monospace";
    if (mode === "clear") {
      ctx.fillText(`Ngay: ${formatDateVi(state.todayIso)}  09:30`, 210, 98);
    } else if (mode === "nodate") {
      ctx.fillText("(Thieu ngay tren hoa don)", 210, 98);
    } else {
      ctx.fillText("Ngay: ??/??/????", 210, 98);
    }

    ctx.textAlign = "left";
    ctx.fillText("1x Phin Sua Da          45,000", 42, 170);
    ctx.fillText("1x Banh Mi Que          19,000", 42, 204);

    ctx.beginPath();
    ctx.moveTo(42, 260);
    ctx.lineTo(378, 260);
    ctx.strokeStyle = "#cbd5e1";
    ctx.stroke();

    ctx.font = "bold 20px monospace";
    ctx.fillText(mode === "blurry" ? "TONG: ???,???" : "TONG THUC TRA: 64,000 VND", 42, 310);

    return canvas.toDataURL("image/jpeg", 0.92);
  }

  async function runOcrAndCreateDraft(modeHint = "auto") {
    if (!state.currentImageDataUrl) return;
    const targetDate = $("capture-target-date").value || state.todayIso;
    const filename =
      modeHint === "blurry"
        ? "hoa_don_mo.jpg"
        : modeHint === "nodate"
        ? "hoa_don_thieu_ngay.jpg"
        : "hoa_don_ro.jpg";

    $("btn-run-ocr").disabled = true;
    $("btn-run-ocr").textContent = "Đang đọc hóa đơn…";

    let scanData = null;
    let scanError = "";
    const useBackend = state.backendOnline && modeHint === "auto";
    if (useBackend) {
      try {
        const res = await fetch("/api/receipts/scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            image_data_url: state.currentImageDataUrl,
            receipt_date: targetDate,
            source_mode: "camera",
            filename,
          }),
        });
        const body = await res.json();
        if (res.ok) scanData = body;
        else scanError = body.error || "Máy chủ chưa đọc được ảnh.";
      } catch (_) {
        scanError = "Chưa kết nối được máy chủ để đọc ảnh.";
      }
    }

    $("btn-run-ocr").disabled = false;
    $("btn-run-ocr").textContent = "Đọc hóa đơn (Tạo bản xem nhanh)";

    // Evaluate quality / G10 blurry check
    // Backend là nguồn quyết định: không hợp lệ / lỗi → Cần đọc lại, không tạo bản nháp giả.
    const backendRejected = useBackend && (!scanData || !scanData.validation?.valid || !scanData.draft);
    const isBlurry = modeHint === "blurry" || backendRejected;

    if (isBlurry) {
      const missing = scanData?.validation?.missing_fields || [];
      const reason = scanError
        || (scanData?.quality_report?.quality_status === "fail" ? "Ảnh bị mờ hoặc lóa (G10)." : "")
        || (missing.includes("paid_total") ? "Chưa xác định rõ số tiền thực trả." : "")
        || (missing.includes("date") ? "Chưa đọc được ngày hợp lệ." : "")
        || "Ảnh bị mờ hoặc chưa xác định rõ số tiền thực trả (G10).";
      $("reread-reason").textContent = reason + " Chưa ghi khoản chi, tổng chi tiêu trong sổ được giữ nguyên.";
      $("reread-preview").src = state.currentImageDataUrl;
      // Ảnh không chắc số tiền: AI không đoán, cho người dùng tự gõ số thực trả (ảnh vẫn được lưu kèm).
      state.manualDraft = scanData?.manual_draft || null;
      $("btn-manual-reread").classList.toggle("hidden", !state.manualDraft);
      showSheetStep("reread");
      return;
    }

    const draft = scanData?.draft
      ? { ...scanData.draft, total: scanData.draft.printed_total }
      : {
      merchant: modeHint === "nodate" ? "Tiệm Bánh Phố Cổ" : "Highlands Coffee",
      date: targetDate,
      category: "Ăn uống",
      total: 64000,
      items: [
        { name: "Phin Sữa Đá", price: 45000 },
        { name: "Bánh Mì Que", price: 19000 },
      ],
    };

    const missingDate = modeHint === "nodate" || (scanData?.validation?.missing_fields || []).includes("date");
    const dateSource = missingDate ? "Ngày chụp mặc định" : "Từ hóa đơn";

    state.currentDraft = {
      ...draft,
      capture_id: draft.capture_id || state.activeCaptureId,
      date: draft.date || targetDate,
      date_source: dateSource,
      image_data_url: state.currentImageDataUrl,
    };

    populateDraftForm(state.currentDraft, missingDate);
    showSheetStep("draft");
  }

  function openManualDraft() {
    const draft = state.manualDraft;
    if (!draft) return;
    const isCaptureDate = draft.date_source !== "hóa đơn";
    state.currentDraft = {
      ...draft,
      total: 0,
      date_source: isCaptureDate ? "Ngày chụp mặc định" : "Từ hóa đơn",
      image_data_url: state.currentImageDataUrl,
    };
    populateDraftForm(state.currentDraft, isCaptureDate);
    $("draft-total-input").value = "";
    $("draft-total-input").placeholder = "Nhập số tiền thực trả";
    $("draft-items-summary").textContent = "Tự nhập · AI chưa đọc chắc số tiền";
    showSheetStep("draft");
    $("draft-total-input").focus();
  }

  function populateDraftForm(draft, isDefaultDate) {
    $("draft-total-input").value = Number(draft.total || 0);
    $("draft-date-input").value = draft.date || state.todayIso;
    $("draft-merchant-input").value = draft.merchant || "";

    const srcBadge = $("draft-date-source-badge");
    srcBadge.textContent = draft.date_source || "Từ hóa đơn";
    srcBadge.classList.toggle("default-date", Boolean(isDefaultDate));

    state.selectedCategory = CATEGORIES.includes(draft.category) ? draft.category : "không rõ";
    renderCategoryChips();

    $("draft-thumb-img").src = state.currentImageDataUrl;
    $("draft-items-summary").textContent = `${(draft.items || []).length || 1} khoản chi · Xem nhanh`;
    $("draft-capture-id-text").textContent = `Mã lượt chụp: ${draft.capture_id}`;
  }

  function renderCategoryChips() {
    const box = $("draft-category-chips");
    box.innerHTML = "";
    CATEGORIES.forEach((cat) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cat-chip" + (cat === state.selectedCategory ? " active" : "");
      btn.textContent = cat;
      btn.addEventListener("click", () => {
        state.selectedCategory = cat;
        renderCategoryChips();
      });
      box.appendChild(btn);
    });
  }

  async function confirmChot(e) {
    if (e) e.preventDefault();
    if (!state.currentDraft) return;

    const captureId = state.currentDraft.capture_id || state.activeCaptureId;
    // Bản nháp từ backend: để backend kiểm trùng. Bản nháp demo cục bộ: kiểm trùng ở đây.
    if (!state.currentDraft.draft_id && state.confirmedCaptures.has(captureId)) {
      showToast("Trùng mã lượt chụp — giữ nguyên tổng ngày!");
      closeCaptureSheet();
      return;
    }

    const total = Math.round(Number($("draft-total-input").value) || 0);
    const date = $("draft-date-input").value || state.todayIso;
    const merchant = $("draft-merchant-input").value.trim() || "Khoản chi mới";

    if (total <= 0) {
      showToast("Số tiền thực trả phải lớn hơn 0 ₫");
      return;
    }

    const payload = {
      ...state.currentDraft,
      capture_id: captureId,
      date,
      merchant,
      category: state.selectedCategory,
      total,
      items: [{ name: merchant, price: total }],
    };

    let savedRecord = {
      ...payload,
      id: "HD-" + Math.random().toString(36).slice(2, 6).toUpperCase(),
      time: new Date().toTimeString().slice(0, 5),
    };

    let duplicate = false;
    if (state.backendOnline && payload.draft_id) {
      try {
        const res = await fetch("/api/receipts/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...payload, image_data_url: undefined }),
        });
        const data = await res.json();
        if (!res.ok || !data.receipt) {
          showToast(data.error || "Chưa lưu được khoản chi. Hãy thử lại.");
          return;
        }
        duplicate = Boolean(data.duplicate);
        savedRecord = { ...data.receipt, image_data_url: state.currentImageDataUrl };
      } catch (_) {
        showToast("Chưa kết nối được máy chủ. Chưa ghi khoản chi.");
        return;
      }
    }

    state.confirmedCaptures.add(captureId);
    state.lastSubmittedCaptureId = captureId;
    if (duplicate) {
      closeCaptureSheet();
      showToast("Trùng mã lượt chụp — khoản đã có, giữ nguyên tổng ngày!");
      return;
    }
    state.receipts.push(savedRecord);
    saveLocalCache();

    const [y, m] = savedRecord.date.split("-").map(Number);
    state.calYear = y;
    state.calMonth = m;
    state.selectedDate = savedRecord.date;
    state.dayExpanded = true;

    closeCaptureSheet();
    switchScreen("calendar");
    showToast(`Đã chốt ${formatVnd(total)} vào ngày ${formatDateVi(date)}`);
    refreshInsights({ notify: true });
  }

  // =========================================================================
  // Phân tích chi tiêu: hạn mức tháng, cảnh báo (backend code tính) + nhận xét AI
  // =========================================================================
  const ALERT_RANK = { danger: 3, warn: 2, info: 1 };

  async function refreshInsights({ notify = false } = {}) {
    if (!state.backendOnline) return null;
    try {
      const res = await fetch(`/api/insights?date=${state.todayIso}`);
      if (!res.ok) return null;
      state.insights = await res.json();
    } catch (_) {
      return null;
    }
    renderInsights();
    const top = topAlert(state.insights);
    if (notify && top && top.level !== "info") {
      setTimeout(() => showToast(`${top.title}: ${top.text}`), 2900);
    }
    return state.insights;
  }

  function topAlert(facts) {
    const alerts = (facts && facts.alerts) || [];
    return alerts.slice().sort((a, b) => ALERT_RANK[b.level] - ALERT_RANK[a.level])[0] || null;
  }

  function renderInsights() {
    const f = state.insights;
    if (!f) return;
    const top = topAlert(f);
    const banner = $("insight-banner");
    banner.classList.toggle("hidden", !top);
    if (top) {
      banner.dataset.level = top.level;
      $("insight-banner-icon").textContent = top.level === "info" ? "i" : "!";
      $("insight-banner-title").textContent = top.title;
      $("insight-banner-text").textContent = top.text;
    }

    $("insight-month-label").textContent = `tháng ${f.month}`;
    $("insight-today-total").textContent = `Hôm nay: ${formatVnd(f.today_total)}`;
    const b = f.budget;
    const st = f.settings || {};
    if (document.activeElement !== $("budget-input")) $("budget-input").value = b ? b.limit : "";
    if (document.activeElement !== $("income-input")) $("income-input").value = st.monthly_income || "";
    if (document.activeElement !== $("goal-input")) $("goal-input").value = st.savings_goal || "";
    const sv = f.savings;
    const svText = $("savings-text");
    svText.classList.toggle("hidden", !sv);
    if (sv) {
      svText.textContent = sv.goal
        ? `Mục tiêu để dành ${formatVnd(sv.goal)}/tháng · dự kiến để dành được ${formatVnd(sv.projected)}` +
          (sv.gap ? ` · còn thiếu ${formatVnd(sv.gap)}` : " · đạt mục tiêu")
        : `Dự kiến để dành được ${formatVnd(sv.projected)} (thu nhập − dự báo chi cuối tháng)`;
      svText.dataset.level = sv.projected < 0 ? "danger" : sv.gap ? "warn" : "ok";
    }
    $("budget-progress").classList.toggle("hidden", !b);
    if (b) {
      const fill = $("budget-bar-fill");
      fill.style.width = `${Math.min(b.used_pct, 100)}%`;
      fill.dataset.level = b.used_pct >= 100 ? "danger" : b.used_pct >= 80 ? "warn" : "ok";
      $("budget-progress-text").textContent = b.remaining >= 0
        ? `Đã chi ${formatVnd(f.month_total)} / ${formatVnd(b.limit)} (${String(b.used_pct).replace(".", ",")}%) · còn ${formatVnd(b.remaining)}` +
          (b.safe_per_day ? ` · nên chi ≤ ${formatVnd(b.safe_per_day)}/ngày` : "")
        : `Đã chi ${formatVnd(f.month_total)} / ${formatVnd(b.limit)} · vượt ${formatVnd(-b.remaining)}`;
      if (sv && sv.goal) $("budget-progress-text").textContent += " · hạn mức = thu nhập − mục tiêu để dành";
    }
    $("insight-forecast").textContent =
      `Trung bình ${formatVnd(f.daily_average)}/ngày · dự báo cuối tháng ${formatVnd(f.forecast_month_end)} · cùng kỳ tháng trước ${formatVnd(f.prev_same_span_total)}`;

    const list = $("insight-alerts");
    list.innerHTML = "";
    (f.alerts || []).forEach((a) => {
      const li = document.createElement("li");
      li.dataset.level = a.level;
      const strong = document.createElement("strong");
      strong.textContent = a.title;
      const span = document.createElement("span");
      span.textContent = a.text;
      li.append(strong, span);
      list.appendChild(li);
    });
    if (!(f.alerts || []).length) list.innerHTML = `<li data-level="ok"><strong>Chi tiêu ổn</strong><span>Chưa có cảnh báo nào trong tháng này.</span></li>`;

    const ideas = $("saving-ideas");
    ideas.innerHTML = "";
    (f.saving_ideas || []).forEach((idea) => {
      const li = document.createElement("li");
      li.textContent = idea.text;
      ideas.appendChild(li);
    });
    if (!(f.saving_ideas || []).length) ideas.innerHTML = "<li>Chưa có nhóm chi linh hoạt nào tăng hoặc chi thường xuyên để gợi ý.</li>";
  }

  async function saveSavings(e) {
    e.preventDefault();
    const toInt = (id) => ($(id).value.trim() === "" ? 0 : Number($(id).value));
    const income = toInt("income-input");
    const goal = toInt("goal-input");
    if (!Number.isInteger(income) || !Number.isInteger(goal) || income < 0 || goal < 0) {
      showToast("Thu nhập và số muốn để dành phải là số nguyên VND không âm");
      return;
    }
    try {
      const res = await fetch("/api/settings/savings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ monthly_income: income, savings_goal: goal }),
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || "Chưa lưu được mục tiêu để dành");
        return;
      }
      showToast(income ? `Mục tiêu để dành ${formatVnd(goal)} · hạn mức tháng ${formatVnd(data.monthly_budget)}` : "Đã tắt mục tiêu để dành");
    } catch (_) {
      showToast("Chưa kết nối được máy chủ");
      return;
    }
    document.activeElement?.blur();
    await refreshInsights({ notify: true });
  }

  async function saveBudget(e) {
    e.preventDefault();
    const raw = $("budget-input").value.trim();
    const amount = raw === "" ? 0 : Number(raw);
    if (!Number.isInteger(amount) || amount < 0) {
      showToast("Hạn mức phải là số nguyên VND không âm");
      return;
    }
    try {
      const res = await fetch("/api/settings/budget", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ monthly_budget: amount }),
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || "Chưa lưu được hạn mức");
        return;
      }
    } catch (_) {
      showToast("Chưa kết nối được máy chủ");
      return;
    }
    $("budget-input").blur();
    showToast(amount ? `Đã đặt hạn mức tháng ${formatVnd(amount)}` : "Đã tắt hạn mức tháng");
    await refreshInsights({ notify: true });
  }

  async function runAiInsight() {
    const btn = $("btn-ai-insight");
    btn.disabled = true;
    btn.textContent = "AI đang phân tích…";
    const list = $("ai-insight-lines");
    try {
      const res = await fetch("/api/insights/ai", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: state.todayIso }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "AI chưa trả lời");
      list.innerHTML = "";
      (data.lines.length ? data.lines : ["AI chưa đưa ra nhận xét khớp số liệu. Thử lại sau."]).forEach((line) => {
        const li = document.createElement("li");
        li.textContent = line;
        list.appendChild(li);
      });
      list.classList.remove("hidden");
      $("ai-insight-note").classList.remove("hidden");
    } catch (err) {
      showToast(String(err.message || err));
    } finally {
      btn.disabled = false;
      btn.textContent = "AI phân tích chi tiêu";
    }
  }

  // =========================================================================
  // Screen 2: Analytics (Tuần / Tháng / Năm)
  // =========================================================================
  function getPeriodBounds(period, anchorIso) {
    const [y, m, d] = anchorIso.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    if (period === "week") {
      const offset = (dt.getDay() + 6) % 7;
      const start = new Date(dt);
      start.setDate(dt.getDate() - offset);
      const end = new Date(start);
      end.setDate(start.getDate() + 6);
      const prevStart = new Date(start);
      prevStart.setDate(start.getDate() - 7);
      const prevEnd = new Date(start);
      prevEnd.setDate(start.getDate() - 1);
      const fmt = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
      return {
        label: `Tuần ${String(start.getDate()).padStart(2, "0")}/${String(start.getMonth() + 1).padStart(2, "0")}`,
        start: fmt(start),
        end: fmt(end),
        prevStart: fmt(prevStart),
        prevEnd: fmt(prevEnd),
      };
    }
    if (period === "year") {
      return {
        label: `Năm ${y}`,
        start: `${y}-01-01`,
        end: `${y}-12-31`,
        prevStart: `${y - 1}-01-01`,
        prevEnd: `${y - 1}-12-31`,
      };
    }
    const lastDay = new Date(y, m, 0).getDate();
    const pm = m === 1 ? 12 : m - 1;
    const py = m === 1 ? y - 1 : y;
    const pLast = new Date(py, pm, 0).getDate();
    return {
      label: `Tháng ${String(m).padStart(2, "0")}/${y}`,
      start: `${y}-${String(m).padStart(2, "0")}-01`,
      end: `${y}-${String(m).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`,
      prevStart: `${py}-${String(pm).padStart(2, "0")}-01`,
      prevEnd: `${py}-${String(pm).padStart(2, "0")}-${String(pLast).padStart(2, "0")}`,
    };
  }

  function renderAnalytics() {
    const b = getPeriodBounds(state.analyticsPeriod, state.analyticsAnchor);
    $("analytics-period-label").textContent = b.label;

    const cur = state.receipts.filter((r) => r.date >= b.start && r.date <= b.end);
    const prev = state.receipts.filter((r) => r.date >= b.prevStart && r.date <= b.prevEnd);

    const curSum = cur.reduce((s, r) => s + (Number(r.total) || 0), 0);
    const prevSum = prev.reduce((s, r) => s + (Number(r.total) || 0), 0);
    const diff = curSum - prevSum;
    const pct = prevSum > 0 ? Math.round((diff / prevSum) * 100) : null;

    $("kpi-current-total").textContent = formatVnd(curSum);
    $("kpi-current-range").textContent = `${formatDateVi(b.start)} – ${formatDateVi(b.end)}`;
    $("kpi-delta-pct").textContent = pct === null ? (curSum > 0 ? "Mới" : "0%") : `${diff >= 0 ? "+" : ""}${pct}%`;
    $("kpi-delta-vnd").textContent = `${diff >= 0 ? "+" : ""}${formatVnd(diff)}`;
    $("kpi-receipt-count").textContent = String(cur.length);
    $("kpi-prev-count").textContent = `Kỳ trước: ${prev.length} hóa đơn`;

    const byDay = {};
    cur.forEach((r) => { byDay[r.date] = (byDay[r.date] || 0) + (Number(r.total) || 0); });
    let peakDay = "—";
    let peakAmt = 0;
    Object.entries(byDay).forEach(([d, a]) => { if (a > peakAmt) { peakAmt = a; peakDay = formatDateVi(d); } });
    $("kpi-peak-day-amt").textContent = formatVnd(peakAmt);
    $("kpi-peak-day-date").textContent = peakDay;

    const byCat = {};
    const prevCat = {};
    cur.forEach((r) => { byCat[r.category] = (byCat[r.category] || 0) + (Number(r.total) || 0); });
    prev.forEach((r) => { prevCat[r.category] = (prevCat[r.category] || 0) + (Number(r.total) || 0); });

    const barsBox = $("analytics-bars");
    barsBox.innerHTML = "";
    if (!cur.length) {
      barsBox.innerHTML = `<p class="empty-box">Chưa có dữ liệu trong kỳ này.</p>`;
    } else {
      Object.entries(byCat)
        .sort((a, b) => b[1] - a[1])
        .forEach(([cat, amt]) => {
          const share = curSum > 0 ? Math.round((amt / curSum) * 100) : 0;
          const row = document.createElement("div");
          row.className = "cat-row";
          row.innerHTML = `
            <div class="cat-row-top"><span>${cat}</span><span>${formatVnd(amt)} (${share}%)</span></div>
            <div class="cat-bar-bg"><div class="cat-bar-fill" style="width:${share}%"></div></div>
          `;
          barsBox.appendChild(row);
        });
    }

    // SVG Comparison Chart
    const cats = Array.from(new Set([...Object.keys(byCat), ...Object.keys(prevCat)])).slice(0, 5);
    const maxVal = Math.max(1, ...cats.map((c) => Math.max(byCat[c] || 0, prevCat[c] || 0)));
    const svgW = 320;
    const svgH = 150;
    const colW = cats.length ? svgW / cats.length : svgW;

    const barsSvg = cats
      .map((c, idx) => {
        const h1 = Math.round(((byCat[c] || 0) / maxVal) * 95);
        const h2 = Math.round(((prevCat[c] || 0) / maxVal) * 95);
        const x = idx * colW + colW * 0.2;
        return `
          <rect x="${x}" y="${115 - h1}" width="14" height="${h1}" rx="3" fill="#0284c7"/>
          <rect x="${x + 17}" y="${115 - h2}" width="14" height="${h2}" rx="3" fill="#bae6fd"/>
          <text x="${x + 15}" y="136" text-anchor="middle" font-size="9" fill="#64748b">${escapeXml(c.slice(0, 7))}</text>
        `;
      })
      .join("");

    $("analytics-svg-wrap").innerHTML = cats.length
      ? `<svg viewBox="0 0 ${svgW} ${svgH}" width="100%" height="${svgH}">${barsSvg}</svg>`
      : `<p class="empty-box">Chưa có dữ liệu để vẽ biểu đồ.</p>`;
  }

  function shiftPeriod(delta) {
    const [y, m, d] = state.analyticsAnchor.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    if (state.analyticsPeriod === "week") dt.setDate(dt.getDate() + delta * 7);
    else if (state.analyticsPeriod === "year") dt.setFullYear(dt.getFullYear() + delta);
    else dt.setMonth(dt.getMonth() + delta);
    state.analyticsAnchor = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
    renderAnalytics();
  }

  // =========================================================================
  // Demo Scenarios (Inspector Rail) & Reset
  // =========================================================================
  async function runScenario(type) {
    if (type === "duplicate") {
      if (!state.lastSubmittedCaptureId) {
        showToast("Hãy chốt 1 hóa đơn trước để thử trùng mã lượt chụp!");
        return;
      }
      state.activeCaptureId = state.lastSubmittedCaptureId;
      state.currentImageDataUrl = generateSampleReceiptImage("clear");
      state.currentDraft = {
        capture_id: state.activeCaptureId,
        merchant: "Highlands Coffee",
        date: state.todayIso,
        date_source: "Từ hóa đơn",
        category: "Ăn uống",
        total: 64000,
        items: [{ name: "Phin Sữa Đá", price: 64000 }],
      };
      confirmChot();
      return;
    }

    openCaptureSheet(state.todayIso);
    setCapturedImage(generateSampleReceiptImage(type));
    await runOcrAndCreateDraft(type);
  }

  async function resetDemoData() {
    state.confirmedCaptures.clear();
    state.lastSubmittedCaptureId = "";
    if (state.backendOnline) {
      try {
        const res = await fetch("/api/receipts/reset-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data.receipts)) state.receipts = data.receipts;
        }
      } catch (_) {}
    } else {
      state.receipts = SEED_RECEIPTS.map((r) => ({ ...r }));
    }
    saveLocalCache();
    renderCalendar();
    renderAnalytics();
    showToast("Đã khôi phục dữ liệu mẫu");
    refreshInsights();
  }

  // =========================================================================
  // Event Binding & Init
  // =========================================================================
  function bindEvents() {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchScreen(btn.dataset.screen));
    });

    $("btn-prev-month").addEventListener("click", () => {
      state.calMonth -= 1;
      if (state.calMonth < 1) { state.calMonth = 12; state.calYear -= 1; }
      renderCalendar();
    });
    $("btn-next-month").addEventListener("click", () => {
      state.calMonth += 1;
      if (state.calMonth > 12) { state.calMonth = 1; state.calYear += 1; }
      renderCalendar();
    });
    $("btn-jump-today").addEventListener("click", () => {
      const [y, m] = state.todayIso.split("-").map(Number);
      state.calYear = y;
      state.calMonth = m;
      state.selectedDate = state.todayIso;
      renderCalendar();
    });

    $("btn-toggle-day-items").addEventListener("click", () => {
      state.dayExpanded = !state.dayExpanded;
      renderDayDetail();
    });
    $("btn-add-empty-day").addEventListener("click", () => openCaptureSheet(state.selectedDate));
    $("btn-open-camera").addEventListener("click", () => openCaptureSheet(state.selectedDate || state.todayIso));
    $("btn-close-sheet").addEventListener("click", closeCaptureSheet);

    $("btn-toggle-cam").addEventListener("click", toggleCamera);
    $("btn-shutter").addEventListener("click", takePhoto);
    $("upload-file-input").addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => setCapturedImage(reader.result);
      reader.readAsDataURL(file);
      e.target.value = ""; // cho phép chọn lại đúng ảnh cũ (ca chụp trùng)
    });

    $("btn-sample-clear").addEventListener("click", () => setCapturedImage(generateSampleReceiptImage("clear")));
    $("btn-sample-blurry").addEventListener("click", async () => {
      setCapturedImage(generateSampleReceiptImage("blurry"));
      await runOcrAndCreateDraft("blurry");
    });
    $("btn-sample-nodate").addEventListener("click", async () => {
      setCapturedImage(generateSampleReceiptImage("nodate"));
      await runOcrAndCreateDraft("nodate");
    });

    $("btn-run-ocr").addEventListener("click", () => runOcrAndCreateDraft("auto"));
    $("btn-retake-reread").addEventListener("click", () => showSheetStep("camera"));
    $("btn-manual-reread").addEventListener("click", openManualDraft);
    $("budget-form").addEventListener("submit", saveBudget);
    $("savings-form").addEventListener("submit", saveSavings);
    $("btn-ai-insight").addEventListener("click", runAiInsight);
    $("insight-banner").addEventListener("click", () => switchScreen("analytics"));
    $("btn-retake-from-draft").addEventListener("click", () => showSheetStep("camera"));
    $("btn-discard-draft").addEventListener("click", closeCaptureSheet);
    $("step-draft").addEventListener("submit", confirmChot);

    $("btn-close-photo-modal").addEventListener("click", () => $("photo-modal").classList.add("hidden"));

    document.querySelectorAll(".seg-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".seg-tab").forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        state.analyticsPeriod = tab.dataset.period;
        renderAnalytics();
      });
    });
    $("btn-period-prev").addEventListener("click", () => shiftPeriod(-1));
    $("btn-period-next").addEventListener("click", () => shiftPeriod(1));

    document.querySelectorAll(".guide-trigger").forEach((btn) => {
      btn.addEventListener("click", () => switchScreen("guide"));
    });
    $("btn-guide-back").addEventListener("click", () => switchScreen("calendar"));

    document.querySelectorAll(".scenario-btn").forEach((btn) => {
      btn.addEventListener("click", () => runScenario(btn.dataset.scenario));
    });
    $("btn-toggle-phone-theme").addEventListener("click", () => {
      const screen = $("phone-screen");
      screen.dataset.theme = screen.dataset.theme === "dark" ? "light" : "dark";
    });
    $("btn-reset-demo").addEventListener("click", resetDemoData);
    $("btn-mobile-reset-demo").addEventListener("click", resetDemoData);
  }

  async function init() {
    updateClock();
    setInterval(updateClock, 30000);
    const [y, m] = state.todayIso.split("-").map(Number);
    state.calYear = y;
    state.calMonth = m;
    state.selectedDate = state.todayIso;
    state.analyticsAnchor = state.todayIso;

    bindEvents();
    await initBackend();
    renderCalendar();
    refreshInsights({ notify: true });
  }

  init();
})();
