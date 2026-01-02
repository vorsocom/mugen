"""Provides a service for the User declarative model."""

__all__ = ["UserService"]

import re
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.contract.gateway.storage.rdbms.uow import IRelationalUnitOfWork
from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.service import (
    IGlobalRoleService,
    IGlobalRoleMembershipService,
    IPersonService,
    IRefreshTokenService,
    IUserService,
)
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.domain import UserDE


class UserService(
    IRelationalService[UserDE],
    IUserService,
):
    """A service for the User declarative model."""

    # pylint: disable=too-many-arguments
    # ylint: disable=too-many-positional-arguments
    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        config_provider=lambda: di.container.config,
        logger_provider=lambda: di.container.logging_gateway,
        registry_provider=lambda: di.container.get_ext_service("admin_registry"),
        **kwargs,
    ):
        super().__init__(
            de_type=UserDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

        self._config: SimpleNamespace = config_provider()
        self._logger: ILoggingGateway = logger_provider()

        registry: IAdminRegistry = registry_provider()
        self._resource = registry.get_resource_by_type("ACP.User")

        self._grole_svc: IGlobalRoleService = registry.get_edm_service(
            registry.get_resource_by_type("ACP.GlobalRole").service_key,
        )

        self._grole_mship_svc: IGlobalRoleMembershipService = registry.get_edm_service(
            registry.get_resource_by_type("ACP.GlobalRoleMembership").service_key,
        )

        self._person_svc: IPersonService = registry.get_edm_service(
            registry.get_resource_by_type("ACP.Person").service_key,
        )

        self._rtoken_svc: IRefreshTokenService = registry.get_edm_service(
            registry.get_resource_by_type("ACP.RefreshToken").service_key,
        )

    async def bump_token_version(self, where: Mapping[str, Any]) -> UserDE | None:
        user = await self.get(where)
        if user is not None:
            return await self.update(
                where,
                changes={"token_version": user.token_version + 1},
            )

    async def entity_action_delete(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Soft-delete a User."""
        try:
            user = await self.get({"id": entity_id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if user is None:
            self._logger.warning("User for deletion not found.")
            abort(404, "User not found.")

        if user.deleted_at is not None:
            self._logger.debug("User already deleted.")
            return "", 204

        update_time = datetime.now(timezone.utc)
        svc: ICrudServiceWithRowVersion = self
        try:
            updated = await svc.update_with_row_version(
                {"id": user.id},
                expected_row_version=data.row_version,
                changes={
                    "locked_at": update_time,
                    "locked_by_user_id": auth_user_id,
                    "deleted_at": update_time,
                    "deleted_by_user_id": auth_user_id,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        try:
            await self.bump_token_version({"id": updated.id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        return "", 204

    async def entity_action_lock(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Lock a User."""
        try:
            user = await self.get({"id": entity_id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if user is None:
            self._logger.warning("User for account lock not found.")
            abort(404, "User not found.")

        update_time = datetime.now(timezone.utc)
        svc: ICrudServiceWithRowVersion = self
        try:
            updated = await svc.update_with_row_version(
                {"id": user.id},
                expected_row_version=data.row_version,
                changes={
                    "locked_at": update_time,
                    "locked_by_user_id": auth_user_id,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        try:
            await self.bump_token_version({"id": updated.id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        return "", 204

    async def entity_action_resetpasswordadmin(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Reset a User's password. Performed by an admin."""
        row_version = data.row_version

        try:
            user = await self.get({"id": entity_id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        new_password = data.new_password.get_secret_value()

        if user is None:
            self.verify_password_hash(self._config.acp.login_dummy_hash, new_password)
            self._logger.debug("User for account lock not found.")
            abort(404, "User not found.")

        if new_password != data.confirm_new_password.get_secret_value():
            self._logger.debug("Password and password confirmation do not match")
            abort(400, "Password confirmation mismatch.")

        if (
            self._config.acp.enforce_password_policy
            and not self.validate_password_policy(new_password)
        ):
            abort(400, "Password does not adhere to policy.")

        update_time = datetime.now(timezone.utc)
        svc: ICrudServiceWithRowVersion = self
        try:
            updated = await svc.update_with_row_version(
                {"id": user.id},
                expected_row_version=row_version,
                changes={
                    "password_hash": self.get_password_hash(new_password),
                    "password_changed_at": update_time,
                    "password_changed_by_user_id": auth_user_id,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        try:
            await self.bump_token_version({"id": updated.id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        try:
            await self._rsg.delete_many(self._rtoken_svc.table, {"user_id": updated.id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        return "", 204

    async def entity_action_resetpassworduser(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Reset a User's password. Peformed by the user."""
        row_version = data.row_version

        if entity_id != auth_user_id:
            self._logger.debug("Non-admin attempt to reset other user's password.")
            abort(400, "Cannot reset another user's password.")

        try:
            user = await self.get({"id": entity_id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        current_password = data.current_password.get_secret_value()

        if user is None:
            self.verify_password_hash(
                self._config.acp.login_dummy_hash, current_password
            )
            self._logger.debug("User for account lock not found.")
            abort(404, "User not found.")

        if not self.verify_password_hash(user.password_hash, current_password):
            self._logger.debug("Password incorrect.")
            abort(401)

        new_password = data.new_password.get_secret_value()

        if new_password != data.confirm_new_password.get_secret_value():
            self._logger.debug("Password and password confirmation do not match")
            abort(400, "Password confirmation mismatch.")

        if (
            self._config.acp.enforce_password_policy
            and not self.validate_password_policy(new_password)
        ):
            abort(400, "Password does not adhere to policy.")

        update_time = datetime.now(timezone.utc)
        svc: ICrudServiceWithRowVersion = self
        try:
            updated = await svc.update_with_row_version(
                {"id": user.id},
                expected_row_version=row_version,
                changes={
                    "password_hash": self.get_password_hash(new_password),
                    "password_changed_at": update_time,
                    "password_changed_by_user_id": auth_user_id,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        try:
            await self.bump_token_version({"id": updated.id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        try:
            await self._rsg.delete_many(self._rtoken_svc.table, {"user_id": updated.id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        return "", 204

    async def entity_action_unlock(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Unlock a user."""
        try:
            user = await self.get({"id": entity_id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if user is None:
            self._logger.warning("User for account unlock not found.")
            abort(404, "User not found.")

        svc: ICrudServiceWithRowVersion = self
        try:
            updated = await svc.update_with_row_version(
                {"id": user.id},
                expected_row_version=data.row_version,
                changes={
                    "locked_at": None,
                    "locked_by_user_id": None,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        try:
            await self.bump_token_version({"id": updated.id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        return "", 204

    async def entity_action_updateprofile(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Update a User's profile (Person)."""
        if entity_id != auth_user_id:
            self._logger.debug("Attempt to update other user's profile.")
            abort(400, "Cannot update another user's profile.")

        row_version = data.row_version
        changes = data.model_dump(exclude_none=True)
        changes.pop("row_version")

        try:
            user = await self.get({"id": entity_id}, columns=("person_id",))
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if user is None:
            self._logger.warning("User for profile update not found.")
            abort(404, "User not found.")

        svc: ICrudServiceWithRowVersion = self._person_svc
        try:
            updated = await svc.update_with_row_version(
                {"id": user.person_id},
                expected_row_version=row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204

    async def entity_action_updateroles(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Update a User's roles."""
        try:
            user = await self.get({"id": entity_id})
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if user is None:
            self._logger.warning("User not found.")
            abort(404, "User not found.")

        try:
            auth_role = await self._grole_svc.get(
                {
                    "namespace": self._resource.namespace,
                    "name": "authenticated",
                }
            )
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        if not auth_role:
            self._logger.debug("Authentication role not found.")
            abort(500)

        roles: list[uuid.UUID] = [auth_role.id]
        try:
            for role in data.roles:
                namespace, name = role.split(":")
                user_role = await self._grole_svc.get(
                    {
                        "namespace": namespace,
                        "name": name,
                    }
                )
                if user_role is None:
                    self._logger.debug(f"Role not found: {role}.")
                    abort(404, f"Role not found: {role}.")

                roles.append(user_role.id)

            await self._grole_mship_svc.clear_user_roles({"user_id": user.id})
            await self._grole_mship_svc.associate_roles_with_user(user.id, roles)
        except SQLAlchemyError as e:
            self._logger.error(e)
            abort(500)

        return "", 204

    async def entity_set_action_provision(
        self,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        if (
            self._config.acp.enforce_password_policy
            and not self.validate_password_policy(data.password.get_secret_value())
        ):
            abort(400, "Password does not adhere to policy.")

        person_data = {"first_name": data.first_name, "last_name": data.last_name}

        uow: IRelationalUnitOfWork
        async with self._rsg.unit_of_work() as uow:
            try:
                person = await uow.insert(self._person_svc.table, person_data)
            except SQLAlchemyError as e:
                self._logger.error(e)
                abort(500)

            user_data = {
                "username": data.username,
                "login_email": data.login_email,
                "person_id": person["id"],
                "password_hash": self.get_password_hash(
                    data.password.get_secret_value(),
                ),
            }

            try:
                user = await uow.insert(self.table, user_data)
            except SQLAlchemyError as e:
                self._logger.error(e)
                abort(500)

            try:
                auth_role = await uow.get_one(
                    self._grole_svc.table,
                    {
                        "namespace": self._resource.namespace,
                        "name": "authenticated",
                    },
                )
            except SQLAlchemyError as e:
                self._logger.error(e)
                abort(500)

            if auth_role is None:
                self._logger.debug("Authenticated role not found.")
                abort(500)

            try:
                await uow.insert(
                    self._grole_mship_svc.table,
                    {
                        "user_id": user["id"],
                        "global_role_id": auth_role["id"],
                    },
                )
            except SQLAlchemyError as e:
                self._logger.error(e)
                abort(500)
        return "", 204

    async def get_expanded(self, where: Mapping[str, Any]) -> UserDE | None:
        row = await self.get(where)
        if row is not None:

            row.person = await self._person_svc.get(
                {"id": row.person_id},
            )

            row.global_roles = [
                await self._grole_svc.get({"id": grm.global_role_id})
                for grm in await self._grole_mship_svc.get_role_memberships_by_user(
                    {"user_id": row.id}
                )
            ]

        return row

    def get_password_hash(self, pw: str) -> str:
        return generate_password_hash(pw)

    def verify_password_hash(self, pw_hash: str, pw: str) -> bool:
        return check_password_hash(pw_hash, pw)

    def validate_password_policy(self, pw: str) -> bool:
        if pw is None:
            return False
        regex_pattern = re.compile(self._config.acp.password_policy)
        return bool(regex_pattern.fullmatch(pw))
