import frappe
import os

@frappe.whitelist()
def rename_uploaded_file(file_docname, new_name):
    file_doc = frappe.get_doc("File", file_docname)

    if not file_doc.file_url:
        return

    # -------------------------------
    # Get REAL filename from file_url
    # -------------------------------
    actual_filename = file_doc.file_url.split("/")[-1]

    # -------------------------------
    # If PRIVATE → move to PUBLIC
    # -------------------------------
    if file_doc.is_private:

        old_path = frappe.get_site_path("private", "files", actual_filename)
        new_path = frappe.get_site_path("public", "files", actual_filename)

        if os.path.exists(old_path):
            os.rename(old_path, new_path)
        else:
            frappe.throw("Original private file not found.")

        file_doc.db_set("is_private", 0)

    # -------------------------------
    # Now work in PUBLIC
    # -------------------------------
    base_path = frappe.get_site_path("public", "files")
    url_prefix = "/files/"

    old_path = os.path.join(base_path, actual_filename)

    if not os.path.exists(old_path):
        frappe.throw("File not found after move.")

    # Preserve extension
    extension = os.path.splitext(actual_filename)[1]
    safe_name = new_name.replace("/", "-").replace("\\", "-")
    new_filename = safe_name + extension
    new_path = os.path.join(base_path, new_filename)

    # Prevent overwrite
    if os.path.exists(new_path):
        new_filename = safe_name + "_" + frappe.generate_hash(length=4) + extension
        new_path = os.path.join(base_path, new_filename)

    # Rename physically
    os.rename(old_path, new_path)

    # Update DB
    file_doc.db_set("file_name", new_filename)
    file_doc.db_set("file_url", url_prefix + new_filename)

    return new_filename




import frappe
import os
from PyPDF2 import PdfFileMerger


@frappe.whitelist()
def merge_shipping_docs(po_name, documents):

    if isinstance(documents, str):
        documents = frappe.parse_json(documents)

    if not documents:
        frappe.throw("No shipping documents received.")

    merger = PdfFileMerger()

    for row in documents:
        file_url = row.get("file")

        if not file_url:
            continue

        file_doc = frappe.get_doc("File", {"file_url": file_url})
        full_path = frappe.get_site_path(file_doc.file_url.strip("/"))

        if not os.path.exists(full_path):
            frappe.throw(f"File not found: {file_url}")

        if not full_path.lower().endswith(".pdf"):
            frappe.throw("Only PDF files are allowed for merging.")

        merger.append(full_path)

    output_filename = f"Shipping Dossier - {po_name}.pdf"
    output_path = frappe.get_site_path("private/files", output_filename)

    if os.path.exists(output_path):
        os.remove(output_path)

    merger.write(output_path)
    merger.close()

    new_file = frappe.get_doc({
        "doctype": "File",
        "file_name": output_filename,
        "file_url": f"/private/files/{output_filename}",
        "attached_to_doctype": "Purchase Order",
        "attached_to_name": po_name,
        "is_private": 1
    }).insert(ignore_permissions=True)

    return {
        "message": "Merged successfully",
        "file_url": new_file.file_url
    }


# --------------------------------------------------
# Merge Shipment Documents
# --------------------------------------------------

import frappe
import json
import io
from pypdf import PdfMerger
from frappe.utils.file_manager import save_file


@frappe.whitelist()
def merge_shipment_documents(file_names, po_name):

    if isinstance(file_names, str):
        file_names = json.loads(file_names)

    if not file_names:
        frappe.throw("No files received for merging.")

    merger = PdfMerger(strict=False)
    file_docs = []

    # -------------------------------
    # Validate & Collect Files
    # -------------------------------
    for file_docname in file_names:

        file_doc = frappe.get_doc("File", file_docname)

        if not file_doc.file_url or not file_doc.file_url.lower().endswith(".pdf"):
            frappe.throw("Only PDF files are allowed.")

        if file_doc.file_url.startswith("/private/files/"):
            file_path = frappe.get_site_path(
                "private", "files", file_doc.file_url.split("/")[-1]
            )
        elif file_doc.file_url.startswith("/files/"):
            file_path = frappe.get_site_path(
                "public", "files", file_doc.file_url.split("/")[-1]
            )
        else:
            frappe.throw("Invalid file path: " + file_doc.file_url)

        merger.append(file_path)
        file_docs.append(file_doc)

    # -------------------------------
    # Merge in Memory
    # -------------------------------
    # Merge in Memory
    merged_filename = f"Shipment Documents - {po_name}.pdf"

    buffer = io.BytesIO()
    merger.write(buffer)
    merger.close()
    buffer.seek(0)

    new_file = save_file(
        merged_filename,
        buffer.read(),
        None,
        None,
        is_private=0
    )

    # Delete Original Files (background)
    frappe.enqueue(
        "worldshading.api.utility.cleanup_shipment_files",
        file_names=[f.name for f in file_docs],
        queue="short"
    )

    return new_file.file_url

@frappe.whitelist()
def cleanup_shipment_files(file_names):

    if isinstance(file_names, str):
        file_names = json.loads(file_names)

    for file_name in file_names:
        try:
            frappe.delete_doc("File", file_name , ignore_permissions=True)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                "Shipment file cleanup failed"
            )



import json
import io
import tempfile
from urllib.parse import unquote
from pypdf import PdfMerger
from PIL import Image
from frappe.utils.file_manager import save_file

# Merge Global
@frappe.whitelist()
def merge_documents(
    file_names,
    output_filename=None,
    attach_to_doctype=None,
    attach_to_name=None,
    cleanup_originals=0,
    is_private=1
):

    # --------------------------------------------------
    # Parse JSON
    # --------------------------------------------------

    if isinstance(file_names, str):
        file_names = json.loads(file_names)

    if not file_names:
        frappe.throw("No files received for merging.")

    # --------------------------------------------------
    # Defaults
    # --------------------------------------------------

    if not output_filename:
        output_filename = "Merged Document"

    if not output_filename.lower().endswith(".pdf"):
        output_filename += ".pdf"

    cleanup_originals = int(cleanup_originals)
    is_private = int(is_private)

    # --------------------------------------------------
    # Supported Formats
    # --------------------------------------------------

    image_extensions = (
        ".jpg",
        ".jpeg",
        ".jpe",
        ".jfif",
        ".png",
        ".webp"
    )

    pdf_extensions = (
        ".pdf",
    )

    # --------------------------------------------------
    # Setup
    # --------------------------------------------------

    merger = PdfMerger(strict=False)

    temp_files = []
    original_files = []

    # --------------------------------------------------
    # Process Files
    # --------------------------------------------------

    for file_docname in file_names:

        file_doc = frappe.get_doc("File", file_docname)

        if not file_doc.file_url:
            continue

        file_url = (file_doc.file_url or "").strip()
        decoded_file_url = unquote(file_url)
        file_url_for_ext = decoded_file_url.split("?", 1)[0].split("#", 1)[0].lower()
        file_extension = os.path.splitext(file_url_for_ext)[1]

        # --------------------------------------------------
        # Resolve Path
        # --------------------------------------------------

        if file_url.startswith("/private/files/"):

            file_path = frappe.get_site_path(
                "private",
                "files",
                decoded_file_url.split("/")[-1]
            )

        elif file_url.startswith("/files/"):

            file_path = frappe.get_site_path(
                "public",
                "files",
                decoded_file_url.split("/")[-1]
            )

        else:
            frappe.throw("Invalid file path: " + file_doc.file_url)

        # --------------------------------------------------
        # File Exists Check
        # --------------------------------------------------

        if not os.path.exists(file_path):
            frappe.throw("File not found: " + file_doc.file_url)

        # --------------------------------------------------
        # PDF Handling
        # --------------------------------------------------

        if file_extension in pdf_extensions:

            merger.append(file_path)
            original_files.append(file_doc)

        # --------------------------------------------------
        # Image Handling
        # --------------------------------------------------

        elif file_extension in image_extensions:

            try:

                img = Image.open(file_path).convert("RGB")

                temp_pdf = tempfile.NamedTemporaryFile(
                    suffix=".pdf",
                    delete=False
                )

                img.save(temp_pdf.name, "PDF")

                merger.append(temp_pdf.name)

                temp_files.append(temp_pdf.name)
                original_files.append(file_doc)

            except Exception:
                frappe.throw(
                    "Failed to process image: " + file_doc.file_name
                )

        # --------------------------------------------------
        # Unsupported
        # --------------------------------------------------

        else:

            frappe.throw(
                "Unsupported file type: " + file_doc.file_name
            )

    # --------------------------------------------------
    # Merge PDFs in Memory
    # --------------------------------------------------

    buffer = io.BytesIO()

    merger.write(buffer)
    merger.close()

    buffer.seek(0)

    # --------------------------------------------------
    # Save Final PDF
    # --------------------------------------------------

    new_file = save_file(
        output_filename,
        buffer.read(),
        attach_to_doctype,
        attach_to_name,
        is_private=is_private
    )

    # --------------------------------------------------
    # Cleanup Temp PDFs
    # --------------------------------------------------

    for temp_path in temp_files:

        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                "Temporary PDF cleanup failed"
            )

    # --------------------------------------------------
    # Optional Original File Cleanup
    # --------------------------------------------------

    if cleanup_originals:

        frappe.enqueue(
            "worldshading.api.utility.cleanup_shipment_files",
            file_names=[f.name for f in original_files],
            queue="short"
        )

    # --------------------------------------------------
    # Return
    # --------------------------------------------------

    return {
        "success": True,
        "file_name": new_file.file_name,
        "file_url": new_file.file_url,
        "file_doc": new_file.name
    }
