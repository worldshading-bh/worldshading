# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, now
from six import string_types


CHANNEL_OPTIONS = ("Call", "WhatsApp", "SMS", "Email", "Visit")
OUTCOME_OPTIONS = (
	"No Answer", "Busy", "Call Back Later", "Message Sent", "Replied",
	"Interested", "Not Interested", "Wrong Number", "Visit Scheduled",
	"Order Confirmed", "Other",
)
STATUS_OPTIONS = (
	"Planned", "Follow Up", "Interested", "Not Interested", "Converted", "Closed",
)
NEXT_ACTION_OPTIONS = ("Call", "WhatsApp", "SMS", "Email", "Visit", "None")
FOLLOW_UP_REQUIRED_STATUSES = ("Follow Up", "Interested")
PRIORITY_OPTIONS = ("Standard", "Top 20")
MAX_BULK_CUSTOMERS = 250


class CampaignCustomer(Document):

	def validate(self):
		set_missing_contact_details(self)
		set_campaign_customer_key(self)
		validate_unique_campaign_customer(self)
		update_interaction_summary(self)
		validate_opportunity_customer(self)


def set_missing_contact_details(doc):
	if not doc.get("customer"):
		return
	if all(doc.get(fieldname) for fieldname in (
		"contact_person", "mobile_number", "whatsapp_number", "email_address"
	)):
		return

	customer = frappe.db.get_value(
		"Customer",
		doc.customer,
		["customer_primary_contact", "mobile_no", "email_id"],
		as_dict=True
	) or frappe._dict()

	if not doc.get("contact_person") and customer.get("customer_primary_contact"):
		doc.contact_person = customer.get("customer_primary_contact")

	contact = frappe._dict()
	if doc.get("contact_person"):
		contact = frappe.db.get_value(
			"Contact",
			doc.contact_person,
			["mobile_no", "phone", "email_id"],
			as_dict=True
		) or frappe._dict()

	if not doc.get("mobile_number"):
		doc.mobile_number = (
			contact.get("mobile_no") or contact.get("phone") or customer.get("mobile_no")
		)
	if not doc.get("whatsapp_number"):
		doc.whatsapp_number = contact.get("mobile_no") or customer.get("mobile_no")
	if not doc.get("email_address"):
		doc.email_address = contact.get("email_id") or customer.get("email_id")


def set_campaign_customer_key(doc):
	value = "{0}\n{1}".format(doc.campaign, doc.customer)
	doc.campaign_customer_key = hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_unique_campaign_customer(doc):
	filters = {
		"campaign": doc.campaign,
		"customer": doc.customer
	}
	if doc.get("name"):
		filters["name"] = ["!=", doc.name]

	existing = frappe.db.get_value("Campaign Customer", filters, "name")
	if existing:
		frappe.throw(_(
			"Customer {0} is already included in Campaign {1} as {2}."
		).format(doc.customer, doc.campaign, existing))


def update_interaction_summary(doc):
	interactions = list(doc.get("interactions") or [])
	doc.number_of_interactions = len(interactions)

	dated_interactions = []
	for row in interactions:
		if not row.get("interaction_on"):
			continue
		interaction_datetime = get_datetime(row.get("interaction_on"))
		dated_interactions.append((interaction_datetime, row))

	if dated_interactions:
		latest_row = max(dated_interactions, key=lambda value: value[0])[1]
		doc.last_contact_on = latest_row.get("interaction_on")
		doc.last_outcome = latest_row.get("outcome")
		doc.latest_note = latest_row.get("notes")
		doc.next_follow_up = latest_row.get("next_follow_up")
	else:
		doc.last_contact_on = None
		doc.last_outcome = None
		doc.latest_note = None


def _validate_contact_option(label, value, options, allow_blank=False):
	if allow_blank and not value:
		return
	if value not in options:
		frappe.throw(_("Invalid {0}: {1}").format(label, value or _("Blank")))


@frappe.whitelist()
def record_contact(name, channel, outcome, notes, status, next_follow_up=None,
		next_action=None):
	_validate_contact_option(_("Channel"), channel, CHANNEL_OPTIONS)
	_validate_contact_option(_("Outcome"), outcome, OUTCOME_OPTIONS)
	_validate_contact_option(_("Status"), status, STATUS_OPTIONS)
	_validate_contact_option(
		_("Next Action"), next_action, NEXT_ACTION_OPTIONS, allow_blank=True
	)

	if not isinstance(notes, string_types) or not notes.strip():
		frappe.throw(_("Notes are required."))
	notes = notes.strip()
	if status in FOLLOW_UP_REQUIRED_STATUSES and not next_follow_up:
		frappe.throw(_("Next Follow-up is required when Status is {0}.").format(status))

	doc = frappe.get_doc("Campaign Customer", name)
	doc.check_permission("write")
	doc.append("interactions", {
		"interaction_on": now(),
		"channel": channel,
		"handled_by": frappe.session.user,
		"outcome": outcome,
		"notes": notes,
		"next_follow_up": next_follow_up or None,
	})
	doc.status = status
	doc.next_action = next_action or None
	doc.save()

	return {
		"name": doc.name,
		"status": doc.status,
		"last_contact_on": doc.last_contact_on,
		"last_outcome": doc.last_outcome,
		"latest_note": doc.latest_note,
		"next_follow_up": doc.next_follow_up,
		"number_of_interactions": doc.number_of_interactions,
	}


@frappe.whitelist()
def bulk_create_campaign_customers(campaign, customers, caller,
		planned_contact_date, priority="Standard", batch_size=10):
	if not frappe.has_permission("Campaign Customer", "create"):
		frappe.throw(_("You do not have permission to create Campaign Customers."))

	customers = frappe.parse_json(customers) or []
	if not campaign:
		frappe.throw(_("Campaign is required."))
	if not caller:
		frappe.throw(_("Caller is required."))
	if not planned_contact_date:
		frappe.throw(_("Planned Contact Date is required."))
	if priority not in PRIORITY_OPTIONS:
		frappe.throw(_("Invalid Priority: {0}").format(priority or _("Blank")))
	if not isinstance(customers, (list, tuple)) or not customers:
		frappe.throw(_("At least one Customer is required."))
	if len(customers) > MAX_BULK_CUSTOMERS:
		frappe.throw(_("A maximum of {0} Customers can be processed at once.").format(
			MAX_BULK_CUSTOMERS
		))

	batch_size = cint(batch_size)
	if batch_size < 1 or batch_size > MAX_BULK_CUSTOMERS:
		frappe.throw(_("Batch Size must be between 1 and {0}.").format(
			MAX_BULK_CUSTOMERS
		))

	ordered_customers = []
	seen = set()
	for customer in customers:
		if not isinstance(customer, string_types) or not customer.strip():
			frappe.throw(_("Each Customer must be a valid Customer code."))
		if customer in seen:
			continue
		seen.add(customer)
		ordered_customers.append(customer)

	existing_rows = frappe.get_all(
		"Campaign Customer",
		filters={
			"campaign": campaign,
			"customer": ["in", ordered_customers],
		},
		fields=["customer"]
	)
	existing_customers = set(row.get("customer") for row in existing_rows)
	created = []
	skipped = []
	for customer in ordered_customers:
		if customer in existing_customers:
			skipped.append(customer)
			continue
		if len(created) >= batch_size:
			break
		doc = frappe.get_doc({
			"doctype": "Campaign Customer",
			"campaign": campaign,
			"customer": customer,
			"caller": caller,
			"planned_contact_date": planned_contact_date,
			"priority": priority,
			"status": "Planned",
		})
		doc.insert()
		created.append(doc.name)

	return {
		"created": created,
		"created_count": len(created),
		"skipped": skipped,
		"skipped_count": len(skipped),
	}


def validate_opportunity_customer(doc):
	if not doc.get("opportunity"):
		return

	opportunity = frappe.db.get_value(
		"Opportunity",
		doc.opportunity,
		["opportunity_from", "party_name"],
		as_dict=True
	)
	if not opportunity:
		frappe.throw(_("Opportunity {0} does not exist.").format(doc.opportunity))
	if opportunity.opportunity_from != "Customer":
		frappe.throw(_(
			"Opportunity {0} must be based on a Customer."
		).format(doc.opportunity))
	if opportunity.party_name != doc.customer:
		frappe.throw(_(
			"Opportunity {0} belongs to Customer {1}, not Customer {2}."
		).format(doc.opportunity, opportunity.party_name, doc.customer))
