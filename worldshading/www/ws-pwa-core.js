/* =========================================================================
   World Shading PWA — shared core JS (WSPWA namespace).
   Served at /ws-pwa-core.js. Include once per PWA page BEFORE the page's own
   inline script:
       <script src="/ws-pwa-core.js?v=1"></script>
   Relies on the Frappe web bundle already present via the page's web.html base:
   frappe.ready / frappe.call / frappe.session / frappe.csrf_token / jQuery ($).
   NOTE: www/ .js and .css are Jinja-rendered by Frappe, so this file must not
   contain Jinja tokens (no double-brace or brace-percent sequences).
   Bump the ?v= query AND the page service worker cache name when this changes.
   ========================================================================= */

(function () {
    "use strict";

    var WSPWA = {};

    /* ---------------- Debug ---------------- */

    WSPWA.debug_enabled = false;

    WSPWA.debug = function (label, data) {
        if (!WSPWA.debug_enabled || !window.console || !console.log) {
            return;
        }
        console.log("[ws-pwa] " + label, data || {});
    };

    /* ---------------- HTML safety ---------------- */

    WSPWA.escapeHtml = function (value) {
        return $("<div>").text(value === null || value === undefined ? "" : value).html();
    };

    WSPWA.escapeAttr = function (value) {
        return WSPWA.escapeHtml(value).replace(/"/g, "&quot;");
    };

    WSPWA.stripHtml = function (value) {
        return $("<div>").html(value || "").text();
    };

    /* ---------------- Icons ---------------- */

    /* Base icon set. A page may add its own before rendering:
       WSPWA.icons.myicon = '<path .../>'; */
    WSPWA.icons = {
        "refresh": '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>',
        "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
        "back": '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>',
        "check": '<path d="M20 6 9 17l-5-5"/>',
        "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
        "calendar": '<path d="M8 2v4"/><path d="M16 2v4"/><path d="M3 10h18"/><path d="M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"/>',
        "tag": '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8Z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
        "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
        "file-text": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><path d="M8 13h8"/><path d="M8 17h5"/>',
        "box": '<path d="M21 8 12 3 3 8v8l9 5 9-5Z"/><path d="M3 8l9 5 9-5"/><path d="M12 13v8"/>',
        "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
        "logout": '<path d="M10 17l5-5-5-5"/><path d="M15 12H3"/><path d="M14 4h5a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-5"/>',
        "message": '<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/>',
        "chart": '<path d="M3 3v18h18"/><path d="M7 15l3-3 3 2 5-7"/>',
        "user": '<path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="7" r="4"/>',
        "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
        "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        "play": '<path d="m8 5 12 7-12 7V5Z"/>',
        "pause": '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
        "stop": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
        "phone": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.3 1.7.6 2.5a2 2 0 0 1-.5 2.1L8 9.5a16 16 0 0 0 6.5 6.5l1.2-1.2a2 2 0 0 1 2.1-.5c.8.3 1.6.5 2.5.6A2 2 0 0 1 22 16.9Z"/>',
        "map-pin": '<path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
        "download": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
        "share": '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 10.7 6.8-4.4"/><path d="m8.6 13.3 6.8 4.4"/>',
        "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
        "camera": '<path d="M14.5 4 16 7h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h3l1.5-3h5Z"/><circle cx="12" cy="13" r="3.5"/>'
    };

    WSPWA.iconSvg = function (name) {
        var path = WSPWA.icons[name] || WSPWA.icons.check;
        return '<svg class="ws-icon" viewBox="0 0 24 24" aria-hidden="true">' + path + '</svg>';
    };

    WSPWA.renderIcons = function (root) {
        $(root).find("[data-icon]").each(function () {
            var name = $(this).attr("data-icon");
            $(this).replaceWith(WSPWA.iconSvg(name));
        });
    };

    /* ---------------- Numbers / state ---------------- */

    WSPWA.clampPercent = function (value) {
        var number = parseFloat(value || 0);
        if (isNaN(number)) { number = 0; }
        if (number < 0) { number = 0; }
        if (number > 100) { number = 100; }
        return Math.round(number);
    };

    WSPWA.formatQty = function (qty, uom) {
        var number_value = parseFloat(qty || 0);
        if (isNaN(number_value)) { number_value = 0; }
        var text = number_value.toFixed(2).replace(/\.00$/, "");
        return text + (uom ? " " + uom : "");
    };

    WSPWA.stateClass = function (state) {
        state = (state || "").toLowerCase();
        if (state.indexOf("ready") !== -1) { return "state-ready"; }
        if (state.indexOf("progress") !== -1) { return "state-progress"; }
        if (state.indexOf("paused") !== -1) { return "state-paused"; }
        if (state.indexOf("stopped") !== -1 || state.indexOf("cancel") !== -1) { return "state-stop"; }
        if (state.indexOf("complete") !== -1 || state.indexOf("done") !== -1) { return "state-done"; }
        return "";
    };

    WSPWA.initials = function (name) {
        var parts = (name || "").trim().split(/\s+/);
        if (!parts.length || !parts[0]) { return "WS"; }
        var first = parts[0].charAt(0);
        var second = parts.length > 1 ? parts[parts.length - 1].charAt(0) : "";
        return (first + second).toUpperCase();
    };

    /* ---------------- Dates / time ---------------- */

    WSPWA.pad2 = function (value) {
        value = String(value);
        return value.length === 1 ? "0" + value : value;
    };

    WSPWA.dateToYmd = function (date) {
        return date.getFullYear() + "-" + WSPWA.pad2(date.getMonth() + 1) + "-" + WSPWA.pad2(date.getDate());
    };

    WSPWA.today = function () {
        return WSPWA.dateToYmd(new Date());
    };

    WSPWA.addDays = function (date_value, days) {
        var parts = (date_value || WSPWA.today()).split("-");
        var date = new Date(
            parseInt(parts[0], 10),
            parseInt(parts[1], 10) - 1,
            parseInt(parts[2], 10)
        );
        date.setDate(date.getDate() + days);
        return WSPWA.dateToYmd(date);
    };

    WSPWA.humanDate = function (year, month, day) {
        var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        return parseInt(day, 10) + " " + months[parseInt(month, 10) - 1] + " " + year;
    };

    WSPWA.formatDate = function (value) {
        if (!value) { return ""; }
        var match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (match) {
            return WSPWA.humanDate(match[1], match[2], match[3]);
        }
        if (frappe.datetime && frappe.datetime.str_to_user) {
            return frappe.datetime.str_to_user(value);
        }
        return value;
    };

    WSPWA.formatTimeAmPm = function (value) {
        if (!value) { return ""; }
        var parts = String(value).split(/[ T]/);
        if (parts.length < 2) { return ""; }
        var hm = parts[1].split(":");
        var hour = parseInt(hm[0], 10);
        var minute = parseInt(hm[1], 10);
        if (isNaN(hour) || isNaN(minute)) { return ""; }
        var suffix = hour >= 12 ? "PM" : "AM";
        var hour12 = hour % 12;
        if (hour12 === 0) { hour12 = 12; }
        return hour12 + ":" + WSPWA.pad2(minute) + " " + suffix;
    };

    /* "16 Jul 2026 - 3:00 PM" (dash separator) */
    WSPWA.formatDateTime = function (value) {
        var day = WSPWA.formatDate(value);
        var time = WSPWA.formatTimeAmPm(value);
        return [day, time].filter(Boolean).join(" - ");
    };

    /* "16 Jul 2026, 3:00 PM" (comma separator) */
    WSPWA.formatFullDateTime = function (value) {
        var day = WSPWA.formatDate(value);
        var time = WSPWA.formatTimeAmPm(value);
        return [day, time].filter(Boolean).join(", ");
    };

    /* ---------------- Toasts / errors ---------------- */

    WSPWA.toast = function (message, indicator) {
        frappe.show_alert({ message: message, indicator: indicator || "green" });
    };

    WSPWA.error = function (message) {
        frappe.msgprint(message);
    };

    /* ---------------- Session / auth ---------------- */

    WSPWA.isGuest = function () {
        return !!(frappe.session && frappe.session.user === "Guest");
    };

    WSPWA.login = function (options) {
        options = options || {};
        var user = options.user;
        var password = options.password;
        var redirect = options.redirect || window.location.pathname;

        return $.ajax({
            url: "/api/method/login",
            type: "POST",
            data: { usr: user, pwd: password }
        }).done(function () {
            if (options.onSuccess) {
                options.onSuccess();
            } else {
                window.location.href = redirect;
            }
        }).fail(function () {
            if (options.onError) {
                options.onError();
            }
        });
    };

    WSPWA.logout = function (redirect) {
        redirect = redirect || window.location.pathname;
        $.ajax({
            url: "/api/method/logout",
            type: "POST",
            complete: function () {
                window.location.replace(redirect);
            }
        });
    };

    /* ---------------- PWA lifecycle ---------------- */

    WSPWA._installPrompt = null;

    WSPWA.appendHeadTag = function (tag_name, attrs) {
        var tag = document.createElement(tag_name);
        Object.keys(attrs).forEach(function (key) {
            tag.setAttribute(key, attrs[key]);
        });
        document.head.appendChild(tag);
    };

    /* options: { manifest, sw, version, themeColor, appleIcon, installButtonId } */
    WSPWA.setupPwa = function (options) {
        options = options || {};
        var version = options.version || 1;

        if (options.manifest) {
            WSPWA.appendHeadTag("link", { rel: "manifest", href: options.manifest + "?v=" + version });
        }
        WSPWA.appendHeadTag("meta", { name: "theme-color", content: options.themeColor || "#E54B2C" });
        WSPWA.appendHeadTag("meta", { name: "apple-mobile-web-app-capable", content: "yes" });
        WSPWA.appendHeadTag("meta", { name: "apple-mobile-web-app-status-bar-style", content: "default" });
        WSPWA.appendHeadTag("link", { rel: "apple-touch-icon", href: options.appleIcon || "/files/logo%20removed.png" });

        if ("serviceWorker" in navigator && options.sw) {
            navigator.serviceWorker.register(options.sw).catch(function (error) {
                WSPWA.debug("service_worker:error", error);
            });
        }

        window.addEventListener("beforeinstallprompt", function (event) {
            event.preventDefault();
            WSPWA._installPrompt = event;
            if (options.installButtonId) {
                var button = document.getElementById(options.installButtonId);
                if (button) {
                    button.style.display = "block";
                }
            }
        });
    };

    WSPWA.promptInstall = function (installButtonId) {
        if (!WSPWA._installPrompt) {
            frappe.msgprint("Use your browser menu and choose Add to Home Screen.");
            return;
        }
        WSPWA._installPrompt.prompt();
        WSPWA._installPrompt.userChoice.then(function () {
            WSPWA._installPrompt = null;
            if (installButtonId) {
                var button = document.getElementById(installButtonId);
                if (button) {
                    button.style.display = "none";
                }
            }
        });
    };

    /* ---------------- Bottom-nav tab controller ----------------
       options: { shellId, tabs:[...], storageKey, onChange }
       Convention: each tab "x" has panel id "x-panel" and a bottom-nav button
       with data-tab="x". Returns { active, switch(tab), apply(), restore() }.
    */
    WSPWA.setupTabs = function (options) {
        options = options || {};
        var tabs = options.tabs || [];
        var state = { active: tabs[0] };

        function isValid(tab) {
            return tabs.indexOf(tab) !== -1;
        }

        function restore() {
            if (!options.storageKey) { return; }
            try {
                var saved = localStorage.getItem(options.storageKey) || "";
                if (isValid(saved)) { state.active = saved; }
            } catch (e) {
                WSPWA.debug("tabs:restore:error", e);
            }
        }

        function save(tab) {
            if (!options.storageKey) { return; }
            try {
                localStorage.setItem(options.storageKey, tab);
            } catch (e) {
                WSPWA.debug("tabs:save:error", e);
            }
        }

        function apply() {
            var shell = options.shellId ? document.getElementById(options.shellId) : null;
            if (shell) {
                shell.setAttribute("data-active-tab", state.active);
            }
            tabs.forEach(function (tab) {
                var panel = document.getElementById(tab + "-panel");
                var button = document.querySelector('.bottom-nav-button[data-tab="' + tab + '"]');
                if (panel) { panel.classList.toggle("active", state.active === tab); }
                if (button) { button.classList.toggle("active", state.active === tab); }
            });
            if (options.onChange) {
                options.onChange(state.active);
            }
        }

        function switchTo(tab) {
            if (!isValid(tab)) { tab = tabs[0]; }
            state.active = tab;
            save(tab);
            apply();
        }

        restore();

        return {
            get active() { return state.active; },
            switch: switchTo,
            apply: apply,
            restore: restore
        };
    };

    window.WSPWA = WSPWA;
}());
