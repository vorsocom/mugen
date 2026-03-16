"""Unit tests for billing action services (invoice/subscription/payment allocation)."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.billing.service import invoice as invoice_mod
from mugen.core.plugin.billing.service import payment_allocation as payment_alloc_mod
from mugen.core.plugin.billing.service import subscription as subscription_mod
from mugen.core.plugin.billing.service.invoice import InvoiceService
from mugen.core.plugin.billing.service.payment_allocation import PaymentAllocationService
from mugen.core.plugin.billing.service.subscription import SubscriptionService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None, **_kwargs):
    raise _AbortCalled(code, message)


class _AsyncCM:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestMugenBillingServiceActions(unittest.IsolatedAsyncioTestCase):
    """Covers action helper branches and status/concurrency paths."""

    async def test_invoice_get_for_action_paths(self) -> None:
        svc = InvoiceService(table="invoices", rsg=object())

        current = SimpleNamespace(status="draft")
        svc.get = AsyncMock(return_value=current)
        resolved = await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
        self.assertIs(resolved, current)

        svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
        with patch.object(invoice_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, None])
        with patch.object(invoice_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 404)

        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("db")])
        with patch.object(invoice_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, SimpleNamespace(status="issued")])
        with patch.object(invoice_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 409)

    async def test_invoice_action_status_and_update_branches(self) -> None:
        svc = InvoiceService(table="invoices", rsg=object())
        where = {"id": uuid.uuid4()}
        data = SimpleNamespace(row_version=1)
        common = {
            "tenant_id": uuid.uuid4(),
            "entity_id": uuid.uuid4(),
            "where": where,
            "auth_user_id": uuid.uuid4(),
            "data": data,
        }

        scenarios = [
            ("action_issue", "draft", "paid"),
            ("action_void", "draft", "paid"),
            ("action_mark_paid", "issued", "draft"),
        ]
        for method_name, valid_status, invalid_status in scenarios:
            method = getattr(svc, method_name)

            with self.subTest(method=method_name, branch="invalid_status"):
                svc._get_for_action = AsyncMock(return_value=SimpleNamespace(status=invalid_status))  # pylint: disable=protected-access
                with patch.object(invoice_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as ex:
                        await method(**common)
                    self.assertEqual(ex.exception.code, 409)

            with self.subTest(method=method_name, branch="row_version_conflict"):
                svc._get_for_action = AsyncMock(return_value=SimpleNamespace(status=valid_status))  # pylint: disable=protected-access
                svc.update_with_row_version = AsyncMock(side_effect=RowVersionConflict("invoices"))
                with patch.object(invoice_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as ex:
                        await method(**common)
                    self.assertEqual(ex.exception.code, 409)

            with self.subTest(method=method_name, branch="sqlalchemy_error"):
                svc._get_for_action = AsyncMock(return_value=SimpleNamespace(status=valid_status))  # pylint: disable=protected-access
                svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
                with patch.object(invoice_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as ex:
                        await method(**common)
                    self.assertEqual(ex.exception.code, 500)

            with self.subTest(method=method_name, branch="none_updated"):
                svc._get_for_action = AsyncMock(return_value=SimpleNamespace(status=valid_status))  # pylint: disable=protected-access
                svc.update_with_row_version = AsyncMock(return_value=None)
                with patch.object(invoice_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as ex:
                        await method(**common)
                    self.assertEqual(ex.exception.code, 404)

            with self.subTest(method=method_name, branch="success"):
                svc._get_for_action = AsyncMock(return_value=SimpleNamespace(status=valid_status))  # pylint: disable=protected-access
                svc.update_with_row_version = AsyncMock(return_value=SimpleNamespace())
                result = await method(**common)
                self.assertEqual(result, ("", 204))

    async def test_subscription_get_for_action_and_action_branches(self) -> None:
        svc = SubscriptionService(table="subscriptions", rsg=object())

        current = SimpleNamespace(status="active")
        svc.get = AsyncMock(return_value=current)
        resolved = await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
        self.assertIs(resolved, current)

        svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, None])
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 404)

        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("db")])
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, SimpleNamespace(status="paused")])
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 409)

        where = {"id": uuid.uuid4()}
        data = SimpleNamespace(row_version=1)
        common = {
            "tenant_id": uuid.uuid4(),
            "entity_id": uuid.uuid4(),
            "where": where,
            "auth_user_id": uuid.uuid4(),
            "data": data,
        }
        scenarios = [
            ("action_cancel", "active", "canceled"),
            ("action_reactivate", "canceled", "active"),
        ]
        for method_name, valid_status, invalid_status in scenarios:
            method = getattr(svc, method_name)

            with self.subTest(method=method_name, branch="invalid_status"):
                svc._get_for_action = AsyncMock(return_value=SimpleNamespace(status=invalid_status))  # pylint: disable=protected-access
                with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as ex:
                        await method(**common)
                    self.assertEqual(ex.exception.code, 409)

            with self.subTest(method=method_name, branch="row_version_conflict"):
                svc._get_for_action = AsyncMock(return_value=SimpleNamespace(status=valid_status))  # pylint: disable=protected-access
                svc.update_with_row_version = AsyncMock(
                    side_effect=RowVersionConflict("subscriptions")
                )
                with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as ex:
                        await method(**common)
                    self.assertEqual(ex.exception.code, 409)

            with self.subTest(method=method_name, branch="sqlalchemy_error"):
                svc._get_for_action = AsyncMock(return_value=SimpleNamespace(status=valid_status))  # pylint: disable=protected-access
                svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
                with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as ex:
                        await method(**common)
                    self.assertEqual(ex.exception.code, 500)

            with self.subTest(method=method_name, branch="none_updated"):
                svc._get_for_action = AsyncMock(return_value=SimpleNamespace(status=valid_status))  # pylint: disable=protected-access
                svc.update_with_row_version = AsyncMock(return_value=None)
                with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as ex:
                        await method(**common)
                    self.assertEqual(ex.exception.code, 404)

            with self.subTest(method=method_name, branch="success"):
                svc._get_for_action = AsyncMock(return_value=SimpleNamespace(status=valid_status))  # pylint: disable=protected-access
                svc.update_with_row_version = AsyncMock(return_value=SimpleNamespace())
                result = await method(**common)
                self.assertEqual(result, ("", 204))

    async def test_payment_allocation_sync_and_action_branches(self) -> None:
        svc = PaymentAllocationService(table="payment_allocations", rsg=object())

        current = SimpleNamespace(invoice_id=uuid.uuid4())
        svc.get = AsyncMock(return_value=current)
        resolved = await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
        self.assertIs(resolved, current)

        svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
        with patch.object(payment_alloc_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, None])
        with patch.object(payment_alloc_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 404)

        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("db")])
        with patch.object(payment_alloc_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, SimpleNamespace(invoice_id=uuid.uuid4())])
        with patch.object(payment_alloc_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where={"id": uuid.uuid4()}, expected_row_version=1)  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 409)

        with patch.object(payment_alloc_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._sync_invoice_from_allocations(  # pylint: disable=protected-access
                    tenant_id=uuid.uuid4(),
                    invoice_id=uuid.uuid4(),
                )
            self.assertEqual(ex.exception.code, 500)

        session = SimpleNamespace(execute=AsyncMock(return_value=None))
        rsg_with_session = SimpleNamespace(raw_session=lambda: _AsyncCM(session))
        svc_with_session = PaymentAllocationService(
            table="payment_allocations",
            rsg=rsg_with_session,
        )
        await svc_with_session._sync_invoice_from_allocations(  # pylint: disable=protected-access
            tenant_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
        )
        session.execute.assert_awaited_once()

        where = {"id": uuid.uuid4()}
        common = {
            "tenant_id": uuid.uuid4(),
            "entity_id": uuid.uuid4(),
            "where": where,
            "auth_user_id": uuid.uuid4(),
            "data": SimpleNamespace(row_version=1),
        }

        svc_with_session._get_for_action = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(invoice_id=None)
        )
        with patch.object(payment_alloc_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc_with_session.action_sync_invoice(**common)
            self.assertEqual(ex.exception.code, 409)

        svc_with_session._get_for_action = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(invoice_id=uuid.uuid4())
        )
        svc_with_session._sync_invoice_from_allocations = AsyncMock(  # pylint: disable=protected-access
            side_effect=SQLAlchemyError("db")
        )
        with patch.object(payment_alloc_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc_with_session.action_sync_invoice(**common)
            self.assertEqual(ex.exception.code, 500)

        svc_with_session._get_for_action = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(invoice_id=uuid.uuid4())
        )
        svc_with_session._sync_invoice_from_allocations = AsyncMock(return_value=None)  # pylint: disable=protected-access
        result = await svc_with_session.action_sync_invoice(**common)
        self.assertEqual(result, ("", 204))
