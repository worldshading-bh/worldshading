# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


class CampaignCustomer(Document):

	def validate(self):
		validate_unique_campaign_customer(self)
		update_interaction_summary(self)
		validate_opportunity_customer(self)


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
	follow_up_interactions = []
	for row in interactions:
		if not row.get("interaction_on"):
			continue
		interaction_datetime = get_datetime(row.get("interaction_on"))
		dated_interactions.append((interaction_datetime, row))
		if row.get("next_follow_up"):
			follow_up_interactions.append((interaction_datetime, row))

	if dated_interactions:
		latest_row = max(dated_interactions, key=lambda value: value[0])[1]
		doc.last_contact_on = latest_row.get("interaction_on")
		doc.last_outcome = latest_row.get("outcome")
	else:
		doc.last_contact_on = None
		doc.last_outcome = None

	if follow_up_interactions:
		latest_follow_up_row = max(
			follow_up_interactions, key=lambda value: value[0]
		)[1]
		doc.next_follow_up = latest_follow_up_row.get("next_follow_up")


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
