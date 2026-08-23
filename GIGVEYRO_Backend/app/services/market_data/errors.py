class ProviderError(Exception):
    """Base error for normalized public market provider failures."""


class ProviderUnavailable(ProviderError):
    """Provider cannot currently serve a quote."""


class ProviderTimeout(ProviderUnavailable):
    """Provider exceeded the bounded request timeout."""


class ProviderRateLimited(ProviderUnavailable):
    """Provider rejected the request due to a rate limit."""


class ProviderBadResponse(ProviderUnavailable):
    """Provider returned an invalid or unsupported response shape."""


class ProviderUnsupportedSymbol(ProviderError):
    """Symbol is outside the configured GIGVEYRO whitelist or unsupported upstream."""
