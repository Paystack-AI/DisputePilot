"""Exception hierarchy for LLM provider calls and output handling.

Errors are grouped by what the provider chain should do next: fail over to the next
provider, retry the same provider, or stop and publish ai:error.
"""


class LLMError(Exception):
    """Base class for every AI worker LLM failure."""

    # True when the ordered chain may try the next provider.
    failover: bool = True
    # True when the same provider may be called again.
    retryable: bool = False


class LLMRateLimitError(LLMError):
    """The provider rejected the call because of a rate limit (429)."""

    retryable = True


class LLMQuotaError(LLMError):
    """The provider account is out of quota for the requested model."""


class LLMProviderServerError(LLMError):
    """The provider returned a 5xx response."""

    retryable = True


class LLMTimeoutError(LLMError):
    """One provider attempt exceeded its per-attempt timeout."""

    retryable = True


class LLMNetworkError(LLMError):
    """The provider could not be reached (connection, DNS, transport)."""

    retryable = True


class LLMAuthenticationError(LLMError):
    """The provider rejected the API key."""

    failover = False


class LLMBadRequestError(LLMError):
    """The provider rejected the request payload (400/422).

    A bad request is a bug in our request construction, so trying another provider
    with the same payload is not useful.
    """

    failover = False


class LLMSafetyBlockError(LLMError):
    """The provider blocked the output for safety reasons.

    Handled separately from transport and validation failures; it is not retried as a
    provider failure.
    """

    failover = False


class LLMUnparseableOutputError(LLMError):
    """The provider response could not be parsed or failed schema validation."""

    retryable = True


class LLMAllProvidersFailedError(LLMError):
    """Every provider in the ordered chain failed."""

    failover = False


class LLMConfigurationError(LLMError):
    """A required setting (API key, model id) is missing or invalid."""

    failover = False
