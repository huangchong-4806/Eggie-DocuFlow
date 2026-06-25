def parse_invoice(pdf_file, progress_callback=None):
    from pdf_invoice_tool import extract_invoice

    return extract_invoice(pdf_file, progress_callback)
