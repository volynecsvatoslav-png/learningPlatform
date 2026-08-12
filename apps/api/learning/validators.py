import re

from django.core.exceptions import ValidationError

RAW_HTML_PATTERN = re.compile(r"<!--|</?[A-Za-z][^>]*>")


def validate_markdown_without_html(value: str) -> None:
    if RAW_HTML_PATTERN.search(value):
        raise ValidationError("Raw HTML is not allowed in Markdown.")
