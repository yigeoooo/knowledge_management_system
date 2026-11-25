"""DOCX numbering is optional; create it only when writing a list."""

from docx.opc.constants import CONTENT_TYPE as CT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.parts.numbering import NumberingPart


def numbering_element(document_part, *, create=False):
    # python-docx's numbering_part property calls an unimplemented .new()
    # when an otherwise valid imported DOCX has no numbering relationship.
    try:
        part = document_part.part_related_by(RT.NUMBERING)
    except KeyError:
        if not create:
            return None
        package = document_part.package
        part = NumberingPart(
            package.next_partname("/word/numbering%d.xml"),
            CT.WML_NUMBERING,
            OxmlElement("w:numbering"),
            package,
        )
        document_part.relate_to(part, RT.NUMBERING)
    return part.element
