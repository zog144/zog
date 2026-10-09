"""Explicit transport-only retry signal. Local I/O errors never imply retry."""
import errno
import http.client
import socket
import ssl
import urllib.error
from zog.host_install.state_contract import StateError


class RetryableTransport(StateError):
    def __init__(self):
        super().__init__('managed-network-retry', 'Temporary transport failure; durable request retained')


def classify(error):
    """Called only around HTTPS open/read, never around state/key/CA operations."""
    if isinstance(error, urllib.error.HTTPError):
        retry = error.code in (408, 429, 502, 503, 504)
        error.close()
        if retry: raise RetryableTransport() from error
        raise StateError('managed-http-refused', 'Non-retryable HTTP response') from error
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, ssl.SSLError):
        raise StateError('managed-tls-failure', 'TLS verification or protocol failure') from error
    if isinstance(reason, (TimeoutError, ConnectionError, http.client.RemoteDisconnected, http.client.IncompleteRead)):
        raise RetryableTransport() from error
    if isinstance(reason, socket.gaierror) and reason.errno == socket.EAI_AGAIN:
        raise RetryableTransport() from error
    if isinstance(reason, OSError) and reason.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN, errno.ETIMEDOUT):
        raise RetryableTransport() from error
    raise StateError('managed-network-failure', 'Unclassified transport failure requires inspection') from error
