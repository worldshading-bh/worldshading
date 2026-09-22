# -*- coding: utf-8 -*-
"""Quotation payment requests and unallocated customer advances.

ERPNext v12 does not treat Quotation as an accounting reference.  This module
keeps it that way: the Payment Request points to the Quotation for collection,
while the resulting Payment Entry has an empty references table.
"""
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, getdate, now_datetime, nowdate

from erpnext.accounts.doctype.payment_request import payment_request as core_payment_request
from erpnext.accounts.party import get_party_account
from erpnext.accounts.utils import get_account_currency


INVALID_QUOTATION_STATUSES = ("Lost", "Expired", "Ordered", "Cancelled")


def quotation_total(quotation):
	return flt(quotation.get("rounded_total") or quotation.get("grand_total"))


def install_quotation_amount_support(doc, method=None):
	"""Teach this v12 process the Quotation amount before core validation runs."""
	if doc.get("reference_doctype") != "Quotation":
		return

	current = core_payment_request.get_amount
	if getattr(current, "_worldshading_supports_quotation", False):
		return

	def get_amount(reference_doc):
		if reference_doc.doctype == "Quotation":
			amount = quotation_total(reference_doc)
			if amount > 0:
				return amount
			frappe.throw(_("Quotation amount must be greater than zero."))
		return current(reference_doc)

	get_amount._worldshading_supports_quotation = True
	core_payment_request.get_amount = get_amount


def validate_quotation(quotation):
	if quotation.docstatus != 1:
		frappe.throw(_("Only a submitted Quotation can be used for a payment request."))
	if quotation.get("quotation_to") != "Customer":
		frappe.throw(_("Only a customer Quotation can be used for a payment request."))
	if quotation.get("status") in INVALID_QUOTATION_STATUSES:
		frappe.throw(_("Payment cannot be requested for a {0} Quotation.").format(
			quotation.get("status")
		))
	if not quotation.get("party_name"):
		frappe.throw(_("Quotation Customer is required."))
	if not quotation.get("company") or not quotation.get("currency"):
		frappe.throw(_("Quotation Company and Currency are required."))
	if quotation_total(quotation) <= 0:
		frappe.throw(_("Quotation amount must be greater than zero."))


def submitted_request_total(quotation_name, exclude=None):
	filters = {
		"reference_doctype": "Quotation",
		"reference_name": quotation_name,
		"docstatus": 1,
	}
	if exclude:
		filters["name"] = ("!=", exclude)

	return sum(flt(row.grand_total) for row in frappe.get_all(
		"Payment Request", filters=filters, fields=["grand_total"]
	))


@frappe.whitelist()
def get_available_amount(quotation):
	quotation_doc = frappe.get_doc("Quotation", quotation)
	quotation_doc.check_permission("read")
	validate_quotation(quotation_doc)

	precision = frappe.get_precision("Payment Request", "grand_total") or 3
	available = flt(
		quotation_total(quotation_doc) - submitted_request_total(quotation_doc.name),
		precision,
	)
	return {
		"amount": max(available, 0),
		"currency": quotation_doc.currency,
	}


def validate_quotation_payment_request(doc, method=None):
	"""Recheck the cumulative amount when staff submits the draft request."""
	if doc.get("reference_doctype") != "Quotation":
		return

	# Submission must be serialized per Quotation. Without a row lock, two drafts
	# submitted concurrently could both see the same available amount.
	frappe.db.sql(
		"select name from `tabQuotation` where name = %s for update",
		doc.reference_name,
	)
	quotation = frappe.get_doc("Quotation", doc.reference_name)
	validate_quotation(quotation)

	if doc.get("payment_request_type") != "Inward":
		frappe.throw(_("A Quotation Payment Request must be Inward."))
	if doc.get("party_type") != "Customer" or doc.get("party") != quotation.party_name:
		frappe.throw(_("Payment Request Customer must match the Quotation Customer."))
	if doc.get("currency") != quotation.currency:
		frappe.throw(_("Payment Request Currency must match the Quotation Currency."))

	precision = frappe.get_precision("Payment Request", "grand_total") or 3
	requested = flt(doc.get("grand_total"), precision)
	total = flt(quotation_total(quotation), precision)
	already_requested = flt(submitted_request_total(quotation.name, doc.name), precision)

	if requested <= 0:
		frappe.throw(_("Payment Request amount must be greater than zero."))
	if flt(already_requested + requested, precision) > total:
		frappe.throw(_(
			"Submitted Payment Requests would total {0}, above Quotation {1}'s total of {2}."
		).format(already_requested + requested, quotation.name, total))


@frappe.whitelist()
def create_draft_payment_request(quotation, amount, recipient_id=None):
	frappe.has_permission("Payment Request", "create", throw=True)
	quotation_doc = frappe.get_doc("Quotation", quotation)
	quotation_doc.check_permission("read")
	validate_quotation(quotation_doc)

	precision = frappe.get_precision("Payment Request", "grand_total") or 3
	amount = flt(amount, precision)
	available = flt(
		quotation_total(quotation_doc) - submitted_request_total(quotation_doc.name),
		precision,
	)
	if amount <= 0:
		frappe.throw(_("Payment Request amount must be greater than zero."))
	if amount > available:
		frappe.throw(_("Only {0} remains available to request.").format(available))

	# Prevent a UI double-click from producing an identical draft. Legitimate later
	# partial requests are unaffected because submitted requests are never reused.
	existing = frappe.db.get_value(
		"Payment Request",
		{
			"reference_doctype": "Quotation",
			"reference_name": quotation_doc.name,
			"grand_total": amount,
			"docstatus": 0,
			"owner": frappe.session.user,
			"creation": (">=", add_to_date(now_datetime(), seconds=-30)),
		},
		"name",
	)
	if existing:
		return {"name": existing, "reused": True}

	gateway = core_payment_request.get_payment_gateway_account({"is_default": 1}) or frappe._dict()
	payment_request = frappe.new_doc("Payment Request")
	payment_request.update({
		"transaction_date": quotation_doc.get("transaction_date") or nowdate(),
		"payment_gateway_account": gateway.get("name"),
		"payment_gateway": gateway.get("payment_gateway"),
		"payment_account": gateway.get("payment_account"),
		"payment_request_type": "Inward",
		"currency": quotation_doc.currency,
		"grand_total": amount,
		"email_to": recipient_id or quotation_doc.get("contact_email"),
		"subject": _("Payment Request for {0}").format(quotation_doc.name),
		"message": gateway.get("message") or core_payment_request.get_dummy_message(quotation_doc),
		"reference_doctype": "Quotation",
		"reference_name": quotation_doc.name,
		"party_type": "Customer",
		"party": quotation_doc.party_name,
	})
	payment_request.insert()
	return {"name": payment_request.name, "reused": False}


def validate_transaction_for_quotation(payment_request, txn):
	quotation = frappe.get_doc("Quotation", payment_request.reference_name)
	# At this point the bank has already captured the money. Record it even if the
	# Quotation became Lost/Expired/Ordered after the customer opened checkout.
	if quotation.docstatus != 1 or quotation.get("quotation_to") != "Customer":
		frappe.throw(_("Payment Request must reference a submitted customer Quotation."))
	if quotation.party_name != payment_request.party:
		frappe.throw(_("Payment Request Customer must match the Quotation Customer."))

	precision = frappe.get_precision("Payment Request", "grand_total") or 3
	if txn.currency != payment_request.currency:
		frappe.throw(_("Gateway transaction currency does not match the Payment Request."))
	if flt(txn.amount, precision) != flt(payment_request.grand_total, precision):
		frappe.throw(_("Gateway transaction amount does not match the Payment Request."))
	return quotation


def create_advance_payment_entry(payment_request, txn):
	"""Create a submitted advance with no accounting-document allocation."""
	quotation = validate_transaction_for_quotation(payment_request, txn)
	if not frappe.get_meta("Payment Entry").has_field("quotation"):
		frappe.throw(_("Payment Entry Quotation field is not installed."))

	from worldshading.payments.gateways import deposit_account
	from worldshading.payments.utils import gateway_mode_of_payment

	party_account = get_party_account("Customer", quotation.party_name, quotation.company)
	bank_account = deposit_account(txn.gateway)
	if not bank_account:
		frappe.throw(_("No deposit account is configured for gateway {0}.").format(txn.gateway))

	party_currency = get_account_currency(party_account)
	bank_currency = get_account_currency(bank_account)
	if frappe.db.get_value("Account", bank_account, "company") != quotation.company:
		frappe.throw(_("Gateway deposit account Company must match the Quotation Company."))
	if party_currency != payment_request.currency:
		frappe.throw(_("Customer receivable account currency must match the Payment Request."))
	if bank_currency != payment_request.currency:
		frappe.throw(_("Gateway deposit account currency must match the Payment Request."))

	payment_entry = frappe.new_doc("Payment Entry")
	payment_entry.update({
		"payment_type": "Receive",
		"company": quotation.company,
		"posting_date": nowdate(),
		"party_type": "Customer",
		"party": quotation.party_name,
		"paid_from": party_account,
		"paid_to": bank_account,
		"paid_from_account_currency": party_currency,
		"paid_to_account_currency": bank_currency,
		"paid_amount": payment_request.grand_total,
		"received_amount": payment_request.grand_total,
		"source_exchange_rate": 1,
		"target_exchange_rate": 1,
		"mode_of_payment": gateway_mode_of_payment(txn.gateway),
		"reference_no": payment_request.name,
		"reference_date": nowdate(),
		"quotation": quotation.name,
		"remarks": "Customer advance for Quotation {0} via Payment Request {1}".format(
			quotation.name, payment_request.name
		),
	})
	payment_entry.set("references", [])
	payment_entry.insert(ignore_permissions=True)
	payment_entry.submit()
	return payment_entry


def create_draft_sales_order_if_missing(quotation_name):
	"""Create one draft Sales Order from a paid Quotation, idempotently."""
	# Serialize automatic creation per Quotation. A customer can pay two partial
	# requests close together, but only the first settlement may create the order.
	frappe.db.sql(
		"select name from `tabQuotation` where name = %s for update",
		quotation_name,
	)
	quotation = frappe.get_doc("Quotation", quotation_name)

	if quotation.docstatus != 1 or quotation.get("quotation_to") != "Customer":
		frappe.throw(_("Sales Order requires a submitted customer Quotation."))
	if quotation.get("status") in ("Lost", "Expired", "Cancelled"):
		frappe.throw(_("Sales Order cannot be created from a {0} Quotation.").format(
			quotation.get("status")
		))
	if quotation.get("valid_till") and getdate(quotation.valid_till) < getdate(nowdate()):
		frappe.throw(_("Validity period of Quotation {0} has ended.").format(quotation.name))

	# This must also be a locking/current read. A normal frappe.get_all() uses the
	# transaction's repeatable-read snapshot; a second callback that started before
	# the first committed could therefore miss the newly inserted Sales Order even
	# after waiting for the Quotation lock.
	existing = frappe.db.sql(
		"""
			select so.name as parent
			from `tabSales Order` so
			inner join `tabSales Order Item` soi on soi.parent = so.name
			where soi.parenttype = 'Sales Order'
				and soi.prevdoc_docname = %s
				and so.docstatus < 2
			limit 1
			for update
		""",
		quotation.name,
		as_dict=True,
	)
	if existing:
		return existing[0].parent

	from erpnext.selling.doctype.quotation.quotation import _make_sales_order

	sales_order = _make_sales_order(quotation.name, ignore_permissions=True)
	sales_order.transaction_date = nowdate()
	sales_order.delivery_date = nowdate()

	warehouse = quotation.get("set_warehouse") or frappe.db.get_value(
		"Warehouse",
		{
			"is_default_warehouse": 1,
			"company": quotation.company,
			"disabled": 0,
			"is_group": 0,
		},
		"name",
	)
	if not warehouse:
		frappe.throw(_(
			"Quotation {0} has no Set Warehouse and no default Warehouse is configured "
			"for company {1}."
		).format(quotation.name, quotation.company))
	warehouse_details = frappe.db.get_value(
		"Warehouse", warehouse, ["company", "disabled", "is_group"], as_dict=True
	)
	if (
		not warehouse_details
		or warehouse_details.company != quotation.company
		or warehouse_details.disabled
		or warehouse_details.is_group
	):
		frappe.throw(_(
			"Warehouse {0} must be an enabled, non-group Warehouse for company {1}."
		).format(warehouse, quotation.company))

	if sales_order.meta.has_field("set_warehouse"):
		sales_order.set_warehouse = warehouse
	for item in sales_order.get("items") or []:
		if not item.get("delivery_date"):
			item.delivery_date = sales_order.delivery_date
		if not item.get("warehouse"):
			item.warehouse = warehouse
	sales_order.flags.ignore_permissions = True
	sales_order.insert(ignore_permissions=True)

	# ERPNext v12 requires a new workflow document to enter through the first
	# workflow state. This system-created order exists only after an advance is
	# captured, so record that fact after the normal Draft insert without changing
	# docstatus or ERPNext's standard Sales Order status.
	sales_order.db_set(
		"workflow_state",
		"Draft - Advance Paid",
		update_modified=False,
	)

	return sales_order.name
