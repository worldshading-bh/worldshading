# -*- coding: utf-8 -*-
"""Chase payments we were never told the outcome of.

This closes the only path where real money can go missing.

A transaction sits at `Redirected` when we sent the customer to the bank and never
heard back. That is ambiguous in a way no other state is:

  * the customer closed the tab            -> no money moved, nothing to do
  * the payment captured and we lost the
    callback (network, Cloudflare, a
    restart mid-request)                   -> MONEY TAKEN, ERPNext has no idea

Nothing in the normal flow ever revisits those rows, so without this sweep the second
case stays invisible forever. `Initiated` needs none of this -- it never reached the
gateway, so there is definitively no money behind it.

Scheduled from hooks.py. Note `pause_scheduler` is set on this site, which stops
scheduled jobs (enqueued ones still run) -- see Documentation/payments/open_questions.md.

Safe to run by hand at any time:

    bench --site erp.worldshading.com execute worldshading.payments.reconcile.run
"""
from __future__ import unicode_literals

import frappe
from frappe.utils import add_to_date, now_datetime

from worldshading.payments.utils import (
	TRANSACTION_DOCTYPE,
	enqueue_settlement,
	link_validity_days,
	logger,
)

# How long to wait before treating silence as suspicious. Long enough that a customer
# still filling in a card is not chased; short enough that a lost callback surfaces
# the same working day.
STALE_AFTER_MINUTES = 15


def run():
	"""Entry point for the scheduler."""
	chase_redirected()
	expire_unused_links()


def chase_redirected():
	"""Resolve transactions the gateway never reported back on."""
	cutoff = add_to_date(now_datetime(), minutes=-STALE_AFTER_MINUTES)

	stale = frappe.get_all(
		TRANSACTION_DOCTYPE,
		filters={
			"status": "Redirected",
			"creation": ["<", cutoff],
			"needs_review": 0,
		},
		fields=["name", "gateway", "track_id", "amount", "currency"],
		order_by="creation",
	)

	if not stale:
		return

	logger().info("reconcile: %d transaction(s) awaiting an outcome", len(stale))

	for row in stale:
		try:
			_resolve(row)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				frappe.get_traceback(), "Payment reconciliation failed: {0}".format(row.name)
			)


def _resolve(row):
	from worldshading.payments import benefit, mpgs

	txn = frappe.get_doc(TRANSACTION_DOCTYPE, row.name)

	if txn.gateway == mpgs.GATEWAY:
		# MPGS documents Retrieve Order properly, so this needs no hedging: ask, and
		# act on the answer.
		order = mpgs.retrieve_order(txn)
		captured = mpgs.apply_result(txn, order)
		frappe.db.commit()

		logger().info("reconcile: %s resolved to %s", txn.name, txn.status)

		if captured:
			enqueue_settlement(txn.name)
			return

		if txn.status == "Redirected":
			# The gateway answered, but with a state that is neither success nor
			# failure -- an order stuck at AUTHENTICATED, say. Chasing it every
			# fifteen minutes forever helps nobody; a person should look at it.
			_flag_for_review(txn)

		return

	# BENEFIT has not confirmed Inquiry for the REST surface. Never send an
	# unverified financial request in production or guess about the outcome.
	_flag_for_review(txn)


def _flag_for_review(txn):
	txn.db_set("needs_review", 1, update_modified=False)

	if not txn.gateway_message:
		txn.db_set(
			"gateway_message",
			"No outcome received from the gateway. Check this transaction in the "
			"gateway portal before assuming it was not paid.",
			update_modified=False,
		)

	frappe.db.commit()

	logger().error(
		"reconcile: %s (track %s, %s %s) has no outcome -- needs review",
		txn.name, txn.track_id, txn.amount, txn.currency,
	)


def expire_unused_links():
	"""Housekeeping only. Never touches anything that reached the gateway.

	A link nobody opened is harmless -- no gateway contact, no money -- but leaving
	them at `Initiated` forever makes the list useless for spotting the ones that
	matter. Once past the validity window they can no longer be paid anyway, because
	checkout refuses them.
	"""
	from worldshading.payments import benefit

	days = link_validity_days(benefit.GATEWAY)
	if not days:
		return

	cutoff = add_to_date(now_datetime(), days=-days)

	stale = frappe.get_all(
		TRANSACTION_DOCTYPE,
		filters={"status": "Initiated", "creation": ["<", cutoff]},
		fields=["name"],
	)

	for row in stale:
		frappe.db.set_value(
			TRANSACTION_DOCTYPE, row.name, "status", "Expired", update_modified=False
		)

	if stale:
		frappe.db.commit()
		logger().info("reconcile: expired %d unused payment link(s)", len(stale))
