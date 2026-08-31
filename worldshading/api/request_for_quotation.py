from __future__ import unicode_literals

import re

import frappe
from frappe import _
from frappe.core.doctype.communication.email import make
from frappe.utils import cint, flt, validate_email_address


SUPPLIER_ITEM_GROUP_FIELD = "supplier_item_group"
SUPPLIER_ITEM_GROUP_DOCTYPE = "Supplier Item Group"


def set_total_quantity(doc, method=None):
	"""Set the RFQ total quantity from its item rows before save."""
	doc.total_quantity = sum(flt(row.qty) for row in (doc.items or []))


@frappe.whitelist()
def block_standard_supplier_email_send(rfq_name=None):
	"""Prevent the core RFQ sender from creating supplier portal users."""
	frappe.throw(_(
		"Direct supplier sending is disabled. Refresh the RFQ and use the "
		"Review Supplier Emails dialog."
	))


@frappe.whitelist()
def send_supplier_emails_with_review(
	rfq_name, sender, recipients, subject, message, email_template=None,
	send_me_a_copy=0, read_receipt=0, attach_document_print=1,
	print_format=None, language=None, selected_attachments=None
):
	"""Send reviewed RFQ email separately without creating portal users."""
	rfq = frappe.get_doc("Request for Quotation", rfq_name)
	rfq.check_permission("write")

	if rfq.docstatus != 1:
		frappe.throw(_("Only submitted Requests for Quotation can be emailed."))

	sender = _validate_outgoing_sender(sender)
	subject = (subject or "").strip()
	message = message or ""
	if not subject:
		frappe.throw(_("Email Subject is required."))
	if not message.strip():
		frappe.throw(_("Email Message is required."))
	recipients = _get_reviewed_recipients(recipients)
	attachment_names = _get_selected_attachments(rfq, selected_attachments)
	suppliers_by_email = {}
	for supplier in rfq.suppliers:
		if supplier.email_id:
			suppliers_by_email.setdefault(
				supplier.email_id.strip().lower(), []
			).append(supplier)

	sent_recipients = []
	for recipient in recipients:
		matching_suppliers = suppliers_by_email.get(recipient.lower(), [])
		context = matching_suppliers[0].as_dict() \
			if matching_suppliers else rfq.as_dict()
		content = frappe.render_template(message, context)
		attachments = list(attachment_names)
		if cint(attach_document_print):
			attachments.append(frappe.attach_print(
				rfq.doctype,
				rfq.name,
				print_format=print_format,
				doc=rfq,
				lang=language,
			))

		make(
			subject=subject,
			content=content,
			recipients=recipient,
			sender=sender,
			attachments=attachments,
			send_me_a_copy=cint(send_me_a_copy),
			read_receipt=cint(read_receipt),
			email_template=email_template,
			send_email=True,
			doctype=rfq.doctype,
			name=rfq.name,
		)

		for supplier in matching_suppliers:
			frappe.db.set_value(
				supplier.doctype, supplier.name, "email_sent", 1,
				update_modified=False
			)
		sent_recipients.append(recipient)

	return {
		"sent_count": len(sent_recipients),
		"recipients": sent_recipients,
	}


def _get_reviewed_recipients(recipients):
	parts = re.split(r"[,;\n\r]+", recipients or "")
	validated = []
	seen = set()
	for part in parts:
		part = part.strip()
		if not part:
			continue
		email_id = validate_email_address(part, throw=True)
		if not email_id or email_id.lower() in seen:
			continue
		seen.add(email_id.lower())
		validated.append(email_id)

	if not validated:
		frappe.throw(_("At least one valid recipient Email Address is required."))
	if len(validated) > 50:
		frappe.throw(_("A maximum of 50 recipients can be used at one time."))

	return validated


def _get_selected_attachments(rfq, selected_attachments):
	selected_attachments = frappe.parse_json(selected_attachments) \
		if selected_attachments else []
	selected_attachments = list(set(selected_attachments or []))
	if not selected_attachments:
		return []

	files = frappe.get_all(
		"File",
		filters={
			"name": ("in", selected_attachments),
			"attached_to_doctype": rfq.doctype,
			"attached_to_name": rfq.name,
		},
		fields=["name"],
	)
	valid_names = [row.name for row in files]
	if len(valid_names) != len(selected_attachments):
		frappe.throw(_("One or more selected attachments do not belong to this RFQ."))

	return valid_names


def _validate_outgoing_sender(sender):
	sender = (sender or "").strip()
	if not sender:
		frappe.throw(_("From Email Account is required."))

	account = frappe.db.get_value(
		"Email Account",
		{"email_id": sender, "enable_outgoing": 1, "awaiting_password": 0},
		"name"
	)
	if not account:
		frappe.throw(_("The selected From Email Account is not available."))

	linked_account = frappe.db.get_value(
		"User Email",
		{
			"parent": frappe.session.user,
			"parenttype": "User",
			"email_account": account,
			"enable_outgoing": 1,
		},
		"name"
	)
	if not linked_account:
		frappe.throw(_("You are not permitted to send from {0}.").format(sender))

	return sender


def _get_last_purchase_details(item_codes, company=None):
	"""Return latest submitted Purchase Invoice details per Item."""
	item_codes = list(set([item_code for item_code in item_codes if item_code]))
	if not item_codes:
		return {}

	query_values = {"item_codes": tuple(item_codes)}
	company_condition = ""
	if company:
		company_condition = "AND pi.company = %(company)s"
		query_values["company"] = company

	# A single joined query is intentional. Purchase Invoice posting details live
	# on the parent while cost and conversion factor live on the child row.
	rows = frappe.db.sql("""
		SELECT
			pii.item_code,
			pi.supplier,
			pi.currency,
			pii.net_rate,
			pii.base_net_rate,
			pii.conversion_factor
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi
			ON pi.name = pii.parent
		WHERE
			pi.docstatus = 1
			AND pii.item_code IN %(item_codes)s
			{company_condition}
		ORDER BY
			pii.item_code ASC,
			pi.posting_date DESC,
			pi.creation DESC,
			pii.idx DESC
	""".format(company_condition=company_condition), query_values, as_dict=1)

	details = {}
	for row in rows:
		if row.item_code in details:
			continue
		conversion_factor = flt(row.conversion_factor)
		if not conversion_factor:
			continue
		details[row.item_code] = {
			"base_rate": flt(row.base_net_rate) / conversion_factor,
			"supplier": row.supplier,
			"rate": flt(row.net_rate) / conversion_factor,
			"currency": row.currency
		}
	return details


def set_last_purchase_details(doc, method=None):
	"""Refresh latest Purchase Invoice details on RFQ Items before save."""
	item_meta = frappe.get_meta("Request for Quotation Item")
	has_base_rate_field = item_meta.has_field("last_purchase_base_rate")
	has_supplier_field = item_meta.has_field("last_purchase_supplier")
	has_rate_field = item_meta.has_field("last_purchase_rate")
	has_currency_field = item_meta.has_field("last_purchase_currency")
	if not any([
			has_base_rate_field, has_supplier_field,
			has_rate_field, has_currency_field]):
		return

	items = [row for row in (doc.items or []) if row.item_code]
	if not items:
		return

	company = doc.get("company") \
		or frappe.defaults.get_user_default("Company") \
		or frappe.db.get_single_value("Global Defaults", "default_company")
	details = _get_last_purchase_details(
		[row.item_code for row in items], company)

	for row in items:
		detail = details.get(row.item_code, {})
		if has_base_rate_field:
			row.last_purchase_base_rate = detail.get("base_rate")
		if has_supplier_field:
			row.last_purchase_supplier = detail.get("supplier")
		if has_rate_field:
			row.last_purchase_rate = detail.get("rate")
		if has_currency_field:
			row.last_purchase_currency = detail.get("currency")


def _as_list(value):
	if not value:
		return []
	if isinstance(value, (list, tuple)):
		return list(value)
	return frappe.parse_json(value) or []


def _get_item_groups(item_codes):
	item_codes = list(set([code for code in _as_list(item_codes) if code]))
	if not item_codes:
		return []

	items = frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=["item_group"]
	)
	item_groups = set([row.item_group for row in items if row.item_group])
	return list(_with_parent_item_groups(item_groups))


def _get_direct_item_groups(item_codes):
	item_codes = list(set([code for code in _as_list(item_codes) if code]))
	if not item_codes:
		return []

	items = frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=["item_group"]
	)
	return sorted(set([row.item_group for row in items if row.item_group]))


def _with_parent_item_groups(item_groups):
	"""Return the selected Item Groups together with every ancestor group."""
	groups = set(item_groups or [])
	frontier = set(groups)

	while frontier:
		parents = frappe.get_all(
			"Item Group",
			filters={"name": ["in", list(frontier)]},
			fields=["parent_item_group"]
		)
		frontier = set([
			row.parent_item_group for row in parents
			if row.parent_item_group and row.parent_item_group not in groups
		])
		groups.update(frontier)

	return groups


def _get_matching_suppliers(item_codes, country_of_purchase=None):
	item_groups = _get_item_groups(item_codes)
	if not item_groups:
		return [], item_groups

	rows = frappe.get_all(
		SUPPLIER_ITEM_GROUP_DOCTYPE,
		filters={
			"parenttype": "Supplier",
			"parentfield": SUPPLIER_ITEM_GROUP_FIELD,
			"item_group": ["in", item_groups]
		},
		fields=["parent", "priority"]
	)

	priority_by_supplier = {}
	for row in rows:
		priority = cint(row.priority)
		priority = priority if priority > 0 else 999999
		if row.parent not in priority_by_supplier:
			priority_by_supplier[row.parent] = priority
		else:
			priority_by_supplier[row.parent] = min(
				priority_by_supplier[row.parent], priority)

	if not priority_by_supplier:
		return [], item_groups

	# get_list is intentional: unlike get_all, it applies the current user's
	# Supplier permission query conditions.
	supplier_filters = {
		"name": ["in", list(priority_by_supplier)],
		"disabled": 0,
		"prevent_rfqs": 0
	}
	if country_of_purchase:
		supplier_filters["country"] = country_of_purchase

	suppliers = frappe.get_list(
		"Supplier",
		filters=supplier_filters,
		fields=["name", "supplier_name"],
		limit_page_length=0
	)

	for supplier in suppliers:
		supplier.priority = priority_by_supplier.get(supplier.name, 999999)

	suppliers.sort(key=lambda row: (
		row.priority,
		(row.supplier_name or row.name).lower()
	))
	return suppliers, item_groups


@frappe.whitelist()
def get_suppliers_for_items(item_codes=None, country_of_purchase=None):
	suppliers, item_groups = _get_matching_suppliers(
		item_codes, country_of_purchase)
	return {
		"suppliers": suppliers,
		"item_groups": item_groups
	}


def validate_supplier_item_groups(doc, method=None):
	"""Block RFQ save when a supplier cannot supply any RFQ Item Group."""
	item_codes = [row.item_code for row in (doc.items or []) if row.item_code]
	direct_item_groups = _get_direct_item_groups(item_codes)
	matching_item_groups = set(_with_parent_item_groups(direct_item_groups))
	supplier_names = list(set([
		row.supplier for row in (doc.suppliers or []) if row.supplier
	]))

	# Core RFQ validation handles missing items and suppliers. Avoid replacing its
	# standard messages when this custom rule has nothing meaningful to compare.
	if not direct_item_groups or not supplier_names:
		return

	specializations = frappe.get_all(
		SUPPLIER_ITEM_GROUP_DOCTYPE,
		filters={
			"parenttype": "Supplier",
			"parentfield": SUPPLIER_ITEM_GROUP_FIELD,
			"parent": ["in", supplier_names]
		},
		fields=["parent", "item_group"]
	)
	groups_by_supplier = {}
	for row in specializations:
		groups_by_supplier.setdefault(row.parent, set()).add(row.item_group)

	supplier_details = frappe.get_all(
		"Supplier",
		filters={"name": ["in", supplier_names]},
		fields=["name", "supplier_name", "country"]
	)
	details_by_supplier = dict((row.name, row) for row in supplier_details)

	invalid_suppliers = []
	for supplier in supplier_names:
		configured_groups = groups_by_supplier.get(supplier, set())
		details = details_by_supplier.get(supplier) or frappe._dict()
		item_group_matches = bool(
			configured_groups.intersection(matching_item_groups))
		country_matches = bool(
			not doc.country_of_purchase or details.country == doc.country_of_purchase)
		if item_group_matches and country_matches:
			continue

		supplier_name = details.supplier_name or supplier
		configured_text = ", ".join(sorted(configured_groups)) \
			if configured_groups else _("None configured")
		invalid_suppliers.append({
			"supplier_id": supplier,
			"supplier": supplier_name,
			"rfq_item_groups": ", ".join(direct_item_groups),
			"configured_groups": configured_text,
			"item_group_matches": item_group_matches,
			"expected_country": doc.country_of_purchase,
			"country": details.country or _("Not set"),
			"country_matches": country_matches
		})

	if invalid_suppliers:
		message = [
			_("The supplier(s) below cannot provide the items in this RFQ:")
		]
		for index, invalid in enumerate(invalid_suppliers, 1):
			supplier_link = frappe.utils.get_link_to_form(
				"Supplier", invalid["supplier_id"], invalid["supplier"])
			lines = ["{0}. <b>{1}:</b> {2}".format(
				index, _("Supplier"), supplier_link)]
			if not invalid["item_group_matches"]:
				lines.append("&nbsp;&nbsp;&nbsp;<b>{0}:</b> {1} ({2}: {3})".format(
					_("Item Group mismatch"), invalid["configured_groups"],
					_("RFQ requires"), invalid["rfq_item_groups"]))
			if not invalid["country_matches"]:
				lines.append("&nbsp;&nbsp;&nbsp;<b>{0}:</b> {1} ({2}: {3})".format(
					_("Country mismatch"), invalid["country"],
					_("RFQ requires"), invalid["expected_country"]))
			message.append("<br>".join(lines))
		message.append(
			_("Update the Supplier specialization or Country "
			  "so it matches the RFQ filters.")
		)
		frappe.throw(
			"<br><br>".join(message),
			title=_("Supplier Does Not Match RFQ")
		)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def supplier_query(doctype, txt, searchfield, start, page_len, filters):
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	item_codes = filters.get("item_codes")
	suppliers, _item_groups = _get_matching_suppliers(
		item_codes,
		filters.get("country_of_purchase")
	)

	# Before items are entered, retain normal lookup while honoring any optional
	# RFQ filters. Once items exist, Item Group matching remains mandatory.
	if not suppliers and not _as_list(item_codes):
		fallback_filters = {
			"disabled": 0,
			"prevent_rfqs": 0,
			"name": ["like", "%%%s%%" % txt]
		}
		if filters.get("country_of_purchase"):
			fallback_filters["country"] = filters.get("country_of_purchase")
		return frappe.get_list(
			"Supplier",
			filters=fallback_filters,
			fields=["name", "supplier_name"],
			limit_start=start,
			limit_page_length=page_len,
			as_list=True
		)

	txt = (txt or "").lower()
	matched = [row for row in suppliers if
		txt in row.name.lower() or txt in (row.supplier_name or "").lower()]
	return [[row.name, row.supplier_name] for row in matched[start:start + page_len]]
