"""
Utility functions for cleaning text content from template artifacts and placeholders.
"""
import re


def clean_text(s):
    """
    Remove template artifacts and placeholder text from strings.
    
    Removes:
    - Any fragments with "{#" and "#}" (Django template comments)
    - Substring "Inline SVG placeholder"
    - Sequences of 3+ hash symbols (markdown header artifacts)
    
    Args:
        s: Input string (can be None or empty)
    
    Returns:
        Cleaned string, or empty string if input is None/empty
    """
    if not s:
        return ""
    
    if not isinstance(s, str):
        s = str(s)
    
    # Remove Django template comments: {# ... #}
    s = re.sub(r'\{#.*?#\}', '', s, flags=re.DOTALL)
    
    # Remove "Inline SVG placeholder" substring
    s = re.sub(
        r"Inline\s+SVG\s+placeholder(?:\s+for\s+cases\s+when\s+product\s+has\s+no\s+images)?",
        "",
        s,
        flags=re.IGNORECASE,
    )
    # If comment delimiters leaked without a closing tag, strip them too.
    s = s.replace("{#", "").replace("#}", "")
    
    # Remove sequences of 3+ hash symbols (markdown header artifacts)
    s = re.sub(r'#{3,}', '', s)
    
    # Remove spaces before punctuation marks.
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    # Add a single space after comma/semicolon/colon when followed by a letter.
    s = re.sub(r"([,;:])(?=[A-Za-zА-Яа-яЁё])", r"\1 ", s)
    # Clean up extra whitespace
    s = re.sub(r'\s+', ' ', s)
    s = s.strip()
    
    return s
