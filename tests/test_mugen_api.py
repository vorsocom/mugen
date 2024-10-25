"""Provides test suite for mugen.core.api.endpoint."""

import functools
import unittest
import unittest.mock


def dummy_decorator(arg=None, **_dargs):
    """Dummy decorator."""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return wrapper

    if callable(arg):
        return decorator(arg)

    return decorator


mpr_mock = unittest.mock.patch(
    target="util.decorator.matrix_platform_required",
    new=dummy_decorator,
)

wpr_mock = unittest.mock.patch(
    target="util.decorator.whatsapp_platform_required",
    new=dummy_decorator,
)

walr_mock = unittest.mock.patch(
    target="util.decorator.whatsapp_server_ip_allow_list_required",
    new=dummy_decorator,
)

wsvr_mock = unittest.mock.patch(
    target="util.decorator.whatsapp_request_signature_verification_required",
    new=dummy_decorator,
)

mpr_mock.start()
wpr_mock.start()
walr_mock.start()
wsvr_mock.start()

loader = unittest.TestLoader()
suite = loader.discover("tests/api")

runner = unittest.TextTestRunner()
runner.run(suite)

mpr_mock.stop()
wpr_mock.stop()
walr_mock.stop()
wsvr_mock.stop()
