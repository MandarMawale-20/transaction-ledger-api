/* Ledger dashboard — vanilla JS, no framework, no build step. */
"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const STORAGE_KEY = "ledger.selectedAccount";
const PENDING_KEY = "ledger.pending.v1";

const state = {
  accounts: [],
  account: null,
  selectedId: readStoredId(),
  history: { type: "", limit: 10, offset: 0, total: 0, items: [] },
  historyRequestId: 0,
  busyTx: false,
  busyTransfer: false,
};

class ApiError extends Error {
  constructor(status, code, message, details = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/* ---------- API ---------- */

async function request(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      0,
      "NETWORK_ERROR",
      "Cannot reach the API. Check that the server is running and try again.",
    );
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = payload.error || {};
    throw new ApiError(
      response.status,
      error.code || "HTTP_ERROR",
      error.message || `Request failed with status ${response.status}.`,
      error.details || {},
    );
  }
  return { data: payload, status: response.status };
}

/* ---------- formatting ---------- */

function fmtMoney(value) {
  if (value === null || value === undefined) return "—";
  const [whole, fraction = ""] = String(value).split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${grouped}.${fraction.padEnd(2, "0").slice(0, 2)}`;
}

function fmtDateTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function cap(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function uid() {
  // UUID collisions are negligible and match the idempotency-key guidance
  // used by payment APIs. The fallback covers non-secure contexts.
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now().toString(16)}${Math.random().toString(16).slice(2, 10)}`;
}

function newReference(prefix) {
  return `${prefix}-${uid()}`;
}

function readStoredId() {
  try {
    return localStorage.getItem(STORAGE_KEY) || null;
  } catch {
    return null;
  }
}

function storeSelectedId(id) {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* private mode: selection just won't persist */
  }
}

/* ---------- uncertain requests ---------- */

function readPending() {
  try {
    const parsed = JSON.parse(localStorage.getItem(PENDING_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    const day = 24 * 60 * 60 * 1000;
    return parsed.filter((item) => {
      if (!item || !item.id || !item.accountId || !item.payload) return false;
      if (item.kind !== "transaction" && item.kind !== "transfer") return false;
      if (!item.payload.reference_id || !item.payload.amount) return false;
      if (item.kind === "transfer" && !item.payload.to_account_id) return false;
      const age = Date.now() - Date.parse(item.createdAt);
      return Number.isFinite(age) && age >= 0 && age < day;
    });
  } catch {
    return [];
  }
}

function writePending(items) {
  try {
    localStorage.setItem(PENDING_KEY, JSON.stringify(items.slice(-20)));
  } catch {
    /* storage full or blocked: the form still works, only recovery is lost */
  }
}

function rememberPending(kind, accountId, payload) {
  const item = { id: uid(), kind, accountId, payload, createdAt: new Date().toISOString() };
  // One record per (account, kind, reference): retrying must not stack duplicates.
  const rest = readPending().filter(
    (pending) =>
      !(
        pending.kind === kind &&
        pending.accountId === accountId &&
        pending.payload.reference_id === payload.reference_id
      ),
  );
  writePending([...rest, item]);
  return item.id;
}

function forgetPending(id) {
  writePending(readPending().filter((item) => item.id !== id));
  const banner = $("#pending-banner");
  // A retry replaces the stored record with a new id, so clear the banner when
  // the record it was showing is gone, not just when the ids match exactly.
  const shownId = banner.dataset.pendingId;
  if (shownId && (shownId === id || !readPending().some((item) => item.id === shownId))) {
    banner.hidden = true;
    delete banner.dataset.pendingId;
  }
}

function isDefinitive(error) {
  // 4xx means the request was rejected before any write. Network errors and
  // 5xx are uncertain: the server may have committed and lost the response.
  return error.status >= 400 && error.status < 500;
}

function pendingAccountExists(item) {
  if (!state.accounts.some((account) => account.id === item.accountId)) return false;
  return (
    item.kind !== "transfer" ||
    state.accounts.some((account) => account.id === item.payload.to_account_id)
  );
}

function restorePending() {
  const candidates = readPending().filter(pendingAccountExists);
  if (candidates.length === 0) return;

  // The newest uncertain request is the one the user was last working on.
  const item = candidates[candidates.length - 1];
  if (item.accountId !== state.selectedId) selectAccount(item.accountId);

  if (item.kind === "transaction") {
    for (const input of $$('input[name="tx-type"]')) {
      input.checked = input.value === item.payload.type;
    }
    $("#tx-amount").value = item.payload.amount;
    $("#tx-description").value = item.payload.description || "";
    $("#tx-reference").value = item.payload.reference_id;
    $("#tx-advanced").open = true;
  } else {
    $("#transfer-to").value = item.payload.to_account_id;
    $("#transfer-amount").value = item.payload.amount;
    $("#transfer-description").value = item.payload.description || "";
    $("#transfer-reference").value = item.payload.reference_id;
    $("#transfer-advanced").open = true;
  }

  const label = item.kind === "transaction" ? "transaction" : "transfer";
  $("#pending-text").textContent =
    `An earlier ${label} may not have completed. Its details and reference are restored — ` +
    "submit it again to confirm. Reusing the same reference prevents a double entry.";

  const banner = $("#pending-banner");
  banner.dataset.pendingId = item.id;
  banner.hidden = false;
}

function openAdvanced(kind) {
  const details = kind === "transaction" ? $("#tx-advanced") : $("#transfer-advanced");
  if (details) details.open = true;
}

/* ---------- errors ---------- */

function errorText(error) {
  if (error.code === "NETWORK_ERROR") return error.message;
  if (error.status === 422 && error.details?.errors?.length) {
    const first = error.details.errors[0];
    const field = String(first.field || "").replace(/^body\./, "");
    return `${field ? field + ": " : ""}${first.message}`;
  }
  if (error.code === "INSUFFICIENT_BALANCE") {
    return `Not enough funds: balance is ${fmtMoney(error.details.balance)}, requested ${fmtMoney(error.details.requested)}.`;
  }
  if (error.code === "REFERENCE_ID_CONFLICT") {
    return "That reference is already used with a different request. Change the reference, amount or description.";
  }
  if (error.code === "BALANCE_LIMIT_EXCEEDED") {
    return "That would exceed the maximum supported balance.";
  }
  if (error.code === "ACCOUNT_NOT_FOUND") {
    return "That account no longer exists.";
  }
  return error.message || "Something went wrong.";
}

function showFormError(id, message) {
  const node = $(id);
  node.textContent = message;
  node.hidden = false;
}

function hideFormError(id) {
  const node = $(id);
  node.hidden = true;
  node.textContent = "";
}

function showGlobalError(message) {
  const node = $("#global-error");
  node.textContent = message;
  node.hidden = false;
}

function hideGlobalError() {
  $("#global-error").hidden = true;
}

/* ---------- toasts ---------- */

function toast(kind, title, message, timeout = 6000) {
  const host = $("#toasts");
  const node = document.createElement("div");
  node.className = `toast toast-${kind}`;
  node.setAttribute("role", kind === "error" ? "alert" : "status");

  const icon = document.createElement("span");
  icon.className = "toast-icon";
  icon.innerHTML = `<svg class="icon" aria-hidden="true"><use href="#${kind === "error" ? "i-alert" : "i-check"}"/></svg>`;

  const body = document.createElement("div");
  const heading = document.createElement("p");
  heading.className = "toast-title";
  heading.textContent = title;
  const detail = document.createElement("p");
  detail.className = "toast-message";
  detail.textContent = message;
  body.append(heading, detail);

  const close = document.createElement("button");
  close.type = "button";
  close.className = "toast-close";
  close.setAttribute("aria-label", "Dismiss notification");
  close.textContent = "×";

  node.append(icon, body, close);
  host.append(node);

  let timer = window.setTimeout(dismiss, timeout);

  function dismiss() {
    window.clearTimeout(timer);
    node.classList.add("is-leaving");
    window.setTimeout(() => node.remove(), 200);
  }

  close.addEventListener("click", dismiss);
  node.addEventListener("mouseenter", () => window.clearTimeout(timer));
  node.addEventListener("mouseleave", () => {
    timer = window.setTimeout(dismiss, 2000);
  });
}

/* ---------- health ---------- */

async function checkHealth() {
  try {
    await request("/health");
    setHealth("ok");
  } catch {
    setHealth("bad");
  }
}

function setHealth(status) {
  const dot = $("#health-dot");
  const text = $("#health-text");
  dot.dataset.state = status;
  text.textContent =
    status === "ok"
      ? "API connected"
      : status === "bad"
        ? "API unreachable"
        : "Checking API…";
}

/* ---------- accounts ---------- */

async function loadAccounts({ selectId = null } = {}) {
  try {
    const { data } = await request("/accounts?limit=100");
    state.accounts = data.items;
    hideGlobalError();

    if (selectId) state.selectedId = selectId;
    const stillExists = state.accounts.some((account) => account.id === state.selectedId);
    if (!stillExists) {
      state.selectedId = state.accounts[0]?.id || null;
      storeSelectedId(state.selectedId);
    }

    renderAccounts();
    renderTransferTargets();

    if (state.selectedId) await loadSelected({ keepRows: false });
    else clearSelected();
  } catch (error) {
    setHealth("bad");
    showGlobalError(`Could not load accounts. ${errorText(error)}`);
  }
}

async function loadSelected({ keepRows = true } = {}) {
  if (!state.selectedId) {
    clearSelected();
    return;
  }

  if (!keepRows) clearHistoryRows("Loading transactions…");

  try {
    const { data } = await request(`/accounts/${state.selectedId}`);
    state.account = data;
    paintAccount();
    syncFormAvailability();
    await loadHistory({ keepRows });
  } catch (error) {
    if (error.status === 404) {
      state.selectedId = null;
      state.account = null;
      storeSelectedId(null);
      toast("error", "Account missing", "That account no longer exists. Pick another one.");
      await loadAccounts();
      return;
    }
    setHealth("bad");
    showGlobalError(`Could not load the account. ${errorText(error)}`);
  }
}

function selectAccount(id) {
  if (!id || id === state.selectedId) return;
  state.selectedId = id;
  state.account = null;
  storeSelectedId(id);
  renderAccounts();
  renderTransferTargets();
  clearHistoryRows("Loading transactions…");
  syncFormAvailability();
  loadSelected({ keepRows: false });
}

function paintAccount() {
  const account = state.account;
  if (!account) return;
  $("#selected-name").textContent = account.name;
  $("#selected-id").textContent = account.id;
  $("#selected-created").textContent = `Created ${fmtDateTime(account.created_at)}`;
  $("#selected-balance").textContent = fmtMoney(account.balance);
  $("#transfer-from-name").textContent = account.name;
  $("#transfer-from-balance").textContent = fmtMoney(account.balance);
}

function clearSelected() {
  state.account = null;
  $("#selected-name").textContent = "No account selected";
  $("#selected-id").textContent = "—";
  $("#selected-created").textContent = "";
  $("#selected-balance").textContent = "—";
  $("#transfer-from-name").textContent = "No account selected";
  $("#transfer-from-balance").textContent = "—";
  syncFormAvailability();
  renderHistory();
}

function renderAccounts() {
  const list = $("#account-list");
  const filter = $("#account-filter").value.trim().toLowerCase();
  list.innerHTML = "";

  const visible = state.accounts.filter((account) => {
    if (!filter) return true;
    return (
      account.name.toLowerCase().includes(filter) ||
      account.id.toLowerCase().includes(filter)
    );
  });

  $("#account-count").textContent = String(state.accounts.length);
  $("#accounts-empty").hidden = visible.length !== 0;
  $("#accounts-empty").textContent = state.accounts.length
    ? "No accounts match that filter."
    : "No accounts yet. Create the first one.";

  for (const account of visible) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "account-item";
    if (account.id === state.selectedId) button.setAttribute("aria-current", "true");
    button.title = account.name;

    const top = document.createElement("span");
    top.className = "account-top";
    const name = document.createElement("span");
    name.className = "account-name";
    name.textContent = account.name;
    const amount = document.createElement("span");
    amount.className = "account-amount";
    amount.textContent = fmtMoney(account.balance);
    top.append(name, amount);

    const sub = document.createElement("span");
    sub.className = "account-sub";
    sub.textContent = account.id.slice(0, 8);

    button.append(top, sub);
    button.addEventListener("click", () => selectAccount(account.id));

    item.append(button);
    list.append(item);
  }
}

function renderTransferTargets() {
  const select = $("#transfer-to");
  const previous = select.value;
  select.innerHTML = "";

  const others = state.accounts.filter((account) => account.id !== state.selectedId);
  if (others.length === 0) {
    select.add(new Option("No other accounts", ""));
    return;
  }

  for (const account of others) {
    select.add(new Option(`${account.name} — ${account.id.slice(0, 8)}`, account.id));
  }
  if (others.some((account) => account.id === previous)) select.value = previous;
}

/* ---------- history ---------- */

async function loadHistory({ keepRows = true } = {}) {
  if (!state.selectedId) {
    clearHistoryRows("Select an account to see its history.");
    renderHistory();
    return;
  }

  const { type, limit, offset } = state.history;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (type) params.set("type", type);

  const wrap = $(".table-wrap");
  wrap.setAttribute("aria-busy", "true");
  if (!keepRows) clearHistoryRows("Loading transactions…");

  const requestId = ++state.historyRequestId;
  try {
    const { data } = await request(
      `/accounts/${state.selectedId}/transactions?${params.toString()}`,
    );
    if (requestId !== state.historyRequestId) return; // a newer request won
    state.history.items = data.items;
    state.history.total = data.total;
    state.history.limit = data.limit;
    state.history.offset = data.offset;
    renderHistory();
  } catch (error) {
    if (requestId !== state.historyRequestId) return;
    showGlobalError(`Could not load history. ${errorText(error)}`);
    clearHistoryRows("History could not be loaded.");
  } finally {
    if (requestId === state.historyRequestId) wrap.setAttribute("aria-busy", "false");
  }
}

function clearHistoryRows(message) {
  const body = $("#history-body");
  body.innerHTML = `<tr class="is-empty"><td colspan="5" class="table-empty">${esc(message)}</td></tr>`;
  $("#page-info").textContent = "—";
  $("#prev-page").disabled = true;
  $("#next-page").disabled = true;
}

function renderHistory() {
  const body = $("#history-body");
  const { items, total, offset, limit, type } = state.history;

  if (!state.selectedId) {
    clearHistoryRows("Select an account to see its history.");
    return;
  }

  if (items.length === 0) {
    const message = type
      ? `No ${type} transactions yet on this account.`
      : "No transactions yet. Post a credit to get started.";
    clearHistoryRows(message);
    $("#page-info").textContent = "No transactions";
    return;
  }

  body.innerHTML = items
    .map((txn) => {
      const credit = txn.type === "credit";
      const sign = credit ? "+" : "−";
      const transferTag = txn.transfer_id
        ? `<span class="badge badge-transfer" title="Transfer ${esc(txn.transfer_id)}">transfer</span>`
        : "";
      return `<tr>
        <td><time class="time" datetime="${esc(txn.created_at)}">${esc(fmtDateTime(txn.created_at))}</time></td>
        <td><span class="badge badge-${credit ? "credit" : "debit"}">${cap(txn.type)}</span>${transferTag}</td>
        <td class="num"><span class="amount amount-${credit ? "credit" : "debit"}">${sign}${fmtMoney(txn.amount)}</span></td>
        <td class="desc ${txn.description ? "" : "desc-empty"}">${txn.description ? esc(txn.description) : "—"}</td>
        <td class="col-ref"><span class="ref" title="${esc(txn.reference_id)}">${esc(txn.reference_id)}</span></td>
      </tr>`;
    })
    .join("");

  const from = offset + 1;
  const to = offset + items.length;
  $("#page-info").textContent = `Showing ${from}–${to} of ${total}`;
  $("#prev-page").disabled = offset === 0;
  $("#next-page").disabled = offset + limit >= total;
}

/* ---------- form state ---------- */

function syncFormAvailability() {
  const hasAccount = Boolean(state.account);
  const others = state.accounts.filter((account) => account.id !== state.selectedId);
  const canTransfer = hasAccount && others.length > 0;

  for (const field of $$("#tx-form input, #tx-form button")) {
    field.disabled = !hasAccount || state.busyTx;
  }
  for (const field of $$("#transfer-form input, #transfer-form select, #transfer-form button")) {
    field.disabled = !canTransfer || state.busyTransfer;
  }

  const hint = $("#transfer-hint");
  if (!hasAccount) {
    hint.textContent = "Create an account to post transactions and transfers.";
    hint.hidden = false;
  } else if (others.length === 0) {
    hint.textContent = "Create a second account to send a transfer.";
    hint.hidden = false;
  } else {
    hint.hidden = true;
  }
  $("#copy-selected-id").disabled = !hasAccount;
}

function setSubmitting(form, busy, label) {
  const button = $('button[type="submit"]', form);
  if (busy) {
    button.dataset.label = button.innerHTML;
    button.innerHTML = `<span class="spinner" aria-hidden="true"></span>${esc(label)}`;
  } else if (button.dataset.label) {
    button.innerHTML = button.dataset.label;
  }

  if (form.id === "tx-form") state.busyTx = busy;
  else state.busyTransfer = busy;

  syncFormAvailability();
}

function validateAmount(value) {
  if (!value) return "Enter an amount.";
  if (!/^[0-9]+(\.[0-9]+)?$/.test(value)) {
    return "Use digits only, with a dot for decimals (for example 120.50).";
  }
  if (!/^[0-9]+(\.[0-9]{1,2})?$/.test(value)) {
    return "Use at most 2 decimal places.";
  }
  if (!/[1-9]/.test(value.replace(".", ""))) {
    return "Amount must be greater than zero.";
  }
  return "";
}

function validateReference(value) {
  if (!value) return "Enter a reference id.";
  if (value.length > 128) return "Reference id must be at most 128 characters.";
  return "";
}

/* ---------- actions ---------- */

async function createAccount(event) {
  event.preventDefault();
  const name = $("#new-account-name").value.trim();
  if (!name) {
    showFormError("#new-account-error", "Enter an account name.");
    return;
  }

  hideFormError("#new-account-error");
  const form = $("#new-account-form");
  const button = $('button[type="submit"]', form);
  const label = button.textContent;
  button.disabled = true;
  button.innerHTML = `<span class="spinner" aria-hidden="true"></span>Creating…`;

  try {
    const { data } = await request("/accounts", { method: "POST", body: { name } });
    form.reset();
    form.hidden = true;
    $("#new-account-toggle").setAttribute("aria-expanded", "false");
    toast("success", "Account created", `${data.name} starts with a balance of ${fmtMoney(data.balance)}.`);
    await loadAccounts({ selectId: data.id });
  } catch (error) {
    showFormError("#new-account-error", errorText(error));
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

async function postTransaction(event) {
  event.preventDefault();
  if (!state.selectedId) return;

  const accountId = state.selectedId;
  const form = event.currentTarget;
  const amount = $("#tx-amount").value.trim();
  const reference = $("#tx-reference").value.trim();
  const description = $("#tx-description").value.trim();
  const type = $('input[name="tx-type"]:checked', form).value;

  const problem = validateAmount(amount) || validateReference(reference);
  if (problem) {
    showFormError("#tx-error", problem);
    return;
  }

  hideFormError("#tx-error");
  const payload = {
    type,
    amount,
    reference_id: reference,
    description: description || null,
  };
  // Saved before the request: if the response is lost, the same reference
  // survives a refresh and the retry is idempotent.
  const pendingId = rememberPending("transaction", accountId, payload);
  setSubmitting(form, true, "Posting…");

  try {
    const { data, status } = await request(`/accounts/${accountId}/transactions`, {
      method: "POST",
      body: payload,
    });
    forgetPending(pendingId);

    if (status === 200 || data.duplicate) {
      toast(
        "success",
        "Already applied",
        "That reference was already used with the same payload. The original transaction was returned and the balance did not change.",
      );
    } else {
      toast(
        "success",
        `${cap(type)} posted`,
        `${fmtMoney(data.amount)} ${type === "credit" ? "added to" : "taken from"} ${state.account?.name || "the account"}.`,
      );
    }

    form.reset();
    $("#tx-reference").value = newReference("TX");
    $("#tx-advanced").open = false;
    state.history.offset = 0;
    await loadAccounts();
  } catch (error) {
    const message = errorText(error);
    if (isDefinitive(error)) forgetPending(pendingId);
    if (
      error.code === "REFERENCE_ID_CONFLICT" ||
      error.details?.errors?.some((item) => String(item.field).includes("reference_id"))
    ) {
      openAdvanced("transaction");
    }
    showFormError("#tx-error", message);
    toast(
      "error",
      isDefinitive(error) ? "Transaction failed" : "Outcome uncertain",
      isDefinitive(error)
        ? message
        : "The request may not have completed. It is saved; after a refresh the same reference is restored, so retrying is safe.",
    );
  } finally {
    setSubmitting(form, false, "");
  }
}

async function postTransfer(event) {
  event.preventDefault();
  if (!state.selectedId) return;

  const fromAccountId = state.selectedId;
  const form = event.currentTarget;
  const to = $("#transfer-to").value;
  const amount = $("#transfer-amount").value.trim();
  const reference = $("#transfer-reference").value.trim();
  const description = $("#transfer-description").value.trim();

  if (!to) {
    showFormError("#transfer-error", "Choose a destination account.");
    return;
  }
  const problem = validateAmount(amount) || validateReference(reference);
  if (problem) {
    showFormError("#transfer-error", problem);
    return;
  }

  hideFormError("#transfer-error");
  const payload = {
    from_account_id: fromAccountId,
    to_account_id: to,
    amount,
    reference_id: reference,
    description: description || null,
  };
  const pendingId = rememberPending("transfer", fromAccountId, payload);
  setSubmitting(form, true, "Sending…");

  try {
    const { data, status } = await request("/transfers", {
      method: "POST",
      body: payload,
    });
    forgetPending(pendingId);

    if (status === 200 || data.duplicate) {
      toast(
        "success",
        "Already sent",
        "That reference was already used with the same payload. The original transfer was returned; no money moved twice.",
      );
    } else {
      toast(
        "success",
        "Transfer sent",
        `${fmtMoney(data.amount)} moved from ${state.account?.name || "this account"} to ${$("#transfer-to").selectedOptions[0]?.textContent.split(" — ")[0] || "the destination"}.`,
      );
    }

    form.reset();
    $("#transfer-reference").value = newReference("TRF");
    $("#transfer-advanced").open = false;
    state.history.offset = 0;
    await loadAccounts();
  } catch (error) {
    const message = errorText(error);
    if (isDefinitive(error)) forgetPending(pendingId);
    if (
      error.code === "REFERENCE_ID_CONFLICT" ||
      error.details?.errors?.some((item) => String(item.field).includes("reference_id"))
    ) {
      openAdvanced("transfer");
    }
    showFormError("#transfer-error", message);
    toast(
      "error",
      isDefinitive(error) ? "Transfer failed" : "Outcome uncertain",
      isDefinitive(error)
        ? message
        : "The request may not have completed. It is saved; after a refresh the same reference is restored, so retrying is safe.",
    );
  } finally {
    setSubmitting(form, false, "");
  }
}

async function refreshAll() {
  const button = $("#refresh");
  button.disabled = true;
  try {
    await loadAccounts();
    await checkHealth();
  } finally {
    button.disabled = false;
  }
}

async function copySelectedId() {
  if (!state.account) return;
  const id = state.account.id;

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(id);
    } else {
      const helper = document.createElement("textarea");
      helper.value = id;
      helper.setAttribute("readonly", "");
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.append(helper);
      helper.select();
      document.execCommand("copy");
      helper.remove();
    }
    toast("success", "Copied", "Account id copied to the clipboard.", 2500);
  } catch {
    toast("error", "Copy failed", "Select the id and copy it manually.");
  }
}

/* ---------- wiring ---------- */

function bindEvents() {
  $("#account-filter").addEventListener("input", renderAccounts);
  $("#new-account-toggle").addEventListener("click", () => {
    const form = $("#new-account-form");
    form.hidden = !form.hidden;
    $("#new-account-toggle").setAttribute("aria-expanded", String(!form.hidden));
    if (!form.hidden) $("#new-account-name").focus();
  });
  $("#cancel-new-account").addEventListener("click", () => {
    $("#new-account-form").hidden = true;
    $("#new-account-toggle").setAttribute("aria-expanded", "false");
    hideFormError("#new-account-error");
  });
  $("#new-account-form").addEventListener("submit", createAccount);

  $("#tx-form").addEventListener("submit", postTransaction);
  $("#transfer-form").addEventListener("submit", postTransfer);

  for (const id of ["#tx-amount", "#tx-reference", "#tx-description"]) {
    $(id).addEventListener("input", () => hideFormError("#tx-error"));
  }
  for (const id of ["#transfer-amount", "#transfer-reference", "#transfer-description", "#transfer-to"]) {
    $(id).addEventListener("input", () => hideFormError("#transfer-error"));
  }

  $("#history-type").addEventListener("change", (event) => {
    state.history.type = event.currentTarget.value;
    state.history.offset = 0;
    loadHistory({ keepRows: false });
  });
  $("#history-limit").addEventListener("change", (event) => {
    state.history.limit = Number(event.currentTarget.value);
    state.history.offset = 0;
    loadHistory({ keepRows: false });
  });
  $("#prev-page").addEventListener("click", () => {
    state.history.offset = Math.max(0, state.history.offset - state.history.limit);
    loadHistory();
  });
  $("#next-page").addEventListener("click", () => {
    state.history.offset += state.history.limit;
    loadHistory();
  });

  $("#refresh").addEventListener("click", refreshAll);
  $("#copy-selected-id").addEventListener("click", copySelectedId);
  $("#pending-dismiss").addEventListener("click", () => {
    const banner = $("#pending-banner");
    const id = banner.dataset.pendingId;
    if (!id) return;
    const confirmed = window.confirm(
      "Only dismiss if you have confirmed this request did not go through. " +
        "If it did, submitting a different request could double-enter it.",
    );
    if (confirmed) forgetPending(id);
  });
}

async function init() {
  bindEvents();
  $("#tx-reference").value = newReference("TX");
  $("#transfer-reference").value = newReference("TRF");
  setHealth("checking");
  syncFormAvailability();
  await loadAccounts();
  restorePending();
  checkHealth();
  window.setInterval(checkHealth, 30000);
}

document.addEventListener("DOMContentLoaded", init);
