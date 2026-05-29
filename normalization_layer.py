import re
import unicodedata

def convert_digits(text: str) -> str:
    """Converts Farsi/Arabic digits to English digits for consistent parsing."""
    if not text:
        return ""
    farsi_digits = '۰۱۲۳۴۵۶۷۸۹'
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    english_digits = '0123456789'
    translation_table = str.maketrans(farsi_digits + arabic_digits, english_digits * 2)
    return text.translate(translation_table)

def remove_emojis_and_symbols(text: str) -> str:
    """
    Strips emojis, pictographs, dingbats, and non-essential custom symbols
    by checking Unicode character category properties.
    Keeps standard alphanumeric characters, spaces, and punctuation.
    """
    if not text:
        return ""
        
    cleaned_chars = []
    for char in text:
        category = unicodedata.category(char)
        # Category 'So' (Symbol, other) contains the vast majority of emojis and pictographs.
        # Category 'Cs' is surrogate (used in UTF-16 representation, can represent emojis).
        if category in ('So', 'Cs'):
            # Replaces emoji with a space to avoid character merging, which will be collapsed later
            cleaned_chars.append(' ')
        else:
            cleaned_chars.append(char)
            
    return "".join(cleaned_chars)

def normalize_text(content: str) -> str:
    """
    Fully cleans and standardizes chat/voice-transcribed content:
    - Normalizes Farsi/Arabic character mappings (ي -> ی, ك -> ک).
    - Translates Farsi/Arabic digits to English numbers.
    - Strips emojis and corrupted symbols.
    - Normalizes whitespaces and collapsing tabs/multi-spaces.
    - Converts all line break formats to standard '\n' and caps consecutive newlines to 2.
    """
    if not content:
        return ""
        
    # 1. Standardize directional marks and zero-width spaces
    cleaned = content.replace('\u200e', '').replace('\u200f', '').replace('\u202f', ' ').replace('\u200b', '')
    
    # 2. Convert yiah and kaf
    cleaned = cleaned.replace('ي', 'ی').replace('ك', 'ک')
    
    # 3. Convert Farsi/Arabic digits to English
    cleaned = convert_digits(cleaned)
    
    # 4. Remove emojis & So symbols
    cleaned = remove_emojis_and_symbols(cleaned)
    
    # 5. Normalize line breaks (convert CRLF to LF)
    cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')
    
    # Collapse multiple consecutive newlines to maximum 2 (maintaining paragraphs)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    
    # 6. Normalize whitespaces on each line
    lines = cleaned.split('\n')
    normalized_lines = []
    for line in lines:
        # Collapse multiple spaces or tabs into a single space
        norm_line = re.sub(r'[\s\xa0]+', ' ', line).strip()
        normalized_lines.append(norm_line)
        
    # Join lines back
    result = '\n'.join(normalized_lines)
    
    # Final trim
    return result.strip()
