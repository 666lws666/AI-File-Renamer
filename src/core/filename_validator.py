"""M2 Filename Validator — pure validation, no disk I/O."""
import re
from dataclasses import dataclass, field


RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"}
for i in range(1, 10):
    RESERVED_NAMES.add(f"COM{i}")
    RESERVED_NAMES.add(f"LPT{i}")

ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*]')
MAX_NAME_LENGTH = 255


@dataclass
class ValidationError:
    code: str
    message_id: str
    detail: str = ""


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list = field(default_factory=list)


def validate_filename(name: str, original_extension: str = "") -> ValidationResult:
    """Validate a proposed base filename (without extension). Pure logic, no disk I/O."""
    errors = []

    ext = original_extension
    # Protect extension — target name MUST end with original extension
    if ext:
        if not name.lower().endswith(ext.lower()):
            errors.append(ValidationError("EXTENSION_CHANGED", "filename.ext_changed",
                                          f"Extension must be {ext}"))
            return ValidationResult(False, errors)
        stem = name[:-len(ext)]
    else:
        stem = name

    # Empty
    if not stem.strip():
        errors.append(ValidationError("EMPTY_NAME", "filename.empty", "Name is empty"))
        return ValidationResult(False, errors)

    # Illegal characters
    if ILLEGAL_CHARS_RE.search(stem):
        errors.append(ValidationError("ILLEGAL_CHARS", "filename.illegal_chars",
                                      f"Contains illegal characters: < > : \" / \\ | ? *"))
        return ValidationResult(False, errors)

    # Trailing space or dot
    if stem != stem.rstrip():
        errors.append(ValidationError("TRAILING_SPACE", "filename.trailing_space", "Trailing spaces"))
        return ValidationResult(False, errors)
    if stem.endswith("."):
        errors.append(ValidationError("TRAILING_DOT", "filename.trailing_dot", "Name ends with dot"))
        return ValidationResult(False, errors)

    # Reserved names (with or without extension)
    stem_upper = stem.upper()
    for reserved in RESERVED_NAMES:
        if stem_upper == reserved:
            errors.append(ValidationError("RESERVED_NAME", "filename.reserved",
                                          f"'{stem}' is a reserved Windows name"))
            return ValidationResult(False, errors)
        if stem_upper.startswith(reserved + "."):
            errors.append(ValidationError("RESERVED_NAME", "filename.reserved",
                                          f"'{stem}' starts with reserved name"))
            return ValidationResult(False, errors)

    # Length check
    full = stem + ext if ext else stem
    if len(full) > MAX_NAME_LENGTH:
        errors.append(ValidationError("NAME_TOO_LONG", "filename.too_long",
                                      f"Name exceeds {MAX_NAME_LENGTH} characters"))
        return ValidationResult(False, errors)

    return ValidationResult(True)
