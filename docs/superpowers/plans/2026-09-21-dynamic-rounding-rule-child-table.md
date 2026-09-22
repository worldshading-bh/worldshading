# Dynamic Rounding Rule Child Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the ERPNext v12 child DocType files needed to store dynamic rounding ranges and methods.

**Architecture:** A standard editable-grid child DocType named `Dynamic Rounding Rule` will live in the existing Worldshading module. This task creates metadata only; it does not link the table to WS Settings or change sales-document calculations.

**Tech Stack:** Frappe/ERPNext v12 DocType JSON, Python 3.6-compatible Document controller

**Spec:** `docs/superpowers/specs/2026-09-21-dynamic-sales-rounding-design.md`

## Global Constraints

- Compatible with ERPNext/Frappe v12 and Python 3.6.
- Do not modify ERPNext core.
- Do not run migration, restart, cache clear, or bench tests.
- Create only the child DocType in this implementation unit.

## Review Focus

- All four fields must be required so incomplete rules cannot be saved.
- `rounding_method` must allow only `Nearest`, `Lowest`, and `Highest`.
- Amount and rounding-value fields must retain currency precision.
- The DocType must be marked `istable` so it cannot behave as a standalone document.
- File and controller names must match Frappe's snake-case DocType convention.

---

### Task 1: Create Dynamic Rounding Rule child DocType

**Files:**
- Create: `worldshading/worldshading/doctype/dynamic_rounding_rule/__init__.py`
- Create: `worldshading/worldshading/doctype/dynamic_rounding_rule/dynamic_rounding_rule.py`
- Create: `worldshading/worldshading/doctype/dynamic_rounding_rule/dynamic_rounding_rule.json`

**Interfaces:**
- Consumes: Frappe v12 `Document` and DocType metadata loader.
- Produces: Child DocType `Dynamic Rounding Rule` with fields `minimum_amount`, `maximum_amount`, `rounding_method`, and `rounding_value`.

- [ ] **Step 1: Create the package marker and controller**

```python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from frappe.model.document import Document


class DynamicRoundingRule(Document):
	pass
```

- [ ] **Step 2: Create the DocType metadata**

Create an editable-grid child DocType with four required list-view fields. Use Currency for the three numeric values and Select with exact options `Nearest\nLowest\nHighest` for the method.

- [ ] **Step 3: Perform non-executing static review**

Read the files and confirm valid JSON structure, `istable: 1`, module `Worldshading`, exact controller naming, and no unrelated files changed. Do not invoke Frappe, Bench, migration, reload, cache-clear, restart, or test commands.

- [ ] **Step 4: Hand off the reload command**

```bash
bench --site erp.worldshading.com reload-doc worldshading doctype dynamic_rounding_rule
```

Expected result: Frappe imports the child DocType metadata. Linking it to WS Settings remains a separate change.
