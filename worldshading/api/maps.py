# Copyright (c) 2026, World Shading
# Serves the Google Maps API key from site_config so it is NOT hardcoded in
# web-form client scripts. Keeps the key out of git; rotate it via site_config
# alone. The key is HTTP-referrer restricted to *.worldshading.com, so handing
# it to the browser is safe.

import frappe


@frappe.whitelist(allow_guest=True)
def get_maps_key():
	"""Return the Google Maps JS API key for public web-form location pickers.

	Set it in site_config.json as `google_maps_api_key`.
	"""
	return frappe.conf.get("google_maps_api_key")
