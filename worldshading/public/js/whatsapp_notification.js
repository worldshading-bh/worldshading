/* WhatsApp Notification is a custom DocType, so its maintained form script is
 * loaded globally and guarded by the button fields installed by the patch. */
frappe.ui.form.on("WhatsApp Notification", {
    refresh: function(frm) {
        if (!frm.fields_dict.button_parameter_field) {
            return;
        }

        frm.set_query("print_format", function() {
            return {filters: {doc_type: frm.doc.reference_doctype}};
        });
    },

    get_fields: function(frm) {
        if (!frm.fields_dict.button_parameter_field) {
            return;
        }
        if (!frm.doc.reference_doctype) {
            frappe.msgprint(__("Please select Doctype first"));
            return;
        }

        frappe.model.with_doctype(frm.doc.reference_doctype, function() {
            var meta = frappe.get_meta(frm.doc.reference_doctype);
            var allowed_types = ["Data", "Phone", "Small Text"];
            var fields = ["<div style='padding:4px'><code>name</code> - Document ID</div>"];

            (meta.fields || []).forEach(function(field) {
                if (field.fieldname && allowed_types.indexOf(field.fieldtype) !== -1) {
                    fields.push("<div style='padding:4px'><code>" +
                        frappe.utils.escape_html(field.fieldname) + "</code> - " +
                        frappe.utils.escape_html(field.label || "") + "</div>");
                }
            });
            frappe.msgprint({title: __("Usable Fields"), message: fields.join(""), wide: true});
        });
    },

    fetch_meta_template: function(frm) {
        if (!frm.fields_dict.button_parameter_field) {
            return;
        }

        frappe.call({
            method: "worldshading.api.whatsapp.fetch_meta_templates",
            freeze: true,
            freeze_message: __("Fetching templates from Meta...")
        }).then(function(response) {
            var templates = response.message || [];
            if (!templates.length) {
                frappe.msgprint(__("No approved templates found"));
                return;
            }

            var escape = frappe.utils.escape_html;
            var html = "<div class='ws-template-list' style='max-height:520px;overflow:auto'>";

            templates.forEach(function(template, index) {
                var buttons = template.buttons || [];
                var preview = escape(template.body || "").replace(/\n/g, "<br>");
                if (template.footer) {
                    preview += "<div style='margin-top:10px;color:#777'>" +
                        escape(template.footer).replace(/\n/g, "<br>") + "</div>";
                }

                var button_html = "";
                buttons.forEach(function(button) {
                    button_html += "<span style='display:inline-block;margin:8px 6px 0 0;" +
                        "padding:4px 9px;border-radius:12px;background:#edf6ff;color:#1769aa'>" +
                        "🔗 " + escape(button.text || __("URL Button")) +
                        (button.dynamic ? " · " + __("Dynamic") : "") + "</span>";
                });

                html += "<div class='ws-template-item' data-index='" + index + "' style='" +
                    "border:1px solid #dfe3e8;padding:12px;margin-bottom:10px;border-radius:7px;" +
                    "cursor:pointer;background:#fff'>" +
                    "<div><b>" + escape(template.name) + "</b> " +
                    "<span style='color:#777'>(" + escape(template.language || "") + ")</span>" +
                    "<span style='float:right;color:#777'>" +
                    escape(template.header_type || "NONE") + "</span></div>" +
                    "<div style='margin-top:9px;line-height:1.55;color:#4b5563'>" + preview + "</div>" +
                    button_html + "</div>";
            });
            html += "</div>";

            var dialog = new frappe.ui.Dialog({
                title: __("Select WhatsApp Template"),
                fields: [{
                    fieldname: "template_list",
                    fieldtype: "HTML",
                    options: html
                }]
            });

            function select_template(index) {
                    var template = templates[index];
                    var dynamic_buttons = (template.buttons || []).filter(function(item) {
                        return item.dynamic;
                    });

                    if (dynamic_buttons.length > 1) {
                        frappe.msgprint(__("This template has multiple dynamic URL buttons. " +
                            "The current notification mapping supports one dynamic URL button."));
                        return;
                    }

                    var button = dynamic_buttons[0] || {};
                    var previous_template = frm.doc.meta_template || "";
                    var previous_button_url = frm.doc.button_url || "";
                    frm.set_value("meta_template", template.name);
                    frm.set_value("template_language", template.language);
                    frm.set_value("header_type", template.header_type || "NONE");
                    frm.set_value("template_preview", template.body +
                        (template.footer ? "\n\n" + template.footer : ""));
                    frm.set_value("button_index", button.index || "");
                    frm.set_value("button_text", button.text || "");
                    frm.set_value("button_url", button.url || "");
                    if (!button.dynamic || previous_template !== template.name ||
                        previous_button_url !== (button.url || "")) {
                        frm.set_value("button_parameter_field", "");
                    }
                    dialog.hide();
            }

            dialog.show();
            dialog.$wrapper.find(".ws-template-item").on("click", function() {
                select_template(parseInt($(this).attr("data-index"), 10));
            }).on("mouseenter", function() {
                $(this).css({"border-color": "#5e64ff", "background": "#f8f9ff"});
            }).on("mouseleave", function() {
                $(this).css({"border-color": "#dfe3e8", "background": "#fff"});
            });
        });
    }
});
