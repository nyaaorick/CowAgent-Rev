/* =====================================================================
 * Address book: the Contacts / Groups list and the per-conversation
 * switches in the header.
 *
 * Loaded after console.js and workspace.js, and reuses their globals
 * (t, escapeHtml, switchSession, sessionId, currentView, activeAgentId,
 * openWorkspacePanel, openInPreview, ...).
 *
 * The Contacts and Groups views are the chat pane with a different list on
 * the left, so nothing here renders a conversation: clicking a row calls
 * console.js's own switchSession() and the existing window takes over.
 * ===================================================================== */

// A WeChat session id ending in this addresses a room rather than a person.
const CT_CHATROOM_SUFFIX = '@chatroom';

// How long to wait after the last keystroke before filtering. The list is
// filtered in memory, so this is only to keep several thousand rows from
// re-rendering on every character.
const CT_SEARCH_DEBOUNCE_MS = 150;

// The catalog as the server last reported it. Filtering is done here rather
// than by refetching: the operator types into a list they can already see.
let ctCatalog = [];
let ctKind = '';              // 'contact' | 'group' | '' when not in these views
let ctQuery = '';
let ctSearchTimer = null;
let ctLoaded = false;
let ctScanning = false;
// The session the switches act on. Empty in the sandbox, which has none.
let ctSelected = '';

// =====================================================================
// API gateway
// =====================================================================
async function ctApi(path, options) {
    const res = await fetch(path, options);
    const data = await res.json();
    if (data.status !== 'success') {
        const err = new Error(data.message || 'Request failed');
        // Carried through so callers can branch on the machine-readable code
        // rather than string-matching an English message that translation or a
        // reworded log line would silently break.
        err.code = data.code || '';
        throw err;
    }
    return data;
}

// =====================================================================
// View wiring
// =====================================================================
function ctIsAddressBookView(viewId) {
    return viewId === 'contacts' || viewId === 'groups';
}

/**
 * Called by console.js's navigateTo(). Swaps the session panel's list for the
 * address book (or back), and loads the catalog the first time it is needed.
 */
function ctOnViewChange(viewId) {
    const inAddressBook = ctIsAddressBookView(viewId);
    ctKind = inAddressBook ? (viewId === 'groups' ? 'group' : 'contact') : '';

    const toolbar = document.getElementById('contact-toolbar');
    const contactList = document.getElementById('contact-list');
    const sessionList = document.getElementById('session-list');
    const newWrap = document.querySelector('.session-panel-new-wrap');
    if (!toolbar || !contactList || !sessionList) return;

    toolbar.hidden = !inAddressBook;
    contactList.hidden = !inAddressBook;
    sessionList.hidden = inAddressBook;
    // "New chat" starts a console conversation, which is not a thing you can
    // do to a WeChat contact.
    if (newWrap) newWrap.hidden = inAddressBook;

    const title = document.querySelector('.session-panel-title');
    if (title) {
        const key = inAddressBook
            ? (viewId === 'groups' ? 'menu_groups' : 'menu_contacts')
            : 'session_history';
        title.dataset.i18n = key;
        title.textContent = t(key);
    }

    if (!inAddressBook) {
        ctSetSwitchesVisible(false);
        return;
    }

    // A selection made in the other pane is not shown in this one, so keeping
    // it would leave the header switches acting on a row the operator can no
    // longer see -- and pointing at a group's @mention rule while the Contacts
    // list is on screen.
    const selected = ctCurrentRow();
    if (selected && !!selected.is_group !== (ctKind === 'group')) ctSelected = '';

    if (typeof openSessionPanel === 'function' && !sessionPanelOpen) openSessionPanel();
    if (!ctLoaded) {
        ctLoad();
    } else {
        ctRender();
    }
    ctSyncSwitches();
}

// =====================================================================
// Loading and scanning
// =====================================================================
async function ctLoad() {
    try {
        const data = await ctApi('/api/contacts');
        ctCatalog = data.contacts || [];
        ctLoaded = true;
        ctSetHint('');
    } catch (e) {
        ctSetHint(e.message);
    }
    ctRender();
}

/**
 * Re-read the address book from WeChat.
 *
 * A failed scan leaves the rendered list exactly as it was: the server keeps
 * its cached catalog on failure, and overwriting the screen with an empty list
 * would read as "you have no contacts" rather than "WeChat is not running".
 */
async function ctScan() {
    if (ctScanning) return;
    ctScanning = true;
    ctSetScanLabel('contacts_scanning');
    try {
        const data = await ctApi('/api/contacts/scan', { method: 'POST' });
        // The count is reported after the reload, not before: ctLoad() clears
        // the hint on success, which would wipe this message the moment it
        // appeared.
        await ctLoad();
        ctSetHint(t('contacts_scan_done').replace('{n}', data.total), 'info');
    } catch (e) {
        ctSetHint(e.code === 'wcf_offline' ? t('contacts_offline') : e.message);
    } finally {
        ctScanning = false;
        ctSetScanLabel('contacts_scan');
    }
}

function ctSetScanLabel(key) {
    const label = document.getElementById('contact-scan-label');
    if (!label) return;
    label.dataset.i18n = key;
    label.textContent = t(key);
}

function ctSetHint(message, kind) {
    const hint = document.getElementById('contact-hint');
    if (!hint) return;
    hint.textContent = message || '';
    hint.hidden = !message;
    hint.classList.toggle('contact-hint-info', kind === 'info');
}

function ctOnSearch(value) {
    ctQuery = value || '';
    clearTimeout(ctSearchTimer);
    ctSearchTimer = setTimeout(ctRender, CT_SEARCH_DEBOUNCE_MS);
}

// =====================================================================
// Rendering
// =====================================================================
function ctVisibleRows() {
    const wantGroup = ctKind === 'group';
    const needle = ctQuery.trim().toLowerCase();
    return ctCatalog.filter(row => {
        if (!!row.is_group !== wantGroup) return false;
        if (!needle) return true;
        return ['remark', 'nickname', 'name', 'alias', 'wxid'].some(
            field => String(row[field] || '').toLowerCase().includes(needle));
    });
}

/**
 * Escape a value for use inside a double-quoted HTML attribute.
 *
 * console.js's escapeHtml() serialises a text node, so it encodes & < > but
 * leaves both quote characters alone. That is correct for text content and
 * wrong for an attribute, where a single " ends the value early. Contact ids
 * come from WeChat rather than from us, so they are escaped for the context
 * they are actually going into.
 */
function ctAttr(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function ctRender() {
    const list = document.getElementById('contact-list');
    if (!list) return;

    const rows = ctVisibleRows();
    const parts = [ctSandboxRowHTML()];

    if (!rows.length) {
        parts.push(`<div class="contact-empty">${escapeHtml(
            ctLoaded && ctCatalog.length ? t('contacts_no_match') : t('contacts_empty')
        )}</div>`);
    } else {
        parts.push(rows.map(ctRowHTML).join(''));
    }
    list.innerHTML = parts.join('');
}

/**
 * The pinned sandbox row. It is not a WeChat session: selecting it hands the
 * conversation back to the console's own chat, where nothing reaches WeChat.
 */
function ctSandboxRowHTML() {
    const active = !ctSelected ? ' active' : '';
    return `
        <div class="session-item contact-sandbox${active}" data-ct-sandbox="1"
             title="${ctAttr(t('contacts_sandbox_desc'))}">
            <span class="contact-dot contact-dot-off"></span>
            <i class="fas fa-flask session-icon"></i>
            <span class="contact-text">
                <span class="contact-name">${escapeHtml(t('contacts_sandbox'))}</span>
                <span class="contact-meta">${escapeHtml(t('contacts_sandbox_desc'))}</span>
            </span>
        </div>`;
}

function ctRowHTML(row) {
    const active = row.wxid === ctSelected ? ' active' : '';
    const dot = row.allowed ? 'contact-dot' : 'contact-dot contact-dot-off';
    const icon = row.is_group ? 'fa-user-group' : 'fa-user';
    // The WeChat ID is what the operator searches by, and the raw id is all
    // they have when the contact database is unreadable (ROADMAP WCF-BUG-02).
    const meta = row.alias || row.wxid;
    return `
        <div class="session-item${active}" data-session-id="${ctAttr(row.wxid)}"
             data-ct-wxid="${ctAttr(row.wxid)}" title="${ctAttr(row.wxid)}">
            <span class="${dot}"></span>
            <i class="fas ${icon} session-icon"></i>
            <span class="contact-text">
                <span class="contact-name">${escapeHtml(row.name)}</span>
                <span class="contact-meta">${escapeHtml(meta)}</span>
            </span>
        </div>`;
}

// =====================================================================
// Selection
// =====================================================================
/**
 * One listener for the whole list, rather than an onclick per row.
 *
 * Building `onclick="ctSelect('<id>')"` by interpolation would put a
 * WeChat-chosen id inside a JS string inside an HTML attribute -- two nested
 * quoting contexts to get right on every render. Reading it back off the
 * element removes both.
 */
document.addEventListener('click', event => {
    const row = event.target.closest('#contact-list .session-item');
    if (!row) return;
    if (row.dataset.ctSandbox) {
        ctSelectSandbox();
    } else if (row.dataset.ctWxid) {
        ctSelect(row.dataset.ctWxid);
    }
});

function ctSelect(wxid) {
    // Switch first, then follow. switchSession can decline -- an unsaved
    // preview edit makes it ask, and answering "stay" leaves the conversation
    // where it was. Reading the selection back off sessionId rather than
    // assuming the click won means the list cannot end up highlighting a
    // contact whose conversation is not the one on screen.
    if (typeof switchSession === 'function') switchSession(wxid);
    ctSelected = (typeof sessionId !== 'undefined' && sessionId === wxid) ? wxid : ctSelected;
    ctSyncSwitches();
    ctRender();
}

/**
 * Enter the debug sandbox: the console's own conversation, where nothing
 * reaches WeChat.
 *
 * Navigating alone is not enough. If the operator was in a WeChat conversation
 * the session would come with them, and the "sandbox" would be that contact's
 * thread with a composer that sends to them for real -- the one thing this row
 * promises it is not. So a WeChat session is left behind for a fresh console
 * one.
 */
function ctSelectSandbox() {
    ctSelected = '';
    ctSetSwitchesVisible(false);
    ctRender();
    // The address book stays on screen: the sandbox is a row in it, not a
    // different place. Only the conversation changes, and only when it has to
    // -- an operator already in a console chat is already in the sandbox.
    if (typeof isMirroredSession === 'function' && isMirroredSession(sessionId)
            && typeof newChat === 'function') {
        newChat(true);
    }
}

function ctCurrentRow() {
    return ctCatalog.find(row => row.wxid === ctSelected) || null;
}

// =====================================================================
// Header switches
// =====================================================================
function ctSetSwitchesVisible(visible) {
    const box = document.getElementById('contact-switches');
    if (box) box.hidden = !visible;
}

/** Point the header switches at the selected session, or hide them. */
function ctSyncSwitches() {
    const row = ctCurrentRow();
    if (!row || !ctIsAddressBookView(currentView)) {
        ctSetSwitchesVisible(false);
        return;
    }
    ctSetSwitchesVisible(true);

    const isGroup = !!row.is_group;
    // A room is admitted or ignored, a person is answered or observed: the
    // second switch means something different in each view, so it is relabelled
    // rather than shown alongside a control that does not apply.
    const allowedLabel = document.getElementById('sw-allowed-label');
    if (allowedLabel) {
        const key = isGroup ? 'sw_room_allowed' : 'sw_allowed';
        allowedLabel.dataset.i18n = key;
        allowedLabel.textContent = t(key);
        // The tooltip is rendered from data-tooltip by applyI18n, so swapping
        // the key alone would leave the contact wording on a group's switch
        // until the next language change.
        const wrap = allowedLabel.closest('.contact-switch');
        if (wrap) {
            const tipKey = isGroup ? 'sw_room_allowed_tip' : 'sw_allowed_tip';
            wrap.dataset.tipKey = tipKey;
            wrap.setAttribute('data-tooltip', t(tipKey));
        }
    }
    const atFreeWrap = document.getElementById('sw-at-free-wrap');
    const autoWrap = document.getElementById('sw-auto-answer-wrap');
    if (atFreeWrap) atFreeWrap.hidden = !isGroup;
    if (autoWrap) autoWrap.hidden = isGroup;

    ctSetChecked('sw-allowed', row.allowed);
    ctSetChecked('sw-auto-answer', row.auto_answer);
    ctSetChecked('sw-at-free', row.at_free);
}

function ctSetChecked(id, value) {
    const el = document.getElementById(id);
    if (el) el.checked = !!value;
}

/**
 * Flip one switch on the selected session.
 *
 * The checkbox is put back to whatever the server reports rather than left
 * where the click left it: a switch that looks on while the gate is off is the
 * one failure this UI must not have.
 */
async function ctToggle(name, value) {
    const row = ctCurrentRow();
    if (!row) return;
    try {
        const data = await ctApi('/api/contacts/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ wxid: row.wxid, switch: name, value: !!value }),
        });
        Object.assign(row, data.switches);
        ctSetHint('');
    } catch (e) {
        ctSetHint(e.message);
    }
    ctSyncSwitches();
    ctRender();
}

// =====================================================================
// Workspace button
// =====================================================================
/**
 * The profile file the Workspace button should open for the selected contact,
 * or '' when there is no contact selected (the sandbox, or another view).
 *
 * Resolved server-side so the file is created on first open; the panel itself
 * then reads and edits it through the workspace endpoints it always used.
 */
async function ctProfilePath() {
    if (!ctSelected || !ctIsAddressBookView(currentView)) return '';
    try {
        const data = await ctApi('/api/contacts/profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                wxid: ctSelected,
                agent: (typeof activeAgentId !== 'undefined') ? activeAgentId : '',
            }),
        });
        return data.path || '';
    } catch (e) {
        ctSetHint(e.message);
        return '';
    }
}
