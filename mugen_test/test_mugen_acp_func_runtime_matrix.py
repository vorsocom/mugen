"""Unit tests for mugen.core.plugin.acp.api.func_runtime_matrix."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import SQLAlchemyError

from mugen.core.plugin.acp.api import func_runtime_matrix

_ACP_NAMESPACE = "com.test.admin"
_AUTH_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000901")
_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000111")
_OTHER_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000222")
_PROFILE_A_ID = "00000000-0000-0000-0000-000000000301"
_PROFILE_B_ID = "00000000-0000-0000-0000-000000000302"


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


def _config() -> SimpleNamespace:
    return SimpleNamespace(acp=SimpleNamespace(namespace=_ACP_NAMESPACE))


def _entry(
    *,
    client_profile_id: str = "00000000-0000-0000-0000-000000000123",
    client_profile_key: str = "default",
    recipient_user_id: str = "@bot:example.com",
    public_name: str = "device-a",
    session_id: str = "DEV-A",
    session_key: str = "ABCD 1234",
    tenant_id: uuid.UUID | None = None,
) -> dict[str, str]:
    row = {
        "client_profile_id": client_profile_id,
        "client_profile_key": client_profile_key,
        "recipient_user_id": recipient_user_id,
        "public_name": public_name,
        "session_id": session_id,
        "session_key": session_key,
    }
    if tenant_id is not None:
        row["tenant_id"] = str(tenant_id)
    return row


def _user(*, global_admin: bool = False) -> SimpleNamespace:
    roles = []
    if global_admin:
        roles = [
            SimpleNamespace(
                namespace=_ACP_NAMESPACE,
                name="administrator",
            )
        ]
    return SimpleNamespace(
        id=_AUTH_USER_ID,
        global_roles=roles,
    )


class _UserServiceStub:
    def __init__(self, user: SimpleNamespace | None) -> None:
        self._user = user
        self.calls: list[dict[str, object]] = []

    async def get_expanded(self, where: dict[str, object]) -> SimpleNamespace | None:
        self.calls.append(dict(where))
        return self._user


class _TenantMembershipServiceStub:
    def __init__(self, membership: SimpleNamespace | None) -> None:
        self._membership = membership
        self.calls: list[dict[str, object]] = []

    async def get(self, where: dict[str, object]) -> SimpleNamespace | None:
        self.calls.append(dict(where))
        return self._membership


class _RegistryStub:
    def __init__(self, services: dict[str, object]) -> None:
        self._services = services

    def get_resource_by_type(self, edm_type_name: str) -> SimpleNamespace:
        return SimpleNamespace(service_key=f"svc:{edm_type_name}")

    def get_edm_service(self, service_key: str):
        return self._services[service_key]


class TestMugenAcpFuncRuntimeMatrix(unittest.IsolatedAsyncioTestCase):
    """Covers Matrix runtime device verification ACP endpoint behavior."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        user_service = object()
        tenant_membership_service = object()
        registry = _RegistryStub(
            {
                "svc:ACP.User": user_service,
                "svc:ACP.TenantMembership": tenant_membership_service,
            }
        )
        container = SimpleNamespace(
            config="config",
            matrix_client="matrix-client",
            logging_gateway="logger",
            get_required_ext_service=Mock(return_value=registry),
        )
        with patch.object(func_runtime_matrix.di, "container", new=container):
            self.assertEqual(
                func_runtime_matrix._config_provider(),
                "config",
            )
            self.assertEqual(
                func_runtime_matrix._matrix_client_provider(),
                "matrix-client",
            )
            self.assertEqual(func_runtime_matrix._logger_provider(), "logger")
            self.assertIs(func_runtime_matrix._registry_provider(), registry)
            self.assertIs(
                func_runtime_matrix._user_service_provider(),
                user_service,
            )
            self.assertIs(
                func_runtime_matrix._tenant_membership_service_provider(),
                tenant_membership_service,
            )

    async def test_endpoint_lists_active_runtime_profiles(self) -> None:
        endpoint = func_runtime_matrix.matrix_device_verification_data.__wrapped__
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(
                return_value=[_entry()]
            )
        )
        logger = Mock()

        with patch.object(
            func_runtime_matrix,
            "request",
            new=SimpleNamespace(args={}),
        ):
            response = await endpoint(
                matrix_client_provider=lambda: matrix_client,
                logger_provider=lambda: logger,
                auth_user="user-id",
            )

        self.assertEqual(response, {"value": [_entry()]})
        matrix_client.active_device_verification_data.assert_awaited_once_with(
            client_profile_id=None
        )

    async def test_endpoint_strips_internal_metadata_from_admin_response(self) -> None:
        endpoint = func_runtime_matrix.matrix_device_verification_data.__wrapped__
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(
                return_value=[
                    _entry(tenant_id=_TENANT_ID),
                ]
            )
        )

        with patch.object(
            func_runtime_matrix,
            "request",
            new=SimpleNamespace(args={}),
        ):
            response = await endpoint(
                matrix_client_provider=lambda: matrix_client,
                logger_provider=lambda: Mock(),
                auth_user="user-id",
            )

        self.assertEqual(response, {"value": [_entry()]})

    async def test_endpoint_filters_one_client_profile(self) -> None:
        endpoint = func_runtime_matrix.matrix_device_verification_data.__wrapped__
        client_profile_id = "00000000-0000-0000-0000-000000000123"
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(
                return_value=[_entry(client_profile_id=client_profile_id)]
            )
        )

        with patch.object(
            func_runtime_matrix,
            "request",
            new=SimpleNamespace(args={"client_profile_id": f" {client_profile_id} "}),
        ):
            response = await endpoint(
                matrix_client_provider=lambda: matrix_client,
                logger_provider=lambda: Mock(),
                auth_user="user-id",
            )

        self.assertEqual(response["value"][0]["client_profile_id"], client_profile_id)
        matrix_client.active_device_verification_data.assert_awaited_once_with(
            client_profile_id=client_profile_id
        )

    async def test_endpoint_rejects_invalid_client_profile_filter(self) -> None:
        endpoint = func_runtime_matrix.matrix_device_verification_data.__wrapped__
        logger = Mock()

        with (
            patch.object(func_runtime_matrix, "abort", side_effect=_abort_raiser),
            patch.object(
                func_runtime_matrix,
                "request",
                new=SimpleNamespace(args={"client_profile_id": "bad-uuid"}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    matrix_client_provider=lambda: SimpleNamespace(),
                    logger_provider=lambda: logger,
                    auth_user="user-id",
                )

        self.assertEqual(ex.exception.code, 400)
        logger.debug.assert_called_once_with(
            "Invalid Matrix device verification client_profile_id filter."
        )

    async def test_endpoint_returns_404_for_missing_active_profile(self) -> None:
        endpoint = func_runtime_matrix.matrix_device_verification_data.__wrapped__
        client_profile_id = "00000000-0000-0000-0000-000000000123"
        logger = Mock()
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(return_value=[])
        )

        with (
            patch.object(func_runtime_matrix, "abort", side_effect=_abort_raiser),
            patch.object(
                func_runtime_matrix,
                "request",
                new=SimpleNamespace(args={"client_profile_id": client_profile_id}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    matrix_client_provider=lambda: matrix_client,
                    logger_provider=lambda: logger,
                    auth_user="user-id",
                )

        self.assertEqual(ex.exception.code, 404)

    async def test_tenant_endpoint_allows_active_owner_and_admin_memberships(
        self,
    ) -> None:
        endpoint = (
            func_runtime_matrix.tenant_matrix_device_verification_data.__wrapped__
        )
        rows = [
            _entry(
                client_profile_id="00000000-0000-0000-0000-000000000123",
                tenant_id=_TENANT_ID,
            ),
            _entry(
                client_profile_id="00000000-0000-0000-0000-000000000124",
                client_profile_key="secondary",
                public_name="device-b",
                session_id="DEV-B",
                session_key="WXYZ 9876",
                tenant_id=_OTHER_TENANT_ID,
            ),
        ]

        for role_in_tenant in ("owner", "admin"):
            with self.subTest(role_in_tenant=role_in_tenant):
                matrix_client = SimpleNamespace(
                    active_device_verification_data=AsyncMock(return_value=rows)
                )
                user_service = _UserServiceStub(_user())
                membership_service = _TenantMembershipServiceStub(
                    SimpleNamespace(role_in_tenant=role_in_tenant)
                )

                with patch.object(
                    func_runtime_matrix,
                    "request",
                    new=SimpleNamespace(args={}),
                ):
                    response = await endpoint(
                        tenant_id=str(_TENANT_ID),
                        auth_user=str(_AUTH_USER_ID),
                        config_provider=_config,
                        matrix_client_provider=lambda: matrix_client,
                        logger_provider=Mock,
                        tenant_membership_service_provider=lambda: membership_service,
                        user_service_provider=lambda: user_service,
                    )

                self.assertEqual(response, {"value": [_entry()]})
                matrix_client.active_device_verification_data.assert_awaited_once_with(
                    client_profile_id=None,
                    include_internal=True,
                )
                self.assertEqual(
                    user_service.calls,
                    [{"id": _AUTH_USER_ID}],
                )
                self.assertEqual(
                    membership_service.calls,
                    [
                        {
                            "tenant_id": _TENANT_ID,
                            "user_id": _AUTH_USER_ID,
                            "status": "active",
                        }
                    ],
                )

    async def test_tenant_endpoint_returns_filtered_client_profile(self) -> None:
        endpoint = (
            func_runtime_matrix.tenant_matrix_device_verification_data.__wrapped__
        )
        client_profile_id = "00000000-0000-0000-0000-000000000123"
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(
                return_value=[
                    _entry(
                        client_profile_id=client_profile_id,
                        tenant_id=_TENANT_ID,
                    ),
                    _entry(
                        client_profile_id="00000000-0000-0000-0000-000000000124",
                        tenant_id=_TENANT_ID,
                    ),
                ]
            )
        )
        user_service = _UserServiceStub(_user())
        membership_service = _TenantMembershipServiceStub(
            SimpleNamespace(role_in_tenant="owner")
        )

        with patch.object(
            func_runtime_matrix,
            "request",
            new=SimpleNamespace(args={"client_profile_id": client_profile_id}),
        ):
            response = await endpoint(
                tenant_id=str(_TENANT_ID),
                auth_user=str(_AUTH_USER_ID),
                config_provider=_config,
                matrix_client_provider=lambda: matrix_client,
                logger_provider=Mock,
                tenant_membership_service_provider=lambda: membership_service,
                user_service_provider=lambda: user_service,
            )

        self.assertEqual(
            response,
            {"value": [_entry(client_profile_id=client_profile_id)]},
        )
        matrix_client.active_device_verification_data.assert_awaited_once_with(
            client_profile_id=client_profile_id,
            include_internal=True,
        )

    async def test_tenant_endpoint_rejects_invalid_tenant_or_profile_uuids(
        self,
    ) -> None:
        endpoint = (
            func_runtime_matrix.tenant_matrix_device_verification_data.__wrapped__
        )
        logger = Mock()
        user_service = _UserServiceStub(_user())
        membership_service = _TenantMembershipServiceStub(
            SimpleNamespace(role_in_tenant="owner")
        )

        with (
            patch.object(func_runtime_matrix, "abort", side_effect=_abort_raiser),
            patch.object(
                func_runtime_matrix,
                "request",
                new=SimpleNamespace(args={}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id="bad-uuid",
                    auth_user=str(_AUTH_USER_ID),
                    config_provider=_config,
                    matrix_client_provider=SimpleNamespace,
                    logger_provider=lambda: logger,
                    tenant_membership_service_provider=lambda: membership_service,
                    user_service_provider=lambda: user_service,
                )

        self.assertEqual(ex.exception.code, 400)
        logger.debug.assert_called_once_with(
            "Invalid Matrix device verification tenant_id filter."
        )

        logger = Mock()
        with (
            patch.object(func_runtime_matrix, "abort", side_effect=_abort_raiser),
            patch.object(
                func_runtime_matrix,
                "request",
                new=SimpleNamespace(args={"client_profile_id": "bad-uuid"}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id=str(_TENANT_ID),
                    auth_user=str(_AUTH_USER_ID),
                    config_provider=_config,
                    matrix_client_provider=SimpleNamespace,
                    logger_provider=lambda: logger,
                    tenant_membership_service_provider=lambda: membership_service,
                    user_service_provider=lambda: user_service,
                )

        self.assertEqual(ex.exception.code, 400)
        logger.debug.assert_called_once_with(
            "Invalid Matrix device verification client_profile_id filter."
        )

    async def test_tenant_endpoint_denies_member_and_missing_active_memberships(
        self,
    ) -> None:
        endpoint = (
            func_runtime_matrix.tenant_matrix_device_verification_data.__wrapped__
        )
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(return_value=[])
        )
        user_service = _UserServiceStub(_user())

        for label, membership in (
            ("member", SimpleNamespace(role_in_tenant="member")),
            ("suspended-owner", None),
            ("different-tenant", None),
        ):
            with self.subTest(label=label):
                logger = Mock()
                membership_service = _TenantMembershipServiceStub(membership)
                with (
                    patch.object(
                        func_runtime_matrix,
                        "abort",
                        side_effect=_abort_raiser,
                    ),
                    patch.object(
                        func_runtime_matrix,
                        "request",
                        new=SimpleNamespace(args={}),
                    ),
                ):
                    with self.assertRaises(_AbortCalled) as ex:
                        await endpoint(
                            tenant_id=str(_TENANT_ID),
                            auth_user=str(_AUTH_USER_ID),
                            config_provider=_config,
                            matrix_client_provider=lambda: matrix_client,
                            logger_provider=lambda: logger,
                            tenant_membership_service_provider=(
                                lambda: membership_service
                            ),
                            user_service_provider=lambda: user_service,
                        )

                self.assertEqual(ex.exception.code, 403)

    async def test_tenant_endpoint_allows_global_admin_without_membership(
        self,
    ) -> None:
        endpoint = (
            func_runtime_matrix.tenant_matrix_device_verification_data.__wrapped__
        )
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(
                return_value=[
                    _entry(tenant_id=_TENANT_ID),
                    _entry(
                        client_profile_id="00000000-0000-0000-0000-000000000124",
                        tenant_id=_OTHER_TENANT_ID,
                    ),
                ]
            )
        )
        user_service = _UserServiceStub(_user(global_admin=True))
        membership_service = _TenantMembershipServiceStub(None)

        with patch.object(
            func_runtime_matrix,
            "request",
            new=SimpleNamespace(args={}),
        ):
            response = await endpoint(
                tenant_id=str(_TENANT_ID),
                auth_user=str(_AUTH_USER_ID),
                config_provider=_config,
                matrix_client_provider=lambda: matrix_client,
                logger_provider=Mock,
                tenant_membership_service_provider=lambda: membership_service,
                user_service_provider=lambda: user_service,
            )

        self.assertEqual(response, {"value": [_entry()]})
        self.assertEqual(membership_service.calls, [])

    async def test_tenant_endpoint_rejects_invalid_auth_user_with_500(self) -> None:
        endpoint = (
            func_runtime_matrix.tenant_matrix_device_verification_data.__wrapped__
        )
        logger = Mock()

        with (
            patch.object(func_runtime_matrix, "abort", side_effect=_abort_raiser),
            patch.object(
                func_runtime_matrix,
                "request",
                new=SimpleNamespace(args={}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id=str(_TENANT_ID),
                    auth_user="bad-auth-user",
                    config_provider=_config,
                    matrix_client_provider=SimpleNamespace,
                    logger_provider=lambda: logger,
                    tenant_membership_service_provider=(
                        lambda: _TenantMembershipServiceStub(None)
                    ),
                    user_service_provider=lambda: _UserServiceStub(_user()),
                )

        self.assertEqual(ex.exception.code, 500)
        logger.error.assert_called_once_with(
            "Invalid auth_user supplied to tenant Matrix runtime lookup."
        )

    async def test_tenant_endpoint_returns_500_when_user_lookup_fails(self) -> None:
        endpoint = (
            func_runtime_matrix.tenant_matrix_device_verification_data.__wrapped__
        )
        logger = Mock()
        user_service = SimpleNamespace(
            get_expanded=AsyncMock(side_effect=SQLAlchemyError("user lookup failed"))
        )

        with (
            patch.object(func_runtime_matrix, "abort", side_effect=_abort_raiser),
            patch.object(
                func_runtime_matrix,
                "request",
                new=SimpleNamespace(args={}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id=str(_TENANT_ID),
                    auth_user=str(_AUTH_USER_ID),
                    config_provider=_config,
                    matrix_client_provider=SimpleNamespace,
                    logger_provider=lambda: logger,
                    tenant_membership_service_provider=(
                        lambda: _TenantMembershipServiceStub(None)
                    ),
                    user_service_provider=lambda: user_service,
                )

        self.assertEqual(ex.exception.code, 500)
        self.assertIsInstance(logger.error.call_args.args[0], SQLAlchemyError)

    async def test_tenant_endpoint_returns_500_when_membership_lookup_fails(
        self,
    ) -> None:
        endpoint = (
            func_runtime_matrix.tenant_matrix_device_verification_data.__wrapped__
        )
        logger = Mock()
        membership_service = SimpleNamespace(
            get=AsyncMock(side_effect=SQLAlchemyError("membership lookup failed"))
        )

        with (
            patch.object(func_runtime_matrix, "abort", side_effect=_abort_raiser),
            patch.object(
                func_runtime_matrix,
                "request",
                new=SimpleNamespace(args={}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id=str(_TENANT_ID),
                    auth_user=str(_AUTH_USER_ID),
                    config_provider=_config,
                    matrix_client_provider=SimpleNamespace,
                    logger_provider=lambda: logger,
                    tenant_membership_service_provider=lambda: membership_service,
                    user_service_provider=lambda: _UserServiceStub(_user()),
                )

        self.assertEqual(ex.exception.code, 500)
        self.assertIsInstance(logger.error.call_args.args[0], SQLAlchemyError)

    async def test_tenant_endpoint_returns_404_for_non_owned_or_missing_profile(
        self,
    ) -> None:
        endpoint = (
            func_runtime_matrix.tenant_matrix_device_verification_data.__wrapped__
        )
        client_profile_id = "00000000-0000-0000-0000-000000000123"
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(
                return_value=[
                    _entry(
                        client_profile_id=client_profile_id,
                        tenant_id=_OTHER_TENANT_ID,
                    )
                ]
            )
        )
        user_service = _UserServiceStub(_user())
        membership_service = _TenantMembershipServiceStub(
            SimpleNamespace(role_in_tenant="owner")
        )

        with (
            patch.object(func_runtime_matrix, "abort", side_effect=_abort_raiser),
            patch.object(
                func_runtime_matrix,
                "request",
                new=SimpleNamespace(args={"client_profile_id": client_profile_id}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id=str(_TENANT_ID),
                    auth_user=str(_AUTH_USER_ID),
                    config_provider=_config,
                    matrix_client_provider=lambda: matrix_client,
                    logger_provider=Mock,
                    tenant_membership_service_provider=lambda: membership_service,
                    user_service_provider=lambda: user_service,
                )

        self.assertEqual(ex.exception.code, 404)

    async def test_tenant_endpoint_returns_empty_when_no_runtime_profiles_match(
        self,
    ) -> None:
        endpoint = (
            func_runtime_matrix.tenant_matrix_device_verification_data.__wrapped__
        )
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(
                return_value=[_entry(tenant_id=_OTHER_TENANT_ID)]
            )
        )
        user_service = _UserServiceStub(_user())
        membership_service = _TenantMembershipServiceStub(
            SimpleNamespace(role_in_tenant="owner")
        )

        with patch.object(
            func_runtime_matrix,
            "request",
            new=SimpleNamespace(args={}),
        ):
            response = await endpoint(
                tenant_id=str(_TENANT_ID),
                auth_user=str(_AUTH_USER_ID),
                config_provider=_config,
                matrix_client_provider=lambda: matrix_client,
                logger_provider=Mock,
                tenant_membership_service_provider=lambda: membership_service,
                user_service_provider=lambda: user_service,
            )

        self.assertEqual(response, {"value": []})

    async def test_collect_device_verification_data_falls_back_to_single_client(
        self,
    ) -> None:
        entries = await (  # pylint: disable=protected-access
            func_runtime_matrix._collect_device_verification_data(
                SimpleNamespace(
                    device_verification_data=Mock(
                        return_value={
                            **_entry(client_profile_id=_PROFILE_A_ID),
                            "ignored": "value",
                        }
                    )
                ),
                client_profile_id=_PROFILE_A_ID,
            )
        )

        self.assertEqual(
            entries,
            [
                {
                    "client_profile_id": _PROFILE_A_ID,
                    "client_profile_key": "default",
                    "recipient_user_id": "@bot:example.com",
                    "public_name": "device-a",
                    "session_id": "DEV-A",
                    "session_key": "ABCD 1234",
                }
            ],
        )

    async def test_collect_device_verification_data_returns_empty_without_resolver(
        self,
    ) -> None:
        entries = await (  # pylint: disable=protected-access
            func_runtime_matrix._collect_device_verification_data(
                SimpleNamespace(),
                client_profile_id=None,
            )
        )

        self.assertEqual(entries, [])

    async def test_collect_device_verification_data_rejects_invalid_single_entry(
        self,
    ) -> None:
        entries = await (  # pylint: disable=protected-access
            func_runtime_matrix._collect_device_verification_data(
                SimpleNamespace(
                    device_verification_data=Mock(
                        return_value={"client_profile_key": "default"}
                    )
                ),
                client_profile_id=None,
            )
        )

        self.assertEqual(entries, [])

    async def test_collect_device_verification_data_rejects_mismatched_profile(
        self,
    ) -> None:
        entries = await (  # pylint: disable=protected-access
            func_runtime_matrix._collect_device_verification_data(
                SimpleNamespace(
                    device_verification_data=Mock(
                        return_value={
                            "client_profile_id": _PROFILE_A_ID,
                            "client_profile_key": "default",
                        }
                    )
                ),
                client_profile_id=_PROFILE_B_ID,
            )
        )

        self.assertEqual(entries, [])

    def test_normalize_entries_and_entry_reject_invalid_values(self) -> None:
        self.assertEqual(
            func_runtime_matrix._normalize_entries(  # pylint: disable=protected-access
                None
            ),
            [],
        )
        self.assertEqual(
            func_runtime_matrix._normalize_entries(  # pylint: disable=protected-access
                [
                    {"client_profile_key": "default"},
                    "bad-row",
                ]
            ),
            [],
        )
        self.assertIsNone(
            func_runtime_matrix._normalize_entry(  # pylint: disable=protected-access
                "bad-row"
            )
        )
        self.assertIsNone(
            func_runtime_matrix._normalize_entry(  # pylint: disable=protected-access
                {"client_profile_id": "  "}
            )
        )
        # pylint: disable=protected-access
        self.assertIsNone(
            func_runtime_matrix._normalize_uuid_value(None)
        )
        self.assertIsNone(
            func_runtime_matrix._normalize_uuid_value("")
        )
        self.assertFalse(
            func_runtime_matrix._is_global_admin(None, config=_config())
        )

    def test_internal_entry_helpers_filter_and_strip_tenant_metadata(self) -> None:
        # pylint: disable=protected-access
        internal_entries = func_runtime_matrix._normalize_entries(
            [
                _entry(tenant_id=_TENANT_ID),
                _entry(
                    client_profile_id="00000000-0000-0000-0000-000000000124",
                    tenant_id=_OTHER_TENANT_ID,
                ),
                {"client_profile_id": "bad", "tenant_id": "not-a-uuid"},
            ],
            include_internal=True,
        )

        self.assertEqual(
            func_runtime_matrix._filter_entries_for_tenant(
                internal_entries,
                tenant_id=str(_TENANT_ID),
            ),
            [_entry(tenant_id=_TENANT_ID)],
        )
        self.assertEqual(
            func_runtime_matrix._normalize_entries(internal_entries),
            [
                _entry(),
                _entry(
                    client_profile_id="00000000-0000-0000-0000-000000000124"
                ),
            ],
        )
        self.assertEqual(
            func_runtime_matrix._normalize_entries(  # pylint: disable=protected-access
                [_entry(tenant_id=None)],
                include_internal=True,
            ),
            [_entry()],
        )
