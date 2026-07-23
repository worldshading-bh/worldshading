import frappe

ALLOWED_OPERATORS = ["=", "!=", ">", "<", ">=", "<=", "IN", "LIKE"]


def build_conditions(user, doctype):

    # ---- Safe Bypass ----
    if not user:
        user = frappe.session.user

    # Administrator should never be restricted
    if user == "Administrator":
        return ""

    restrictions = frappe.get_all(
        "User Document Restriction",
        filters={
            "user": user,
            "reference_doctype": doctype,
            "is_active": 1
        },
        fields=[
            "restriction_type",
            "field_name",
            "operator",
            "value",
            "child_table_field",
            "child_field"
        ]
    )

    if not restrictions:
        return ""

    meta = frappe.get_meta(doctype)
    valid_fields = [df.fieldname for df in meta.fields]
    valid_fields += ["name", "owner", "creation", "modified"]

    conditions = []

    for r in restrictions:
        restriction_type = r.restriction_type or "Field"
        operator = r.operator or "="
        value = r.value

        if operator not in ALLOWED_OPERATORS:
            continue

        # ==================================================
        # 1. Existing Field Restriction
        # ==================================================
        if restriction_type == "Field":
            field = r.field_name

            if not field or field not in valid_fields:
                continue

            condition = make_condition(
                table=f"tab{doctype}",
                field=field,
                operator=operator,
                value=value
            )

            if condition:
                conditions.append(condition)

        # ==================================================
        # 2. New Child Table Restriction
        # ==================================================
        elif restriction_type == "Child Table":
            child_table_field = r.child_table_field
            child_field = r.child_field

            if not child_table_field or not child_field:
                continue

            child_df = meta.get_field(child_table_field)

            if not child_df:
                continue

            if child_df.fieldtype != "Table":
                continue

            child_doctype = child_df.options

            if not child_doctype:
                continue

            child_meta = frappe.get_meta(child_doctype)
            child_valid_fields = [df.fieldname for df in child_meta.fields]
            child_valid_fields += ["name", "parent", "parentfield", "parenttype"]

            if child_field not in child_valid_fields:
                continue

            child_condition = make_condition(
                table=f"tab{child_doctype}",
                field=child_field,
                operator=operator,
                value=value
            )

            if not child_condition:
                continue

            conditions.append("""
                `tab{doctype}`.`name` IN (
                    SELECT `parent`
                    FROM `tab{child_doctype}`
                    WHERE `parenttype` = {parenttype}
                    AND `parentfield` = {parentfield}
                    AND {child_condition}
                )
            """.format(
                doctype=doctype,
                child_doctype=child_doctype,
                parenttype=frappe.db.escape(doctype),
                parentfield=frappe.db.escape(child_table_field),
                child_condition=child_condition
            ))

    return " AND ".join(conditions) if conditions else ""


def make_condition(table, field, operator, value):
    if not field or value is None:
        return ""

    if operator == "IN":
        values = [v.strip() for v in value.split(",") if v.strip()]

        if not values:
            return ""

        escaped = ", ".join(frappe.db.escape(v) for v in values)

        return "`{table}`.`{field}` IN ({escaped})".format(
            table=table,
            field=field,
            escaped=escaped
        )

    elif operator == "LIKE":
        escaped = frappe.db.escape("%{}%".format(value))

        return "`{table}`.`{field}` LIKE {escaped}".format(
            table=table,
            field=field,
            escaped=escaped
        )

    else:
        escaped = frappe.db.escape(value)

        return "`{table}`.`{field}` {operator} {escaped}".format(
            table=table,
            field=field,
            operator=operator,
            escaped=escaped
        )


def po_query_conditions(user):
    return build_conditions(user, "Purchase Order")


def pi_query_conditions(user):
    return build_conditions(user, "Purchase Invoice")


def so_query_conditions(user):
    return build_conditions(user, "Sales Order")


def si_query_conditions(user):
    return build_conditions(user, "Sales Invoice")


def dn_query_conditions(user):
    return build_conditions(user, "Delivery Note")


def supplier_query_conditions(user):
    return build_conditions(user, "Supplier")


def customer_query_conditions(user):
    return build_conditions(user, "Customer")


def pe_query_conditions(user):
    return build_conditions(user, "Payment Entry")


def sv_query_conditions(user):
    return build_conditions(user, "Service Visit")