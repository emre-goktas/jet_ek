import pymupdf

doc = pymupdf.open()
page = doc.new_page()
text = "EK: 1/1"
page.insert_text(pymupdf.Point(page.rect.width - 80, 40), text, fontsize=12, color=(1, 0, 0), fontname="hebo")
doc.save("test.pdf")
