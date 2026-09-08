/*
 * Three tabs: the rate dashboard, the macro series form, and what has run.
 *
 * Nothing technical reaches this file, because nothing technical is sent to
 * it. There is no log to display and no place to display one.
 *
 * The one thing that does arrive while a run is in flight is the trace: the
 * domains being tried, what each answered, what it scored, whether it was
 * kept. That is not a log -- it is the working behind a verdict the page is
 * about to deliver, written as sentences, and a customer told "we checked the
 * sources" without it is being asked to take that on trust.
 *
 * It comes over EventSource so the lines land when they happen rather than on
 * the poll's one-second grid. The poll carries the same events as a fallback,
 * which is why every event has an index: whichever channel delivers it, the
 * page renders each line exactly once.
 */

const $ = (id) => document.getElementById(id);

const POLL_MS = 1000;
const NUMBER = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 2 });
// Rates are quoted to two places even when the second is a zero: "6,2%"
// beside "5,77%" reads as a different precision rather than the same one.
const RATE = new Intl.NumberFormat("vi-VN",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });

let timer = null;
let refreshTimer = null;
let dash = null;          // the dashboard payload currently on screen
let stream = null;        // EventSource for the running job's trace
let traceSeen = 0;        // how many trace events have been drawn

/* ---------------------------------------------------------------- tabs --- */

const PANELS = { rates: "panel-rates", macro: "panel-macro", updates: "panel-updates" };

function showTab(name) {
  for (const [key, panel] of Object.entries(PANELS)) {
    $(panel).hidden = key !== name;
    $("tab-" + key).setAttribute("aria-selected", String(key === name));
  }
  if (name === "updates") loadUpdates();
}

for (const key of Object.keys(PANELS)) {
  $("tab-" + key).addEventListener("click", () => showTab(key));
}

/* ------------------------------------------------------------ dashboard --- */

function fmtRate(value) {
  return value === null || value === undefined ? "—" : RATE.format(value) + "%";
}

function fmtWhen(iso) {
  // Trim first, then substitute: replacing "T" lengthens the string, and
  // slicing afterwards cut "14:53" down to "1".
  return iso ? iso.slice(0, 16).replace("T", " lúc ") : "";
}

async function loadDashboard(banks) {
  const query = new URLSearchParams();
  if (banks && banks.length) query.set("banks", banks.join(","));
  let data;
  try {
    data = await (await fetch("/api/dashboard?" + query)).json();
  } catch (error) {
    return;
  }

  if (!data.ready) {
    $("dash-meta").textContent = "";
    $("dash-notice").innerHTML =
      `<p class="caveat">${escapeHtml(data.message || "Chưa có số liệu.")}</p>`;
    $("dash-notice").hidden = false;
    return;
  }

  dash = data;
  $("dash-notice").hidden = true;
  $("dash-title").textContent = `Lãi suất tiết kiệm kỳ hạn ${data.tenor} tháng`;
  $("dash-meta").textContent =
    `Cập nhật ${fmtWhen(data.captured_at)} · ${data.rows.length} ngân hàng · ` +
    `${data.updates} lần cập nhật đã lưu`;

  renderKpis(data);
  renderCrosscheck(data.crosscheck);
  renderPicker(data);
  renderTrend(data);
  renderTable(data);
}

function renderKpis(data) {
  const k = data.kpis;
  // Three, and only three. A fourth number at the top of a dashboard competes
  // with the answer rather than adding to it.
  const cards = [
    {
      label: `Cao nhất kỳ hạn ${data.tenor} tháng`,
      value: fmtRate(k.top_rate),
      note: k.top_bank,
      tone: "good",
    },
    {
      label: "Trung bình thị trường",
      value: fmtRate(k.average),
      note: `${data.rows.length} ngân hàng đang theo dõi`,
    },
    k.change === null || k.change === undefined
      ? { label: "So với lần cập nhật trước", value: "—",
          note: "Cần thêm một lần cập nhật nữa để so sánh" }
      : { label: "So với lần cập nhật trước",
          value: (k.change > 0 ? "+" : "") + RATE.format(k.change) + " điểm",
          note: Math.abs(k.change) < 0.005 ? "Mặt bằng chung không đổi"
                : k.change > 0 ? "Mặt bằng chung nhích lên" : "Mặt bằng chung hạ xuống",
          tone: Math.abs(k.change) < 0.005 ? "" : k.change > 0 ? "good" : "bad" },
  ];

  $("kpis").innerHTML = cards.map((card) => `
    <div class="kpi">
      <p class="kpi__label">${escapeHtml(card.label)}</p>
      <p class="kpi__value ${card.tone || ""}">${escapeHtml(card.value)}</p>
      <p class="kpi__note">${escapeHtml(card.note || "")}</p>
    </div>`).join("");
}

function renderCrosscheck(check) {
  if (!check || !check.checked || check.agrees) return;   // silence when as expected
  $("dash-notice").innerHTML =
    `<p class="caveat caveat--warn">Số liệu tổng hợp đang lệch so với công bố của
     BIDV ở kỳ hạn ${escapeHtml(check.mismatched.join(", "))} tháng. Bạn nên kiểm
     tra lại tại ngân hàng trước khi dựa vào con số này.</p>`;
  $("dash-notice").hidden = false;
}

function renderPicker(data) {
  $("bank-picker").innerHTML = data.banks_available.map((bank) => {
    const on = data.banks_selected.includes(bank);
    return `<button type="button" class="pill${on ? " pill--on" : ""}"
      data-bank="${escapeHtml(bank)}" aria-pressed="${on}">${escapeHtml(bank)}</button>`;
  }).join("");

  document.querySelectorAll("#bank-picker .pill").forEach((pill) =>
    pill.addEventListener("click", () => {
      const chosen = new Set(dash.banks_selected);
      const bank = pill.dataset.bank;
      if (chosen.has(bank)) chosen.delete(bank);
      // Three is the number of line colours that stay apart from one another.
      else if (chosen.size < 3) chosen.add(bank);
      else return;
      loadDashboard([...chosen]);
    })
  );
}

function renderTrend(data) {
  $("trend-caption").textContent = `Diễn biến lãi suất kỳ hạn ${data.tenor} tháng`;
  $("trend-insight").textContent = data.insight || "";

  if (data.chart) {
    $("trend-chart").src = data.chart;
    $("trend-chart").alt = `Biểu đồ lãi suất kỳ hạn ${data.tenor} tháng`;
    $("trend-figure").hidden = false;
    $("trend-empty").hidden = true;
  } else {
    $("trend-figure").hidden = true;
    $("trend-empty").hidden = false;
    // Not an error, and not hidden either: a single capture is one point, and
    // a line through one point would read as "the rate held steady".
    $("trend-empty").textContent = data.updates < 2
      ? "Chưa vẽ được đường xu hướng: mới có một lần cập nhật. Không nguồn nào " +
        "công bố lãi suất của quá khứ, nên biểu đồ được dựng dần từ các lần cập " +
        "nhật kế tiếp — bấm Cập nhật số liệu vào những ngày sau để đường này hiện ra."
      : "Chưa đủ dữ liệu cho các ngân hàng đang chọn.";
  }
}

function renderTable(data) {
  if (!$("sort-tenor").options.length) {
    $("sort-tenor").innerHTML = data.tenors.map((t) =>
      `<option value="${t}"${t === data.tenor ? " selected" : ""}>${t} tháng</option>`
    ).join("");
    $("sort-tenor").addEventListener("change", () => renderTable(dash));
    $("only-big4").addEventListener("change", () => renderTable(dash));
  }

  const onlyBig4 = $("only-big4").checked;
  const sortTenor = $("sort-tenor").value || String(data.tenor);

  const rows = data.rows
    .filter((row) => !onlyBig4 || row.big_four)
    .slice()
    .sort((a, b) => (b.rates[sortTenor] ?? -1) - (a.rates[sortTenor] ?? -1));

  const head = `<thead><tr><th>Ngân hàng</th>` +
    data.tenors.map((t) => `<th class="num">${t} tháng</th>`).join("") +
    `</tr></thead>`;

  const body = rows.map((row) => {
    const cells = data.tenors.map((t) => {
      const value = row.rates[String(t)];
      // Colour marks a state -- best or worst at this tenor, across banks --
      // and nothing else. Comparing down a column is the question a rate
      // comparison exists to answer.
      let tone = "";
      if (value !== null && value !== undefined) {
        if (data.highest[String(t)] === row.bank) tone = " cell--best";
        else if (data.lowest[String(t)] === row.bank) tone = " cell--worst";
      }
      return `<td class="num${tone}">${escapeHtml(fmtRate(value))}</td>`;
    }).join("");
    return `<tr><th scope="row">${escapeHtml(row.bank)}${
      row.big_four ? '<span class="tag">Big4</span>' : ""}</th>${cells}</tr>`;
  }).join("");

  $("rate-table").innerHTML = head + "<tbody>" + body + "</tbody>";

  $("missing-banks").textContent = data.banks_missing && data.banks_missing.length
    ? "Chưa theo dõi được: " + data.banks_missing.join(", ") +
      " — các ngân hàng này không công bố bảng lãi suất ở dạng đọc được tự động."
    : "";
}

/* --------------------------------------------------------------- refresh --- */

$("refresh").addEventListener("click", async () => {
  const button = $("refresh");
  button.disabled = true;
  button.textContent = "Đang cập nhật…";
  $("refresh-phase").hidden = false;
  $("refresh-phase").textContent = "Đang chuẩn bị…";

  try {
    const { id } = await (await fetch("/api/refresh", { method: "POST" })).json();
    refreshTimer = setInterval(() => pollRefresh(id), POLL_MS);
  } catch (error) {
    endRefresh("Không bắt đầu được. Bạn thử lại sau ít phút.");
  }
});

async function pollRefresh(id) {
  let job;
  try {
    job = await (await fetch(`/api/run/${id}`)).json();
  } catch (error) {
    return;
  }
  $("refresh-phase").textContent = job.phase || "Đang xử lý…";
  if (job.status === "running") return;

  if (job.status === "done") {
    endRefresh("");
    loadDashboard();
  } else {
    endRefresh(job.message || "Không lấy được bảng lãi suất.");
  }
}

function endRefresh(message) {
  clearInterval(refreshTimer);
  const button = $("refresh");
  button.disabled = false;
  button.textContent = "Cập nhật số liệu";
  if (message) $("refresh-phase").textContent = message;
  else $("refresh-phase").hidden = true;
}

/* --------------------------------------------------------------- updates --- */

async function loadUpdates() {
  try {
    const data = await (await fetch("/api/updates")).json();
    const rows = data.updates || [];
    $("updates-empty").hidden = rows.length > 0;
    $("updates-body").innerHTML = rows.map((row) => `
      <tr>
        <td class="num">${escapeHtml(fmtWhen(row.at))}</td>
        <td class="num">${row.banks}</td>
        <td class="num">${row.quotes}</td>
        <td>${escapeHtml(row.source)}</td>
        <td>${row.checked
          ? `<span class="badge badge--${row.agrees ? "used" : "failed"}">${
              row.agrees ? "Khớp với BIDV" : "Lệch với BIDV"}</span>`
          : '<span class="badge badge--unused">Chưa đối chiếu</span>'}</td>
      </tr>`).join("");
  } catch (error) { /* leave the previous listing in place */ }

  try {
    const data = await (await fetch("/api/history")).json();
    const runs = data.runs || [];
    $("history-empty").hidden = runs.length > 0;
    $("history-body").innerHTML = runs.map((run) => {
      const done = run.outcome === "done";
      return `<tr>
        <td class="num">${escapeHtml(run.at.replace("T", " ").slice(0, 16))}</td>
        <td>${escapeHtml(run.topic)}</td>
        <td class="num">${escapeHtml(run.window)}</td>
        <td class="num">${run.sources_passed}/${run.sources_total}</td>
        <td><span class="badge badge--${done ? "used" : "unused"}">${
          done ? "Có kết quả" : "Không đủ tin cậy"}</span>
          <span class="sub">${escapeHtml(run.summary || "")}</span></td>
      </tr>`;
    }).join("");
  } catch (error) { /* same */ }
}

/* ----------------------------------------------------------- macro form --- */

function iso(date) { return date.toISOString().slice(0, 10); }

function setRange(days) {
  const end = new Date();
  $("start").value = iso(new Date(end.getTime() - days * 86400000));
  $("end").value = iso(end);
  document.querySelectorAll(".chip").forEach((chip) =>
    chip.setAttribute("aria-pressed", String(Number(chip.dataset.days) === days)));
}

document.querySelectorAll(".chip").forEach((chip) =>
  chip.addEventListener("click", () => setRange(Number(chip.dataset.days))));

setRange(1825);
$("end").max = iso(new Date());

/* --------------------------------------------------------------- trace --- */

// Older lines stop being interesting once a run is deep into a pool, and an
// unbounded list is a page that gets slower the longer the customer waits.
const TRACE_MAX_ROWS = 200;

function resetTrace() {
  traceSeen = 0;
  $("trace").innerHTML = "";
}

function drawTrace(events) {
  const list = $("trace");
  // Only follow the newest line while the reader is already at the bottom.
  // Yanking the list back down under someone who scrolled up to read a
  // rejected source is the worst moment to do it.
  const following = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
  let drawn = 0;

  for (const event of events || []) {
    if (typeof event.i === "number" && event.i < traceSeen) continue;
    traceSeen = typeof event.i === "number" ? event.i + 1 : traceSeen + 1;

    const row = document.createElement("li");
    row.className = "is-" + (event.kind || "detail");
    const score = event.score === null || event.score === undefined
      ? "" : `<span class="trace__score">${event.score}/100</span>`;
    row.innerHTML =
      `<span class="trace__at">${formatSeconds(event.seconds)}</span>` +
      `<span class="trace__text">${escapeHtml(event.text || "")}</span>` + score;
    list.appendChild(row);
    drawn += 1;
  }

  while (list.childElementCount > TRACE_MAX_ROWS) list.removeChild(list.firstChild);
  if (drawn && following) list.scrollTop = list.scrollHeight;
}

function formatSeconds(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:` +
         `${String(total % 60).padStart(2, "0")}`;
}

function openStream(id) {
  closeStream();
  if (!window.EventSource) return;      // the poll still carries the events
  stream = new EventSource(`/api/run/${id}/events`);
  stream.onmessage = (message) => {
    try { drawTrace([JSON.parse(message.data)]); } catch (error) { /* ignore */ }
  };
  // The server closes the stream when the run ends; without this the browser
  // would reconnect to a finished job every few seconds.
  stream.addEventListener("end", closeStream);
}

function closeStream() {
  if (stream) { stream.close(); stream = null; }
}

$("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("submit");
  button.disabled = true;
  button.textContent = "Đang chạy…";
  $("notice").hidden = true;
  $("result").hidden = true;
  $("caveats").hidden = true;
  $("progress").hidden = false;
  $("phase").textContent = "Đang chuẩn bị…";
  $("progress").classList.remove("progress--done");
  resetTrace();

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic: $("topic").value.trim(),
        notes: $("notes").value.trim(),
        compare: $("compare").value,
        start: $("start").value,
        end: $("end").value,
      }),
    });
    const body = await response.json();
    if (!response.ok) {
      const detail = typeof body.detail === "string"
        ? body.detail : "Thông tin nhập vào chưa hợp lệ.";
      throw new Error(detail);
    }
    openStream(body.id);
    timer = setInterval(() => poll(body.id), POLL_MS);
    poll(body.id);
  } catch (error) {
    stopRun();
    notice("Chưa thể bắt đầu", String(error.message || error));
  }
});

async function poll(id) {
  let job;
  try {
    job = await (await fetch(`/api/run/${id}?since=${traceSeen}`)).json();
  } catch (error) { return; }

  $("phase").textContent = job.phase || "Đang xử lý…";
  // Drawn by index, so this is a no-op whenever the stream is keeping up and
  // the whole trace whenever it never connected.
  drawTrace(job.events);
  if (job.status === "running") return;

  stopRun();
  if (job.status === "done") render(job.result);
  else notice("Chưa thể đưa ra kết quả", job.message, job.result);
}

function stopRun() {
  clearInterval(timer);
  closeStream();
  // The trace stays. It is the working behind the verdict directly below it,
  // and a refusal is exactly the case where a customer wants to read back
  // which sources were tried before being told there is no chart -- hiding it
  // the moment the run ends would take that away at the moment it matters.
  $("progress").classList.add("progress--done");
  $("progress").hidden = $("trace").childElementCount === 0;
  $("phase").textContent = `Đã xong · ${$("trace").childElementCount} bước`;
  $("submit").disabled = false;
  $("submit").textContent = "Chạy phân tích";
}

function notice(title, text, partial) {
  $("notice-title").textContent = title;
  $("notice-text").textContent = text || "Không có thông tin chi tiết.";
  $("notice").hidden = false;
  renderCaveats(partial && partial.caveats);
  if (partial && partial.sources && partial.sources.length) {
    $("result-title").textContent = partial.metric || "";
    $("result-window").textContent = "Không có số liệu nào được đưa vào biểu đồ.";
    renderSources(partial.sources);
    setSections({ tiles: false, chart: false, anomalies: false });
    $("result").hidden = false;
  }
}

function setSections({ tiles, chart, anomalies }) {
  $("tiles-card").hidden = !tiles;
  $("chart-card").hidden = !chart;
  $("anomaly-card").hidden = !anomalies;
}

function render(data) {
  const summary = data.summary;
  const unit = data.unit ? " " + data.unit : "";

  $("result-title").textContent = data.metric;
  $("result-window").textContent =
    `${data.window.start} – ${data.window.end} · ${data.window.points} mốc dữ liệu`;

  setSections({ tiles: true, chart: true, anomalies: true });
  renderCaveats(data.caveats);
  renderSources(data.sources);
  renderTiles(summary, unit);

  $("chart-caption").textContent = data.chart.caption;
  $("chart-explain").textContent =
    "Những cột hoặc điểm tô đỏ là các mốc biến động khác thường so với phần còn lại của kỳ.";
  $("chart").src = data.chart.url + "?t=" + Date.now();
  $("chart").alt = `Biểu đồ ${data.metric}`;
  $("insight").textContent = data.chart.insight;

  renderAnomalies(data.anomalies, data.anomaly_total, unit);
  $("result").hidden = false;
}

function renderCaveats(caveats) {
  const box = $("caveats");
  if (!caveats || !caveats.length) { box.hidden = true; return; }
  box.innerHTML = caveats.map((t) => `<p class="caveat">${escapeHtml(t)}</p>`).join("");
  box.hidden = false;
}

function signed(value, unit) {
  const number = (value > 0 ? "+" : "") + NUMBER.format(value);
  return unit === "%" ? { number: number + "%", unit: "" } : { number, unit };
}

function renderSources(sources) {
  $("sources").innerHTML = sources.map((source) => {
    if (source.failed) {
      return `<li class="source source--unused">
        <span class="source__name">${escapeHtml(source.label)}</span>
        <span class="source__tier">Không lấy được số liệu trong lần chạy này.</span>
        <span class="badge badge--failed">Không dùng</span></li>`;
    }
    const used = source.accepted;
    const note = source.corroborated
      ? "Có nguồn khác đưa ra cùng con số."
      : "Chưa có nguồn độc lập nào xác nhận lại.";
    return `<li class="source source--${used ? "used" : "unused"}">
      <span class="source__name">${escapeHtml(source.label)}</span>
      <span class="source__tier">${escapeHtml(source.tier)}. ${note}</span>
      <span class="badge badge--score">${source.score}/100</span>
      <span class="badge badge--${used ? "used" : "unused"}">${
        used ? "Đã dùng" : "Không dùng"}</span></li>`;
  }).join("");
}

function renderTiles(summary, unit) {
  const trimmed = (unit || "").trim();
  const tiles = [
    { label: "Đầu kỳ", number: NUMBER.format(summary.first), unit: trimmed,
      note: "Giá trị ở mốc đầu tiên có số liệu." },
    { label: "Cuối kỳ", number: NUMBER.format(summary.last), unit: trimmed,
      note: "Giá trị ở mốc gần nhất có số liệu." },
    { label: "Thay đổi cả kỳ", ...signed(summary.change, summary.change_unit),
      note: `Mức ${summary.direction} tính từ đầu kỳ đến cuối kỳ.`,
      tone: summary.change > 0 ? "up" : summary.change < 0 ? "down" : "" },
    { label: "Thấp nhất – cao nhất",
      number: NUMBER.format(summary.minimum) + " – " + NUMBER.format(summary.maximum),
      unit: trimmed, note: "Khoảng dao động trong toàn bộ kỳ quan sát." },
  ];
  if (summary.period_change !== null && summary.period_change !== undefined) {
    tiles.push({ label: "So với kỳ trước",
      ...signed(summary.period_change, summary.period_unit),
      note: summary.period_label + ", tính theo giá trị trung bình.",
      tone: summary.period_change > 0 ? "up" : "down" });
  }

  $("tiles").innerHTML = tiles.map((tile) => `
    <div class="tile">
      <p class="tile__label">${escapeHtml(tile.label)}</p>
      <p class="tile__value ${tile.tone || ""}">${escapeHtml(tile.number)}${
        tile.unit ? `<span class="tile__unit">${escapeHtml(tile.unit)}</span>` : ""}</p>
      <p class="tile__note">${escapeHtml(tile.note)}</p>
    </div>`).join("");
}

function renderAnomalies(anomalies, total, unit) {
  const card = $("anomaly-card");
  if (!anomalies || !anomalies.length) { card.hidden = true; return; }
  card.hidden = false;
  const extra = total > anomalies.length
    ? `<li class="anomaly__note">Còn ${total - anomalies.length} mốc khác đã đánh dấu trên biểu đồ.</li>`
    : "";
  $("anomalies").innerHTML = anomalies.map((item) => `
    <li class="anomaly">
      <span class="anomaly__date">${escapeHtml(item.date)}</span>
      <span class="anomaly__move">${item.direction} ${escapeHtml(
        NUMBER.format(Math.abs(item.change)) +
        (item.change_unit === "%" ? "%" : " " + item.change_unit))}</span>
      <span class="anomaly__note">so với mốc liền trước, về mức ${
        escapeHtml(NUMBER.format(item.value) + unit)}</span>
    </li>`).join("") + extra;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

loadDashboard();

/* ------------------------------------------------- structured rate query --- */
/*
 * The rate question is selected, not typed. Four things vary -- which banks,
 * which tenors, compared how, over which two periods -- and every one of them
 * is a thing a person can point at, so there is nothing here for a planner to
 * interpret and nothing for a model to get wrong. The options themselves come
 * from the server rather than being written into this file: a chip for a bank
 * the board has never carried is a choice that can only end in an empty table.
 */

// What the second dropdown says once the first one has been chosen. The
// comparison period is not a free choice for a preset -- "tháng này" is
// compared with "tháng trước" and nothing else -- so it is shown, locked,
// rather than left as a control that appears to do something it does not.
const PREVIOUS_LABELS = {
  week: "Tuần trước", month: "Tháng trước", year: "Năm ngoái",
  custom: "Khoảng tự chọn",
};

const MODE_TITLES = {
  banks: "So sánh giữa các ngân hàng",
  time: "So sánh theo thời gian",
  both: "So sánh giữa các ngân hàng và theo thời gian",
};

let rateOptions = null;

async function loadRateOptions() {
  try {
    rateOptions = await (await fetch("/api/rates/options")).json();
  } catch (error) { return; }

  if (!rateOptions.banks.length) {
    $("rate-help").textContent =
      "Chưa có lần cập nhật nào. Bấm Cập nhật số liệu trước khi so sánh.";
    $("rate-submit").disabled = true;
    return;
  }

  // The big four first, then the rest: it is the grouping a saver already has
  // in their head, and the dashboard's table marks it too.
  const big4 = rateOptions.big_four || [];
  const banks = [...rateOptions.banks].sort(
    (a, b) => (big4.includes(b) ? 1 : 0) - (big4.includes(a) ? 1 : 0));

  $("pick-banks").innerHTML = banks.map((bank, index) => `
    <label class="chip-check">
      <input type="checkbox" name="bank" value="${escapeHtml(bank)}"${
        index < 3 ? " checked" : ""}>
      <span>${escapeHtml(bank)}</span>
    </label>`).join("");

  $("pick-tenors").innerHTML = rateOptions.tenors.map((tenor) => `
    <label class="chip-check">
      <input type="checkbox" name="tenor" value="${tenor}"${
        tenor === 12 ? " checked" : ""}>
      <span>${tenor} tháng</span>
    </label>`).join("");

  $("rate-help").textContent = `${rateOptions.updates} lần cập nhật đã lưu, ` +
    `từ ${rateOptions.first} đến ${rateOptions.last}.`;
  syncPeriodControls();
}

function checkedValues(name) {
  return [...document.querySelectorAll(`#rate-form input[name="${name}"]:checked`)]
    .map((input) => input.value);
}

function currentMode() {
  const picked = document.querySelector('#rate-form input[name="mode"]:checked');
  return picked ? picked.value : "banks";
}

function syncPeriodControls() {
  // The period block only means something when a period is being compared, so
  // for "giữa ngân hàng" it is absent rather than present and ignored.
  $("period-fields").hidden = currentMode() === "banks";

  const preset = $("preset-current").value;
  $("preset-previous").innerHTML =
    `<option>${escapeHtml(PREVIOUS_LABELS[preset] || "")}</option>`;

  const custom = preset === "custom";
  $("custom-current").hidden = !custom;
  $("custom-previous").hidden = !custom;
  if (custom && !$("cur-end").value) seedCustomRange();
}

function seedCustomRange() {
  // Two adjacent weeks ending today: a starting point that is already a valid
  // comparison, so the picker opens on something rather than on four blanks.
  const day = 86400000;
  const today = new Date();
  $("cur-end").value = iso(today);
  $("cur-start").value = iso(new Date(today.getTime() - 6 * day));
  $("prev-end").value = iso(new Date(today.getTime() - 7 * day));
  $("prev-start").value = iso(new Date(today.getTime() - 13 * day));
}

document.querySelectorAll('#rate-form input[name="mode"]').forEach((radio) =>
  radio.addEventListener("change", syncPeriodControls));
$("preset-current").addEventListener("change", syncPeriodControls);

$("rate-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const banks = checkedValues("bank");
  const tenors = checkedValues("tenor").map(Number);
  if (!banks.length || !tenors.length) {
    $("rate-help").textContent = "Chọn ít nhất một ngân hàng và một kỳ hạn.";
    return;
  }

  const mode = currentMode();
  const preset = mode === "banks" ? "month" : $("preset-current").value;
  const body = { banks, tenors, mode, preset, board: "counter" };
  if (preset === "custom") {
    body.current_start = $("cur-start").value;
    body.current_end = $("cur-end").value;
    body.previous_start = $("prev-start").value;
    body.previous_end = $("prev-end").value;
  }

  const button = $("rate-submit");
  button.disabled = true;
  button.textContent = "Đang so sánh…";
  try {
    const response = await fetch("/api/rates/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(typeof data.detail === "string"
        ? data.detail : "Lựa chọn chưa hợp lệ.");
    }
    if (!data.ok) throw new Error(data.message || "Chưa có số liệu để so sánh.");
    renderRateAnswer(data);
  } catch (error) {
    $("rate-result").hidden = true;
    $("rate-help").textContent = String(error.message || error);
  } finally {
    button.disabled = false;
    button.textContent = "So sánh";
  }
});

function renderRateAnswer(data) {
  $("rq-title").textContent = MODE_TITLES[data.mode] || "Kết quả so sánh";
  $("rq-period").textContent = data.period.label
    ? `${data.period.label} · ${data.period.current} so với ${data.period.previous}`
    : `Cập nhật ${fmtWhen(data.captured_at)}`;

  $("rq-caveats").innerHTML = (data.caveats || [])
    .map((line) => `<p class="caveat">${escapeHtml(line)}</p>`).join("");

  $("rq-insights").innerHTML = (data.insights || [])
    .map((line) => `<li>${escapeHtml(line)}</li>`).join("")
    || "<li>Chưa có nhận định nào cho lựa chọn này.</li>";

  renderRateTable(data);
  renderRateCharts(data);
  $("rate-result").hidden = false;
  $("rate-result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderRateTable(data) {
  const showsChange = data.mode !== "banks";
  $("rq-table-note").textContent = showsChange
    ? "Mỗi ô: mức hiện tại và thay đổi so với kỳ so sánh."
    : "Mức lãi suất tại lần cập nhật mới nhất.";

  const head = `<thead><tr><th>Ngân hàng</th>${
    data.tenors.map((t) => `<th>${t} tháng</th>`).join("")}</tr></thead>`;

  const body = data.rows.map((row) => {
    const cells = data.tenors.map((tenor) => {
      const cell = row.cells[String(tenor)] || {};
      if (cell.rate === null || cell.rate === undefined) {
        return `<td class="muted" title="${escapeHtml(cell.note || "")}">—</td>`;
      }
      // Same two classes the overview table uses, picked the same way: colour
      // has to mean the same thing in both places or it stops being
      // information. One or neither, never both -- concatenating them produced
      // "cell--bestcell--worst", which matches no rule and silently dropped
      // the highlight from every cell where a tenor was tied.
      let tone = "";
      if (data.highest[String(tenor)] === row.bank) tone = "cell--best";
      else if (data.lowest[String(tenor)] === row.bank) tone = "cell--worst";
      return `<td class="${tone}">${fmtRate(cell.rate)}${
        showsChange ? deltaMarkup(cell) : ""}</td>`;
    }).join("");
    return `<tr><th scope="row">${escapeHtml(row.bank)}${
      row.big_four ? '<span class="tag">Big4</span>' : ""}</th>${cells}</tr>`;
  }).join("");

  $("rq-table").innerHTML = head + `<tbody>${body}</tbody>`;
}

function deltaMarkup(cell) {
  if (cell.change === null || cell.change === undefined) {
    // The number is missing because nobody looked during that period, which is
    // a fact about the record rather than about the rate. The cell says so on
    // hover instead of a zero that would read as "it did not move".
    return `<span class="delta delta--none" title="${
      escapeHtml(cell.note || "")}">·</span>`;
  }
  if (Math.abs(cell.change) < 0.005) return '<span class="delta">—</span>';
  const up = cell.change > 0;
  return `<span class="delta ${up ? "delta--up" : "delta--down"}">${
    up ? "▲" : "▼"}${RATE.format(Math.abs(cell.change))}</span>`;
}

function renderRateCharts(data) {
  // One block per tenor, each holding the two charts that answer different
  // questions: the bar says who pays most today, the line says which way each
  // bank is moving. Neither is the other's summary.
  const blocks = [];
  for (const tenor of data.tenors) {
    const snapshot = data.charts.snapshot[String(tenor)];
    const trend = data.charts.trend[String(tenor)];
    if (!snapshot && !trend) continue;
    blocks.push(`
      <div class="chart-pair">
        <h4>Kỳ hạn ${tenor} tháng</h4>
        ${snapshot ? `<figure class="figure"><img src="${escapeHtml(snapshot)}"
           alt="Lãi suất ${tenor} tháng theo ngân hàng"></figure>` : ""}
        ${trend ? `<figure class="figure"><img src="${escapeHtml(trend)}"
           alt="Diễn biến lãi suất ${tenor} tháng"></figure>` : ""}
      </div>`);
  }
  $("rq-charts").innerHTML = blocks.join("");
  $("rq-charts-card").hidden = blocks.length === 0;
}

loadRateOptions();
