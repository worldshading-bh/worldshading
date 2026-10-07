from __future__ import unicode_literals

import frappe
from erpnext import get_company_currency
from erpnext.setup.utils import get_exchange_rate
from erpnext.stock.get_item_details import get_price_list_rate_for
from frappe.utils import cint, flt, nowdate


@frappe.whitelist()
def get_secret_price_lists(customer=None):
    """Return enabled protected Selling Price Lists available for assignment."""
    if not customer:
        frappe.throw("Customer is required")

    customer_doc = frappe.get_doc("Customer", customer)
    customer_doc.check_permission("write")
    _validate_secret_price_permission(customer_doc)

    price_lists = frappe.get_all(
        "Price List",
        filters={
            "only_for_verified_customers": 1,
            "enabled": 1,
            "selling": 1
        },
        fields=["name"],
        order_by="name asc"
    )
    price_list_names = [row.name for row in price_lists]

    if not price_list_names:
        frappe.throw("No enabled protected Selling Price List is configured")

    default_price_list = price_list_names[0]
    current_secret_price_list = None
    if customer_doc and customer_doc.default_price_list in price_list_names:
        default_price_list = customer_doc.default_price_list
        current_secret_price_list = customer_doc.default_price_list

    return {
        "price_lists": price_list_names,
        "default_price_list": default_price_list,
        "current_secret_price_list": current_secret_price_list
    }


@frappe.whitelist()
def apply_secret_price_list(customer, price_list):
    """Assign a protected Selling Price List through the controlled action."""
    if not customer:
        frappe.throw("Customer is required")
    if not price_list:
        frappe.throw("Price List is required")

    customer_doc = frappe.get_doc("Customer", customer)
    customer_doc.check_permission("write")
    _validate_secret_price_permission(customer_doc)

    price_list_details = frappe.db.get_value(
        "Price List",
        price_list,
        ["only_for_verified_customers", "enabled", "selling"],
        as_dict=True
    )
    if (
        not price_list_details or
        not price_list_details.only_for_verified_customers or
        not price_list_details.enabled or
        not price_list_details.selling
    ):
        frappe.throw(
            "Price List {0} is not an enabled protected Selling Price List".format(
                frappe.bold(price_list)
            )
        )

    customer_doc.default_price_list = price_list
    customer_doc.flags.secret_price_list_assignment = True
    customer_doc.save()

    return {
        "customer": customer_doc.name,
        "price_list": customer_doc.default_price_list
    }


@frappe.whitelist()
def remove_secret_price_list(customer):
    """Remove a protected Selling Price List through the controlled action."""
    if not customer:
        frappe.throw("Customer is required")

    customer_doc = frappe.get_doc("Customer", customer)
    customer_doc.check_permission("write")
    _validate_secret_price_permission(customer_doc)
    current_price_list = customer_doc.default_price_list

    if not current_price_list or not _is_protected_price_list(current_price_list):
        frappe.throw("This Customer does not have a protected B2B Price List")

    customer_doc.default_price_list = None
    customer_doc.flags.secret_price_list_assignment = True
    customer_doc.save()

    return {
        "customer": customer_doc.name,
        "removed_price_list": current_price_list
    }


def validate_customer_secret_price_list_assignment(doc, method=None):
    """Prevent protected Price Lists from being assigned outside the controlled action."""
    price_list = doc.get("default_price_list")
    if not price_list or not _is_protected_price_list(price_list):
        return

    if doc.flags.get("secret_price_list_assignment"):
        return

    previous_doc = None if doc.is_new() else doc.get_doc_before_save()
    if previous_doc and previous_doc.get("default_price_list") == price_list:
        return

    frappe.throw(
        "Use the Apply B2B Secret Price List button to assign protected pricing"
    )


def _validate_secret_price_permission(customer_doc):
    """Use the button field's configured permission level as authorization."""
    if not customer_doc.has_permlevel_access_to(
        "apply_secret_price_list", permission_type="write"
    ):
        frappe.throw(
            "You do not have permission to manage B2B Secret Pricing",
            frappe.PermissionError
        )


def set_regular_price_list_rates(doc, method=None):
    """Snapshot the global regular selling rate for protected-price transactions."""
    price_list = doc.get("selling_price_list")
    is_protected_price_list = bool(
        price_list and _is_protected_price_list(price_list)
    )
    service_item_ids = normalize_quotation_service_item_pricing(doc)
    if not is_protected_price_list:
        for item in doc.get("items") or []:
            if id(item) in service_item_ids:
                continue
            item.regular_price_list_rate = flt(
                item.get("price_list_rate"),
                item.precision("regular_price_list_rate")
            )
            item.applied_price_list = None
        set_quotation_total_discount_percentages(doc, service_item_ids)
        set_quotation_pricing_totals(doc, False, service_item_ids)
        return

    business_price_list_details = frappe.db.get_value(
        "Price List",
        price_list,
        ["price_not_uom_dependent", "enabled", "selling"],
        as_dict=True
    )
    if (
        not business_price_list_details or
        not business_price_list_details.enabled or
        not business_price_list_details.selling
    ):
        frappe.throw(
            "The protected Price List {0} must be enabled and marked as Selling".format(
                frappe.bold(price_list)
            )
        )

    regular_price_list = frappe.db.get_single_value(
        "Selling Settings",
        "selling_price_list"
    )
    if not regular_price_list:
        frappe.throw("Configure the Default Price List in Selling Settings")
    if _is_protected_price_list(regular_price_list):
        frappe.throw(
            "The Default Price List in Selling Settings cannot be restricted to verified customers"
        )

    price_list_details = frappe.db.get_value(
        "Price List",
        regular_price_list,
        ["currency", "price_not_uom_dependent", "enabled", "selling"],
        as_dict=True
    )
    if not price_list_details or not price_list_details.enabled or not price_list_details.selling:
        frappe.throw(
            "The regular Price List {0} must be enabled and marked as Selling".format(
                frappe.bold(regular_price_list)
            )
        )

    transaction_date = doc.get("transaction_date") or doc.get("posting_date") or nowdate()
    company_currency = get_company_currency(doc.company)
    price_list_conversion_rate = _get_price_list_conversion_rate(
        price_list_details.currency,
        company_currency,
        transaction_date
    )
    transaction_conversion_rate = flt(doc.get("conversion_rate")) or 1
    validate_business_price = not _is_valid_linked_sales_invoice_return(
        doc,
        price_list
    )
    fallback_applied = False

    for item in doc.get("items") or []:
        if id(item) in service_item_ids:
            continue

        if not item.get("item_code"):
            item.regular_price_list_rate = 0
            if validate_business_price:
                item.applied_price_list = None
            continue

        business_rate = None
        if validate_business_price:
            business_rate, stock_uom = _get_applicable_item_price(
                price_list,
                business_price_list_details,
                item,
                transaction_date
            )

        regular_rate, stock_uom = _get_applicable_item_price(
            regular_price_list,
            price_list_details,
            item,
            transaction_date
        )
        if not regular_rate or flt(regular_rate) <= 0:
            item.regular_price_list_rate = 0
            if validate_business_price:
                item.applied_price_list = (
                    price_list if business_rate and flt(business_rate) > 0 else None
                )
            continue

        converted_rate = (
            flt(regular_rate) * flt(price_list_conversion_rate) /
            transaction_conversion_rate
        )
        item.regular_price_list_rate = flt(
            converted_rate,
            item.precision("regular_price_list_rate")
        )

        if validate_business_price and (not business_rate or flt(business_rate) <= 0):
            item.price_list_rate = item.regular_price_list_rate
            item.rate = item.regular_price_list_rate
            item.applied_price_list = regular_price_list
            fallback_applied = True
        elif validate_business_price:
            item.applied_price_list = price_list

    if fallback_applied:
        doc.calculate_taxes_and_totals()

    set_quotation_total_discount_percentages(doc, service_item_ids)
    set_quotation_pricing_totals(doc, True, service_item_ids)


def normalize_quotation_service_item_pricing(doc):
    """Exclude dynamically priced service items from sales discount comparison."""
    service_item_ids = set()
    if doc.get("doctype") not in ("Quotation", "Sales Order"):
        return service_item_ids

    item_codes = list(set(
        item.get("item_code") for item in (doc.get("items") or [])
        if item.get("item_code")
    ))
    dynamically_priced_items = set(["QC7026"])
    if item_codes:
        dynamically_priced_items.update(
            row.new_item_code for row in frappe.get_all(
                "Product Bundle",
                filters={
                    "new_item_code": ["in", item_codes],
                    "disabled": 0,
                    "custom_project_logic": 1
                },
                fields=["new_item_code"]
            )
        )

    for item in doc.get("items") or []:
        item_code = item.get("item_code")
        if not item_code or item_code not in dynamically_priced_items:
            continue

        service_item_ids.add(id(item))
        item.regular_price_list_rate = 0
        item.discount_percentage = 0
        item.discount_amount = 0
        item.total_discount_percentage = 0
        item.total_discount_amount = 0
        item.applied_price_list = None

    return service_item_ids


def set_quotation_total_discount_percentages(doc, service_item_ids=None):
    """Show the complete reduction from the regular comparison rate."""
    if doc.get("doctype") not in ("Quotation", "Sales Order"):
        return

    service_item_ids = service_item_ids or set()
    for item in doc.get("items") or []:
        if id(item) in service_item_ids:
            item.total_discount_percentage = 0
            item.total_discount_amount = 0
            continue

        regular_price_list_rate = flt(item.get("regular_price_list_rate"))
        price_list_rate = flt(item.get("price_list_rate"))
        final_rate = flt(item.get("rate"))
        comparison_rate = regular_price_list_rate or price_list_rate
        total_discount_percentage = 0

        if comparison_rate > 0 and final_rate < comparison_rate:
            total_discount_percentage = (
                (comparison_rate - final_rate) * 100 / comparison_rate
            )

        precision_method = getattr(item, "precision", None)
        precision = (
            precision_method("total_discount_percentage")
            if callable(precision_method) else None
        )
        item.total_discount_percentage = flt(
            total_discount_percentage,
            precision
        )

        total_discount_amount = 0
        if comparison_rate > 0 and final_rate < comparison_rate:
            total_discount_amount = flt(item.get("qty")) * (
                comparison_rate - final_rate
            )

        amount_precision = (
            precision_method("total_discount_amount")
            if callable(precision_method) else None
        )
        if amount_precision is None:
            doc_precision_method = getattr(doc, "precision", None)
            amount_precision = (
                doc_precision_method("total_item_discount")
                if callable(doc_precision_method) else None
            )
        item.total_discount_amount = flt(
            total_discount_amount,
            amount_precision
        )


def set_quotation_pricing_totals(
    doc,
    is_protected_price_list,
    service_item_ids=None
):
    """Set sales transaction comparison subtotal and total item discount."""
    if doc.get("doctype") not in ("Quotation", "Sales Order"):
        return

    regular_price_list_subtotal = 0
    price_list_subtotal = 0
    total_item_discount = 0
    special_price_savings = 0
    transaction_price_list = doc.get("selling_price_list")
    service_item_ids = service_item_ids or set()

    for item in doc.get("items") or []:
        if id(item) in service_item_ids:
            service_amount = flt(item.get("amount"))
            item.total_discount_amount = 0
            regular_price_list_subtotal += service_amount
            price_list_subtotal += service_amount
            continue

        qty = flt(item.get("qty"))
        price_list_rate = flt(item.get("price_list_rate"))
        regular_price_list_rate = flt(item.get("regular_price_list_rate"))
        row_price_list_total = qty * price_list_rate
        row_regular_total = row_price_list_total

        price_list_subtotal += row_price_list_total

        if (
            is_protected_price_list and
            item.get("applied_price_list") == transaction_price_list and
            regular_price_list_rate > 0
        ):
            row_regular_total = qty * regular_price_list_rate
            special_price_savings += (
                row_regular_total - row_price_list_total
            )

        regular_price_list_subtotal += row_regular_total

        final_rate = item.get("rate")
        if final_rate is None:
            final_rate = price_list_rate - flt(item.get("discount_amount"))
        comparison_rate = regular_price_list_rate or price_list_rate
        row_total_discount = 0
        if comparison_rate > 0 and flt(final_rate) < comparison_rate:
            row_total_discount = qty * (comparison_rate - flt(final_rate))

        precision_method = getattr(item, "precision", None)
        precision = (
            precision_method("total_discount_amount")
            if callable(precision_method) else None
        )
        if precision is None:
            doc_precision_method = getattr(doc, "precision", None)
            precision = (
                doc_precision_method("total_item_discount")
                if callable(doc_precision_method) else None
            )
        item.total_discount_amount = flt(row_total_discount, precision)
        total_item_discount += item.total_discount_amount

    _set_quotation_currency_value(
        doc,
        "regular_price_list_subtotal",
        regular_price_list_subtotal
    )
    if doc.get("doctype") == "Quotation":
        _set_quotation_currency_value(
            doc,
            "special_price_savings",
            special_price_savings
        )
        _set_quotation_currency_value(
            doc,
            "price_list_subtotal",
            price_list_subtotal
        )
    _set_quotation_currency_value(
        doc,
        "total_item_discount",
        total_item_discount
    )


def _set_quotation_currency_value(doc, fieldname, value):
    precision_method = getattr(doc, "precision", None)
    precision = precision_method(fieldname) if callable(precision_method) else None
    setattr(doc, fieldname, flt(value, precision))


def _get_applicable_item_price(price_list, price_list_details, item, transaction_date):
    stock_uom = item.get("stock_uom") or frappe.db.get_value(
        "Item",
        item.item_code,
        "stock_uom"
    )
    args = frappe._dict({
        "price_list": price_list,
        "uom": item.get("uom") or stock_uom,
        "stock_uom": stock_uom,
        "conversion_factor": item.get("conversion_factor") or 1,
        "qty": item.get("qty") or 0,
        "transaction_date": transaction_date,
        "price_list_uom_dependant": not cint(
            price_list_details.price_not_uom_dependent
        )
    })
    rate = get_price_list_rate_for(args, item.item_code)

    if not rate:
        variant_of = frappe.db.get_value("Item", item.item_code, "variant_of")
        if variant_of:
            rate = get_price_list_rate_for(args, variant_of)

    return rate, stock_uom


def _get_price_list_conversion_rate(price_list_currency, company_currency, transaction_date):
    if price_list_currency == company_currency:
        return 1

    conversion_rate = get_exchange_rate(
        price_list_currency,
        company_currency,
        transaction_date,
        "for_selling"
    )
    if not conversion_rate:
        frappe.throw(
            "Unable to determine the exchange rate from {0} to {1}".format(
                price_list_currency, company_currency
            )
        )

    return conversion_rate


def validate_verified_business_price_list(doc, method=None):
    """Allow a protected Price List only when explicitly assigned to the Customer."""
    price_list = doc.get("selling_price_list")
    if not price_list or not _is_protected_price_list(price_list):
        return

    if _is_valid_linked_sales_invoice_return(doc, price_list):
        return

    price_list_details = frappe.db.get_value(
        "Price List",
        price_list,
        ["enabled", "selling"],
        as_dict=True
    )
    if not price_list_details or not price_list_details.enabled or not price_list_details.selling:
        frappe.throw(
            "The protected Price List {0} must be enabled and marked as Selling".format(
                frappe.bold(price_list)
            )
        )

    customer = _get_transaction_customer(doc)
    if not customer:
        frappe.throw(
            "The Price List {0} requires explicit Customer authorization".format(
                frappe.bold(price_list)
            )
        )

    customer_price_list = frappe.db.get_value(
        "Customer",
        customer,
        "default_price_list"
    )

    if customer_price_list != price_list:
        frappe.throw(
            "The protected Price List {0} is not assigned to this Customer. "
            "Use the Apply B2B Secret Price List button on the Customer or select a regular Price List".format(
                frappe.bold(price_list)
            )
        )


def _is_protected_price_list(price_list):
    return bool(frappe.db.get_value(
        "Price List",
        price_list,
        "only_for_verified_customers"
    ))


def _get_transaction_customer(doc):
    if doc.doctype == "Quotation":
        if doc.get("quotation_to") != "Customer":
            return None
        return doc.get("party_name")

    return doc.get("customer")


def _is_valid_linked_sales_invoice_return(doc, price_list):
    if doc.doctype != "Sales Invoice" or not doc.get("is_return") or not doc.get("return_against"):
        return False

    original_invoice = frappe.db.get_value(
        "Sales Invoice",
        doc.return_against,
        ["customer", "selling_price_list", "docstatus"],
        as_dict=True
    )

    return bool(
        original_invoice and
        original_invoice.docstatus == 1 and
        original_invoice.customer == doc.get("customer") and
        original_invoice.selling_price_list == price_list
    )
