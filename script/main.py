import fitz  # PyMuPDF
doc = fitz.open("Boxam2026.pdf")
text = "\n".join(page.get_text() for page in doc)
print(text)