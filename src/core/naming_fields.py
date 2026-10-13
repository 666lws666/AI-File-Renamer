"""M2 NamingFields — structured AI output, pure data."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class NamingFields:
    dcDate: Optional[str] = None
    dcTitle: Optional[str] = None
    dcSubject: Optional[str] = None
    dcType: Optional[str] = None
    dcCreator: Optional[str] = None
    dcIdentifier: Optional[str] = None
    extOrganization: Optional[str] = None
    extProject: Optional[str] = None
    extStatus: Optional[str] = None
    extVersion: Optional[str] = None
