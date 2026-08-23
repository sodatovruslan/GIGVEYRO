class FiatProviderError(Exception):
    """Base error for normalized fiat-rate failures."""


class FiatProviderUnavailable(FiatProviderError):
    """Provider cannot currently serve the requested fiat quote."""


class FiatProviderTimeout(FiatProviderUnavailable):
    """Provider exceeded the bounded HTTP timeout."""


class FiatProviderRateLimited(FiatProviderUnavailable):
    """Provider rejected the request due to rate limiting."""


class FiatProviderBadResponse(FiatProviderUnavailable):
    """Provider response was malformed or failed validation."""


class FiatProviderStale(FiatProviderUnavailable):
    """Provider quote is older than the configured maximum age."""


class FiatProviderUnsupportedPair(FiatProviderError):
    """Provider does not support the requested fiat pair."""
