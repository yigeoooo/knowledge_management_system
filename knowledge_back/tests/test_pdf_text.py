from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.indexer import _extract_text
from app.pdf_text import normalize_pdf_text


def test_pdf_extraction_normalizes_font_controls_and_radicals():
    # Some PDF font maps encode spaces as U+0001 and Chinese characters as
    # Kangxi radicals. Exercise the actual PDF parser without private documents.
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    cmap = DecodedStreamObject()
    cmap.set_data(b"""/CIDInit /ProcSet findresource begin
12 dict begin begincmap
/CMapType 2 def
1 begincodespacerange <00> <FF> endcodespacerange
3 beginbfchar <01> <0001> <02> <2F1D> <03> <2F24> endbfchar
endcmap CMapName currentdict /CMap defineresource pop end end""")
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/ToUnicode"): writer._add_object(cmap),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td <410142010201030143> Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    assert _extract_text("fixture.PDF", output.getvalue()) == "A B 口 大 C"


def test_markdown_source_preserves_code_and_unicode():
    text = '# Unicode\n\n```python\nvalue = "① x² ⼝"\n```'
    assert _extract_text("guide.md", text.encode("utf-8")) == text


def test_pdf_normalization_preserves_commands_math_and_line_breaks():
    text = "接⼝\x01说明\r\n\ttool\x01--port\x0180\n① x² Ａ\x0c下一页"
    expected = "接口 说明\r\n\ttool --port 80\n① x² Ａ\n\n下一页"
    assert normalize_pdf_text(text) == expected
    assert normalize_pdf_text(expected) == expected
