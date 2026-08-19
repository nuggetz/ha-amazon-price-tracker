"""Exceptions shared across the integration."""

from __future__ import annotations


class AmazonBlockedError(Exception):
    """Amazon served an anti-bot wall instead of the page we asked for.

    Raised both when a fetched page turns out to be an interstitial and when a
    marketplace is in cooldown and the request was never sent.
    """


# Historical name from before the "CAPTCHA" wall was only one of several walls.
AmazonCaptchaError = AmazonBlockedError
