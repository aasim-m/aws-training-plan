const form = document.querySelector("#searchForm");
const instanceType = document.querySelector("#instanceType");
const durationValue = document.querySelector("#durationValue");
const durationUnit = document.querySelector("#durationUnit");
const instanceCount = document.querySelector("#instanceCount");
const maximumSegments = document.querySelector("#maximumSegments");
const segmentsWarning = document.querySelector("#segmentsWarning");
const maxLookahead = document.querySelector("#maxLookahead");
const startTimeAfter = document.querySelector("#startTimeAfter");
const timeZone = document.querySelector("#timeZone");
const skipValidation = document.querySelector("#skipValidation");
const searchButton = document.querySelector("#searchButton");
const validateButton = document.querySelector("#validateButton");
const approveNextButton = document.querySelector("#approveNextButton");
const clearResultsButton = document.querySelector("#clearResultsButton");
const exportJsonButton = document.querySelector("#exportJsonButton");
const offeringsBody = document.querySelector("#offeringsBody");
const warningsList = document.querySelector("#warningsList");
const messageArea = document.querySelector("#messageArea");
const resultTitle = document.querySelector("#resultTitle");
const resultMeta = document.querySelector("#resultMeta");
const windowStatus = document.querySelector("#windowStatus");
const regionStatus = document.querySelector("#regionStatus");
const sdkStatus = document.querySelector("#sdkStatus");
const datalist = document.querySelector("#instanceTypes");
const tableSearch = document.querySelector("#tableSearch");
const regionFilter = document.querySelector("#regionFilter");
const azFilter = document.querySelector("#azFilter");
const segmentFilter = document.querySelector("#segmentFilter");
const sortButtons = document.querySelectorAll(".sort-button");
const resetFormButton = document.querySelector("#resetFormButton");
const copyCliButton = document.querySelector("#copyCliButton");

const MAX_LOOKAHEAD_WEEKS = 52;

let approvedLookaheadWeeks = 1;
let lastResult = null;
let currentOfferings = [];
let lastPayload = null;
let searchTimer = null;
let sortState = { key: "start", direction: "desc" };

async function loadSupportedTypes() {
  try {
    const response = await fetch("/api/supported-instance-types");
    const data = await response.json();
    datalist.innerHTML = "";
    data.supported_instance_types.forEach((type) => {
      const option = document.createElement("option");
      option.value = type;
      datalist.appendChild(option);
    });
    sdkStatus.textContent = `${data.supported_instance_types.length} SDK types`;
  } catch (error) {
    sdkStatus.textContent = "SDK list unavailable";
  }
}

function selectedRegions() {
  return Array.from(document.querySelectorAll("input[name='regions']:checked")).map((item) => item.value);
}

function buildPayload() {
  const regions = selectedRegions();
  const payload = {
    instance_type: instanceType.value.trim(),
    instance_count: Number(instanceCount.value),
    maximum_segments: Number(maximumSegments.value || "1"),
    max_lookahead_weeks: MAX_LOOKAHEAD_WEEKS,
    regions,
    approved_lookahead_weeks: approvedLookaheadWeeks,
    skip_instance_type_validation: skipValidation.checked,
  };

  if (durationUnit.value === "days") {
    payload.duration_days = Number(durationValue.value);
  } else {
    payload.duration_hours = Number(durationValue.value);
  }

  if (startTimeAfter.value) {
    payload.start_time_after = localDateTimeToIso(startTimeAfter.value, timeZone.value);
  }

  return payload;
}

function setBusy(isBusy) {
  searchButton.disabled = isBusy;
  validateButton.disabled = isBusy;
  resetFormButton.disabled = isBusy;
  approveNextButton.disabled = isBusy;
}

function setMessage(text, tone = "") {
  messageArea.innerHTML = "";
  if (!text) return;
  const message = document.createElement("div");
  message.className = `message ${tone}`.trim();
  message.textContent = text;
  messageArea.appendChild(message);
}

async function runSearch({ resetApproval = false } = {}) {
  if (resetApproval) {
    approvedLookaheadWeeks = Number(maxLookahead.value || "1");
    lastResult = null;
    currentOfferings = [];
    exportJsonButton.disabled = true;
    copyCliButton.disabled = true;
    clearResultsButton.disabled = true;
    approveNextButton.classList.add("hidden");
    resetFilters();
    resultTitle.textContent = "Searching";
    resultMeta.textContent = `Clearing previous results and searching start dates through ${approvedLookaheadWeeks} week(s).`;
    renderEmpty("Searching...");
    renderWarnings([]);
  }

  setBusy(true);
  lastPayload = buildPayload();
  startSearchTimer();

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(lastPayload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Search failed");
    }
    lastResult = data;
    renderResult(data);
  } catch (error) {
    lastResult = null;
    renderError(error.message);
  } finally {
    stopSearchTimer();
    setBusy(false);
  }
}

function updateSegmentsWarning() {
  segmentsWarning.classList.toggle("hidden", Number(maximumSegments.value || "1") === 1);
}

async function validateInstanceType() {
  setBusy(true);
  setMessage("Checking instance type against AWS...");
  try {
    const regions = selectedRegions();
    const response = await fetch("/api/validate-instance-type", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        instance_type: instanceType.value.trim(),
        duration_hours: durationUnit.value === "hours" ? Number(durationValue.value) : Number(durationValue.value) * 24,
        instance_count: Number(instanceCount.value),
        region: regions[0] || "us-east-1",
      }),
    });
    const data = await response.json();
    const tone = data.valid === false ? "error" : data.valid === null ? "warn" : "";
    setMessage(data.message, tone);
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function renderResult(data) {
  const regions = data.searched_regions || [];
  const offerings = data.offerings || [];
  windowStatus.textContent = `${data.lookahead_used_weeks} week start window`;
  regionStatus.textContent = regions.length ? `${regions.length} regions` : "No regions";
  exportJsonButton.disabled = false;
  copyCliButton.disabled = false;
  clearResultsButton.disabled = false;
  currentOfferings = offerings;
  updateFilterOptions(offerings);

  if (data.found) {
    resultTitle.textContent = `${offerings.length} offering${offerings.length === 1 ? "" : "s"} found`;
    resultMeta.textContent = `${regions.length} region${regions.length === 1 ? "" : "s"} searched; start dates within ${data.lookahead_used_weeks} week(s).`;
    renderOfferings(offerings);
    if (data.approval_required && data.next_lookahead_weeks) {
      approveNextButton.classList.remove("hidden");
      approveNextButton.textContent = `Search ${data.next_lookahead_weeks} weeks`;
      approveNextButton.dataset.nextWindow = String(data.next_lookahead_weeks);
      setMessage(`Offerings found. You can also search start dates through ${data.next_lookahead_weeks} week(s).`, "success");
    } else {
      approveNextButton.classList.add("hidden");
      setMessage("");
    }
  } else {
    resultTitle.textContent = "No offerings found";
    resultMeta.textContent = `Searched ${regions.join(", ") || "no regions"}; start dates within ${data.lookahead_used_weeks} week(s).`;
    renderEmpty("No offerings in the approved start date window.");
    if (data.approval_required && data.next_lookahead_weeks) {
      approveNextButton.classList.remove("hidden");
      approveNextButton.textContent = `Search ${data.next_lookahead_weeks} weeks`;
      approveNextButton.dataset.nextWindow = String(data.next_lookahead_weeks);
      setMessage(`Approve the next start date window to continue to ${data.next_lookahead_weeks} week(s).`, "warn");
    } else {
      approveNextButton.classList.add("hidden");
      setMessage("");
    }
  }

  if (!data.approval_required) {
    approveNextButton.classList.add("hidden");
  }

  renderWarnings(data.errors || []);
}

function renderError(message) {
  resultTitle.textContent = "Search failed";
  resultMeta.textContent = "Fix the inputs and try again.";
  renderEmpty("No results.");
  renderWarnings([]);
  approveNextButton.classList.add("hidden");
  exportJsonButton.disabled = true;
  copyCliButton.disabled = true;
  clearResultsButton.disabled = true;
  currentOfferings = [];
  resetFilters();
  setMessage(message, "error");
}

function renderOfferings(offerings) {
  offeringsBody.innerHTML = "";
  if (!offerings.length) {
    renderEmpty("No offerings returned.");
    return;
  }

  const filteredOfferings = sortOfferings(filterOfferings(offerings));
  if (!filteredOfferings.length) {
    renderEmpty("No offerings match the current filters.");
    return;
  }

  filteredOfferings.forEach((offering) => {
    const capacity = offering.reserved_capacity_offerings && offering.reserved_capacity_offerings.length
      ? offering.reserved_capacity_offerings
      : [{}];
    const segmentCount = capacity.length;
    const groupId = `segments-${safeId(offering.training_plan_offering_id || Math.random().toString(36))}`;
    const summaryRow = document.createElement("tr");
    if (segmentCount > 1) summaryRow.classList.add("multi-segment-summary");
    appendCell(summaryRow, offering.region || "");
    appendCell(summaryRow, uniqueValues(capacity.map((item) => item.AvailabilityZone).filter(Boolean)).join(", "));
    appendCell(summaryRow, uniqueValues(capacity.map((item) => item.InstanceType).filter(Boolean)).join(", "));
    appendCell(summaryRow, uniqueValues(capacity.map((item) => item.InstanceCount).filter(Boolean)).join(", "));
    appendCell(summaryRow, formatDateTime(capacity[0].StartTime || offering.start_time || ""));
    appendCell(summaryRow, formatDateTime(capacity[capacity.length - 1].EndTime || offering.end_time || ""));
    appendCell(summaryRow, String(totalHours(capacity, offering)));
    appendSegmentSummaryCell(summaryRow, segmentCount, groupId);
    appendCell(summaryRow, `${offering.currency_code || ""} ${offering.upfront_fee || ""}`.trim());
    appendOfferingActionsCell(summaryRow, offering);
    offeringsBody.appendChild(summaryRow);

    if (segmentCount > 1) {
      capacity.forEach((item, index) => {
        const row = document.createElement("tr");
        row.classList.add("segment-detail-row", "hidden");
        row.dataset.groupId = groupId;
        appendCell(row, `Segment ${index + 1}`);
        appendCell(row, item.AvailabilityZone || "");
        appendCell(row, item.InstanceType || "");
        appendCell(row, String(item.InstanceCount || ""));
        appendCell(row, formatDateTime(item.StartTime || ""));
        appendCell(row, formatDateTime(item.EndTime || ""));
        appendCell(row, String(item.DurationHours || ""));
        appendSegmentCell(row, segmentCount, index);
        appendCell(row, "");
        appendCell(row, "");
        offeringsBody.appendChild(row);
      });
    }
  });
}

function appendCell(row, value, options = {}) {
  if (options.rowSpan === 0) return;
  const cell = document.createElement("td");
  cell.textContent = value;
  if (options.rowSpan && options.rowSpan > 1) {
    cell.rowSpan = options.rowSpan;
    cell.classList.add("group-cell");
  }
  if (options.className) cell.classList.add(options.className);
  if (options.title) cell.title = options.title;
  row.appendChild(cell);
}

function appendSegmentCell(row, segmentCount, index) {
  const cell = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = segmentCount > 1 ? "segment-badge multi" : "segment-badge";
  badge.textContent = segmentCount > 1 ? `${index + 1} of ${segmentCount}` : "1 segment";
  cell.appendChild(badge);
  row.appendChild(cell);
}

function appendSegmentSummaryCell(row, segmentCount, groupId) {
  const cell = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = segmentCount > 1 ? "segment-badge multi" : "segment-badge";
  badge.textContent = `${segmentCount} segment${segmentCount === 1 ? "" : "s"}`;
  cell.appendChild(badge);
  if (segmentCount > 1) {
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "inline-action segment-toggle";
    toggle.textContent = "Show";
    toggle.addEventListener("click", () => toggleSegments(groupId, toggle));
    cell.appendChild(toggle);
  }
  row.appendChild(cell);
}

function appendOfferingActionsCell(row, offering) {
  const cell = document.createElement("td");
  cell.className = "mono offering-actions-cell";
  const id = offering.training_plan_offering_id || "";
  const idText = document.createElement("span");
  idText.textContent = id;
  idText.title = id;
  cell.appendChild(idText);
  cell.appendChild(copyButton("ID", id));
  cell.appendChild(copyButton("JSON", JSON.stringify(offering, null, 2)));
  row.appendChild(cell);
}

function copyButton(label, value) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "inline-action";
  button.textContent = `Copy ${label}`;
  button.disabled = !value;
  button.addEventListener("click", () => copyText(value, `${label} copied.`));
  return button;
}

function toggleSegments(groupId, toggle) {
  const rows = Array.from(document.querySelectorAll(`tr[data-group-id="${groupId}"]`));
  const shouldShow = rows.some((row) => row.classList.contains("hidden"));
  rows.forEach((row) => row.classList.toggle("hidden", !shouldShow));
  toggle.textContent = shouldShow ? "Hide" : "Show";
}

function filterOfferings(offerings) {
  const search = tableSearch.value.trim().toLowerCase();
  const region = regionFilter.value;
  const az = azFilter.value;
  const segmentValue = segmentFilter.value;

  return offerings.filter((offering) => {
    const capacity = offering.reserved_capacity_offerings && offering.reserved_capacity_offerings.length
      ? offering.reserved_capacity_offerings
      : [{}];
    const segmentCount = capacity.length;
    const text = [
      offering.region,
      offering.training_plan_offering_id,
      offering.currency_code,
      offering.upfront_fee,
      ...capacity.flatMap((item) => [
        item.AvailabilityZone,
        item.InstanceType,
        item.InstanceCount,
        item.StartTime,
        item.EndTime,
        item.DurationHours,
      ]),
    ].join(" ").toLowerCase();

    return (!search || text.includes(search))
      && (!region || offering.region === region)
      && (!az || capacity.some((item) => item.AvailabilityZone === az))
      && (!segmentValue || segmentCount === Number(segmentValue));
  });
}

function sortOfferings(offerings) {
  const direction = sortState.direction === "asc" ? 1 : -1;
  return [...offerings].sort((left, right) => {
    const leftValue = sortValue(left, sortState.key);
    const rightValue = sortValue(right, sortState.key);
    if (leftValue < rightValue) return -1 * direction;
    if (leftValue > rightValue) return 1 * direction;
    return String(left.training_plan_offering_id || "").localeCompare(String(right.training_plan_offering_id || ""));
  });
}

function sortValue(offering, key) {
  const capacity = offering.reserved_capacity_offerings && offering.reserved_capacity_offerings.length
    ? offering.reserved_capacity_offerings
    : [{}];
  const first = capacity[0] || {};
  const values = {
    region: offering.region || "",
    az: first.AvailabilityZone || "",
    instance: first.InstanceType || "",
    count: Number(first.InstanceCount || 0),
    start: first.StartTime || offering.start_time || "",
    end: first.EndTime || offering.end_time || "",
    hours: Number(first.DurationHours || offering.duration_hours || 0),
    segments: capacity.length,
    fee: Number(offering.upfront_fee || 0),
    offering: offering.training_plan_offering_id || "",
  };
  return values[key] ?? "";
}

function updateFilterOptions(offerings) {
  setSelectOptions(regionFilter, "All regions", uniqueValues(offerings.map((offering) => offering.region).filter(Boolean)));
  setSelectOptions(
    azFilter,
    "All AZs",
    uniqueValues(offerings.flatMap((offering) => (offering.reserved_capacity_offerings || []).map((item) => item.AvailabilityZone)).filter(Boolean)),
  );
  tableSearch.disabled = false;
  regionFilter.disabled = false;
  azFilter.disabled = false;
  segmentFilter.disabled = false;
  updateSegmentFilterOptions();
}

function setSelectOptions(select, defaultLabel, values) {
  const currentValue = select.value;
  select.innerHTML = "";
  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = defaultLabel;
  select.appendChild(defaultOption);
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  select.value = values.includes(currentValue) ? currentValue : "";
}

function uniqueValues(values) {
  return Array.from(new Set(values)).sort();
}

function resetFilters() {
  tableSearch.value = "";
  regionFilter.innerHTML = '<option value="">All regions</option>';
  azFilter.innerHTML = '<option value="">All AZs</option>';
  updateSegmentFilterOptions();
  segmentFilter.value = "";
  tableSearch.disabled = true;
  regionFilter.disabled = true;
  azFilter.disabled = true;
  segmentFilter.disabled = true;
}

function updateSegmentFilterOptions() {
  const currentValue = segmentFilter.value;
  const maxSegments = Math.max(1, Number(maximumSegments.value || "1"));
  segmentFilter.innerHTML = '<option value="">All</option>';
  for (let index = 1; index <= maxSegments; index += 1) {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = `${index} segment${index === 1 ? "" : "s"}`;
    segmentFilter.appendChild(option);
  }
  segmentFilter.value = Number(currentValue) <= maxSegments ? currentValue : "";
}

function clearResults() {
  approvedLookaheadWeeks = Number(maxLookahead.value || "1");
  lastResult = null;
  currentOfferings = [];
  resultTitle.textContent = "Ready to search";
  resultMeta.textContent = "Choose inputs and search the first approved start date window.";
  windowStatus.textContent = `${approvedLookaheadWeeks} week start window`;
  regionStatus.textContent = "US regions";
  renderEmpty("No search run yet.");
  renderWarnings([]);
  setMessage("");
  approveNextButton.classList.add("hidden");
  exportJsonButton.disabled = true;
  copyCliButton.disabled = true;
  clearResultsButton.disabled = true;
  resetFilters();
}

function resetForm() {
  instanceType.value = "";
  durationValue.value = "7";
  durationUnit.value = "days";
  instanceCount.value = "1";
  maximumSegments.value = "1";
  maxLookahead.value = "1";
  startTimeAfter.value = "";
  timeZone.value = "Asia/Dubai";
  skipValidation.checked = false;
  document.querySelectorAll("input[name='regions']").forEach((item) => {
    item.checked = true;
  });
  updateSegmentsWarning();
  clearResults();
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timeZone.value,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
    timeZoneName: "short",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}:${values.second} ${values.timeZoneName}`;
}

function localDateTimeToIso(value, selectedTimeZone) {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) return new Date(value).toISOString();
  const [, year, month, day, hour, minute] = match.map(Number);
  const wallTimeAsUtc = Date.UTC(year, month - 1, day, hour, minute, 0);
  const offsetMinutes = timeZoneOffsetMinutes(selectedTimeZone, new Date(wallTimeAsUtc));
  return new Date(wallTimeAsUtc - offsetMinutes * 60_000).toISOString();
}

function timeZoneOffsetMinutes(selectedTimeZone, date) {
  if (selectedTimeZone === "UTC") return 0;
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: selectedTimeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const zonedTimeAsUtc = Date.UTC(
    Number(values.year),
    Number(values.month) - 1,
    Number(values.day),
    Number(values.hour),
    Number(values.minute),
    Number(values.second),
  );
  return (zonedTimeAsUtc - date.getTime()) / 60_000;
}

function renderEmpty(text) {
  offeringsBody.innerHTML = `<tr><td colspan="10" class="empty">${escapeHtml(text)}</td></tr>`;
}

function renderWarnings(errors) {
  warningsList.innerHTML = "";
  if (!errors.length) {
    warningsList.innerHTML = "<li>No warnings.</li>";
    return;
  }

  const grouped = new Map();
  errors.forEach((error) => {
    const message = sanitizeError(error.message || "Unknown error");
    if (!grouped.has(message)) grouped.set(message, new Set());
    grouped.get(message).add(error.region || "unknown");
  });

  Array.from(grouped.entries()).forEach(([message, regions]) => {
    const item = document.createElement("li");
    item.textContent = `${Array.from(regions).sort().join(", ")}: ${message}`;
    warningsList.appendChild(item);
  });
}

function sanitizeError(message) {
  const marker = "ValidationException) when calling the SearchTrainingPlanOfferings operation: ";
  const index = message.indexOf(marker);
  return index >= 0 ? message.slice(index + marker.length) : message;
}

function exportJson() {
  if (!lastResult) return;
  const blob = new Blob([JSON.stringify(lastResult, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "training-plan-search-result.json";
  link.click();
  URL.revokeObjectURL(url);
}

async function copyCliCommand() {
  if (!lastPayload) return;
  const command = cliCommand(lastPayload);
  await copyText(command, "CLI command copied.");
}

function cliCommand(payload) {
  const parts = [
    "python",
    "-m",
    "training_plan_discovery.cli",
    "--instance-type",
    shellQuote(payload.instance_type),
  ];
  if (payload.duration_days !== undefined) {
    parts.push("--duration-days", String(payload.duration_days));
  } else {
    parts.push("--duration-hours", String(payload.duration_hours));
  }
  parts.push("--instance-count", String(payload.instance_count || 1));
  parts.push("--maximum-segments", String(payload.maximum_segments || 1));
  parts.push("--max-lookahead-weeks", String(payload.approved_lookahead_weeks || 1));
  if (payload.start_time_after) parts.push("--start-time-after", shellQuote(payload.start_time_after));
  if (payload.skip_instance_type_validation) parts.push("--skip-instance-type-validation");
  if (payload.regions && payload.regions.length) {
    parts.push("--regions", ...payload.regions.map(shellQuote));
  }
  return parts.join(" ");
}

function shellQuote(value) {
  const text = String(value || "");
  return /^[A-Za-z0-9._:/+-]+$/.test(text) ? text : `"${text.replaceAll('"', '\\"')}"`;
}

async function copyText(value, message) {
  try {
    await navigator.clipboard.writeText(value);
    setMessage(message, "success");
  } catch (error) {
    setMessage("Copy failed. Select and copy the value manually.", "error");
  }
}

function startSearchTimer() {
  const started = Date.now();
  const regions = selectedRegions();
  const regionText = regions.length ? regions.join(", ") : "no selected regions";
  const update = () => {
    const elapsedSeconds = Math.max(0, Math.round((Date.now() - started) / 1000));
    setMessage(`Searching ${regionText} for start dates through ${approvedLookaheadWeeks} week(s). Elapsed ${elapsedSeconds}s...`);
  };
  update();
  searchTimer = window.setInterval(update, 1000);
}

function stopSearchTimer() {
  if (searchTimer !== null) {
    window.clearInterval(searchTimer);
    searchTimer = null;
  }
}

function totalHours(capacity, offering) {
  const total = capacity.reduce((sum, item) => sum + Number(item.DurationHours || 0), 0);
  return total || Number(offering.duration_hours || 0);
}

function safeId(value) {
  return String(value).replace(/[^A-Za-z0-9_-]/g, "-");
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  runSearch({ resetApproval: true });
});

validateButton.addEventListener("click", validateInstanceType);

approveNextButton.addEventListener("click", () => {
  approvedLookaheadWeeks = Number(approveNextButton.dataset.nextWindow || "1");
  runSearch();
});

clearResultsButton.addEventListener("click", clearResults);
resetFormButton.addEventListener("click", resetForm);
exportJsonButton.addEventListener("click", exportJson);
copyCliButton.addEventListener("click", copyCliCommand);
maximumSegments.addEventListener("input", updateSegmentsWarning);
maximumSegments.addEventListener("input", updateSegmentFilterOptions);
maximumSegments.addEventListener("change", updateSegmentsWarning);
maximumSegments.addEventListener("change", updateSegmentFilterOptions);
maxLookahead.addEventListener("change", () => {
  approvedLookaheadWeeks = Number(maxLookahead.value || "1");
  windowStatus.textContent = `${approvedLookaheadWeeks} week start window`;
});
timeZone.addEventListener("change", () => renderOfferings(currentOfferings));
tableSearch.addEventListener("input", () => renderOfferings(currentOfferings));
regionFilter.addEventListener("change", () => renderOfferings(currentOfferings));
azFilter.addEventListener("change", () => renderOfferings(currentOfferings));
segmentFilter.addEventListener("change", () => renderOfferings(currentOfferings));
sortButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const key = button.dataset.sortKey;
    if (sortState.key === key) {
      sortState.direction = sortState.direction === "asc" ? "desc" : "asc";
    } else {
      sortState = { key, direction: key === "start" ? "desc" : "asc" };
    }
    renderOfferings(currentOfferings);
  });
});

loadSupportedTypes();
updateSegmentsWarning();
updateSegmentFilterOptions();
approvedLookaheadWeeks = Number(maxLookahead.value || "1");
windowStatus.textContent = `${approvedLookaheadWeeks} week start window`;
