import re
from typing import Optional, Dict

class CanonicalRegistrar:
    LINKINTIME = "LINKINTIME"
    KFINTECH = "KFINTECH"
    BIGSHARE = "BIGSHARE"
    SKYLINE = "SKYLINE"
    CAMEO = "CAMEO"
    PURVA = "PURVA"
    MAASHITLA = "MAASHITLA"
    OTHER = "OTHER"

ALL_CANONICAL_REGISTRARS = [
    CanonicalRegistrar.LINKINTIME,
    CanonicalRegistrar.KFINTECH,
    CanonicalRegistrar.BIGSHARE,
    CanonicalRegistrar.SKYLINE,
    CanonicalRegistrar.CAMEO,
    CanonicalRegistrar.PURVA,
    CanonicalRegistrar.MAASHITLA,
    CanonicalRegistrar.OTHER,
]

DEFAULT_REGISTRAR_URLS: Dict[str, str] = {
    CanonicalRegistrar.LINKINTIME: "https://in.mpms.mufg.com/Initial_Offer/public-issues.html",
    CanonicalRegistrar.KFINTECH: "https://ipostatus.kfintech.com/",
    CanonicalRegistrar.BIGSHARE: "https://ipo.bigshareonline.com/IPO_Status.html",
    CanonicalRegistrar.SKYLINE: "https://www.skylinerta.com/ipo.php",
    CanonicalRegistrar.CAMEO: "https://ipo.cameoindia.com/",
    CanonicalRegistrar.PURVA: "https://www.purvashare.com/queries/",
    CanonicalRegistrar.MAASHITLA: "https://maashitla.com/allotment-status/",
}

REGISTRAR_DISPLAY_NAMES: Dict[str, str] = {
    CanonicalRegistrar.LINKINTIME: "Link Intime",
    CanonicalRegistrar.KFINTECH: "KFin Technologies",
    CanonicalRegistrar.BIGSHARE: "Bigshare Services",
    CanonicalRegistrar.SKYLINE: "Skyline Financial",
    CanonicalRegistrar.CAMEO: "Cameo Corporate",
    CanonicalRegistrar.PURVA: "Purva Sharegistry",
    CanonicalRegistrar.MAASHITLA: "Maashitla Securities",
    CanonicalRegistrar.OTHER: "Other Registrar",
}


def normalize_registrar_name(raw_val: Optional[str]) -> Optional[str]:
    """
    Normalizes a registrar string, company name, or allotment URL to one of:
    LINKINTIME, KFINTECH, BIGSHARE, SKYLINE, CAMEO, PURVA, MAASHITLA, OTHER.
    Returns None if raw_val is empty or None.
    """
    if not raw_val:
        return None

    val = str(raw_val).strip()
    if not val or val.lower() in {"-", "null", "none", "tba", "n/a"}:
        return None

    lower_val = val.lower()

    # 1. URL domain or parameter checks
    if any(k in lower_val for k in ["mufg.com", "linkintime"]):
        return CanonicalRegistrar.LINKINTIME
    if "kfintech" in lower_val or "karvy" in lower_val:
        return CanonicalRegistrar.KFINTECH
    if "bigshare" in lower_val:
        return CanonicalRegistrar.BIGSHARE
    if "skylinerta" in lower_val or "skyline" in lower_val:
        return CanonicalRegistrar.SKYLINE
    if "cameoindia" in lower_val or "cameo" in lower_val:
        return CanonicalRegistrar.CAMEO
    if "purvashare" in lower_val or "purva" in lower_val:
        return CanonicalRegistrar.PURVA
    if "maashitla" in lower_val:
        return CanonicalRegistrar.MAASHITLA

    # 2. Name string keyword checks
    if any(k in lower_val for k in ["link intime", "linkintime", "mufg"]):
        return CanonicalRegistrar.LINKINTIME
    if any(k in lower_val for k in ["kfin", "karvy"]):
        return CanonicalRegistrar.KFINTECH
    if "bigshare" in lower_val:
        return CanonicalRegistrar.BIGSHARE
    if "skyline" in lower_val:
        return CanonicalRegistrar.SKYLINE
    if "cameo" in lower_val:
        return CanonicalRegistrar.CAMEO
    if "purva" in lower_val:
        return CanonicalRegistrar.PURVA
    if "maashitla" in lower_val:
        return CanonicalRegistrar.MAASHITLA

    # Canonical values directly
    upper_val = val.upper()
    if upper_val in ALL_CANONICAL_REGISTRARS:
        return upper_val

    return CanonicalRegistrar.OTHER
