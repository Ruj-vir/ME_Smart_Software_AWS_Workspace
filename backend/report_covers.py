"""Create report section covers in memory from the shared company template."""
from html import escape
from pathlib import Path

import pymupdf


REPORT_TITLES = {
    "MaintenanceReport": "Maintenance Report",
    "InspectionReport": "Inspection Sheet",
    "SparePartReport": "Spare Part",
    "PhotographerReport": "Photographs",
}


def cover_section(object_name):
    """Return a full-path section key and its display title, or None."""
    parts = object_name.split('/')
    for index in range(len(parts) - 3):
        if parts[index:index + 2] == ['QAQCStep', 'MaintenanceRecord']:
            folder = parts[index + 2]
            return '/'.join(parts[:index + 3]), REPORT_TITLES.get(folder, folder)
    # Data subfolders are independent sections, including nested folders.
    if 'Data' in parts[:-1]:
        return '/'.join(parts[:-1]), parts[-2]
    return None


def create_cover_pdf(title, static_dir):
    """Keep the template footer; replace its heading without writing a file."""
    template = Path(static_dir) / 'assets/pdf/covers/PageCover.pdf'
    with pymupdf.open(template) as doc:
        page = doc[0]
        headings = page.search_for('ORGANIZE')
        if not headings:
            raise ValueError('Cover template is missing its ORGANIZE heading')
        heading = headings[0]
        for rect in headings:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=0, graphics=0)
        # HTML layout wraps and scales long names and supports Unicode fallback.
        area = pymupdf.Rect(57, heading.y0 - 4, page.rect.width - 57, heading.y0 + 160)
        page.insert_htmlbox(
            area, '<div>' + escape(title) + '</div>',
            css='* {margin:0; padding:0} div {font-family:sans-serif; font-size:30pt; '
                'font-weight:bold; font-style:italic; color:#1d33ff; text-align:center; '
                'overflow-wrap:anywhere}',
        )
        return doc.tobytes(garbage=4, deflate=True)
