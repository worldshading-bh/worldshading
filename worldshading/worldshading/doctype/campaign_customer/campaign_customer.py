# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now


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


class CampaignCustomer(Document):

	def validate(self):
		set_campaign_customer_key(self)
		validate_unique_campaign_customer(self)
		update_interaction_summary(self)
		validate_opportunity_customer(self)


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

	notes = (notes or "").strip()
	if not notes:
		frappe.throw(_("Notes are required."))
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
