"""Independent business profiles; defaults are hypotheses, not demographic estimates."""
from .cn_equity import PROFILE as CN_EQUITY
from .us_equity import PROFILE as US_EQUITY

PROFILES = {profile.key: profile for profile in (CN_EQUITY, US_EQUITY)}


def get_profile(market="cn_equity"):
    if market not in PROFILES:
        raise ValueError("market must be cn_equity or us_equity")
    return PROFILES[market]
