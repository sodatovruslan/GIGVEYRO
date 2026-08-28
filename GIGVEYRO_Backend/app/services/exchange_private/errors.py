class ExchangePrivateError(Exception):
    """Safe normalized private-exchange failure without request secrets."""


class ExchangePrivateUnavailable(ExchangePrivateError):
    pass


class ExchangePrivateTimeout(ExchangePrivateUnavailable):
    pass


class ExchangePrivateRateLimited(ExchangePrivateUnavailable):
    pass


class ExchangePrivateAuthenticationError(ExchangePrivateError):
    pass


class ExchangePrivatePermissionError(ExchangePrivateError):
    pass


class ExchangePrivateTimestampError(ExchangePrivateError):
    pass


class ExchangePrivateBadResponse(ExchangePrivateError):
    pass
