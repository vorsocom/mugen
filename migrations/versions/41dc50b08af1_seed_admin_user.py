"""Seed admin user.

Revision ID: 41dc50b08af1
Revises: 2e72f21209c3
Create Date: 2025-12-22 04:28:21.597672

"""

import logging
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op, context
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import NoSuchTableError, SQLAlchemyError
from werkzeug.security import check_password_hash

# Set up a logger for this specific script
log = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "41dc50b08af1"
down_revision: Union[str, Sequence[str], None] = "2e72f21209c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCHEMA = resolve_runtime_schema()


# pylint: disable=no-member
def upgrade() -> None:
    """Upgrade schema."""
    if context.is_offline_mode():
        log.warning("Skipping admin user seeding in offline mode.")
        return

    mugen_cfg = context.config.attributes.get("mugen_cfg")

    if not mugen_cfg:
        raise RuntimeError(
            "mugen_cfg was not provided to Alembic env; cannot seed ACP."
        )

    acp_cfg = mugen_cfg.get("acp", {})

    # Determine if ACP seeding is enabled.
    # Admin user seeding cannot run if ACP seeding was not run.
    seed_acp = acp_cfg.get("seed_acp", False)

    if not isinstance(seed_acp, bool):
        raise TypeError("admin.seed_acp must be a boolean (true/false).")

    if not seed_acp:
        log.warning("ACP seeding skipped by config.")
        return

    # ACP seeding was run. Do admin user seeding.
    from mugen.core.plugin.acp.utility.identity import (
        resolve_acp_admin_namespace,
    )

    admin_namespace = resolve_acp_admin_namespace(mugen_cfg, enabled_only=True)

    admin_username = acp_cfg.get("admin_username", None)
    if admin_username is None:
        raise ValueError("admin.admin_username must be in config.")

    admin_login_email = acp_cfg.get("admin_login_email", None)
    if admin_login_email is None:
        raise ValueError("admin.admin_login_email must be in config.")

    conn = op.get_bind()
    md = sa.MetaData(schema=_SCHEMA)

    try:
        ptable = sa.Table("admin_person", md, autoload_with=conn)
        utable = sa.Table("admin_user", md, autoload_with=conn)
        grtable = sa.Table("admin_global_role", md, autoload_with=conn)
        grmtable = sa.Table("admin_global_role_membership", md, autoload_with=conn)
    except NoSuchTableError as exc:
        raise RuntimeError(
            "Table(s) required for admin user seeding do(es) not exist."
        ) from exc

    # Require columns.
    # User table.
    missing = [
        c
        for c in ("id", "username", "login_email", "password_hash", "person_id")
        if c not in utable.c
    ]
    if missing:
        raise RuntimeError(
            f"Table '{utable.fullname}' is missing required columns: {missing}. "
            f"Available columns: {list(utable.c.keys())}."
        )
    # Person table.
    missing = [c for c in ("id", "first_name", "last_name") if c not in ptable.c]
    if missing:
        raise RuntimeError(
            f"Table '{ptable.fullname}' is missing required columns: {missing}. "
            f"Available columns: {list(ptable.c.keys())}."
        )
    # GlobalRoleMembership table.
    missing = [c for c in ("global_role_id", "user_id") if c not in grmtable.c]
    if missing:
        raise RuntimeError(
            f"Table '{grmtable.fullname}' is missing required columns: {missing}. "
            f"Available columns: {list(grmtable.c.keys())}."
        )

    # Check admin user is not already created.
    checku_stmt = sa.select(utable).where(utable.c.username == admin_username)

    try:
        checku = conn.execute(checku_stmt).first()
    except SQLAlchemyError as exc:
        raise RuntimeError("Could not execute check user statement.") from exc

    person_id = uuid.UUID("ab53b9a3-8cdc-4a2e-bbf2-352cea11edaa")

    if checku is None:
        admin_password = acp_cfg.get("admin_password", None)
        if admin_password is None:
            raise ValueError("admin.admin_password must be in config.")

        admin_password_hash = acp_cfg.get("admin_password_hash", None)
        if admin_password_hash is None:
            raise ValueError("admin.admin_password_hash must be in config.")

        if not check_password_hash(admin_password_hash, admin_password):
            raise ValueError("Password hash does not match plaintext password.")

        # Create Person.
        checkp_stmt = sa.select(ptable).where(ptable.c.id == person_id)

        try:
            checkp = conn.execute(checkp_stmt).first()
        except SQLAlchemyError as exc:
            raise RuntimeError("Could not execute check person statement.") from exc

        if not checkp:
            pstmt = pg_insert(ptable).values(
                {
                    "id": person_id,
                    "first_name": "System",
                    "last_name": "Administrator",
                }
            )

            try:
                conn.execute(pstmt)
                log.info("Seeded Person: System Administrator.")
            except SQLAlchemyError as exc:
                raise RuntimeError(
                    "Could not execute insert person statement."
                ) from exc

        # Create User.
        ustmt = pg_insert(utable).values(
            {
                "username": admin_username,
                "login_email": admin_login_email,
                "password_hash": admin_password_hash,
                "person_id": person_id,
            }
        )
        ustmt = ustmt.returning(utable.c.id)

        try:
            ustmt_res = conn.execute(ustmt)
            log.info("Seeded User: %s.", admin_username)
        except SQLAlchemyError as exc:
            raise RuntimeError("Could not execute insert user statement.") from exc

        user_id = ustmt_res.scalar_one()

        # Add GlobalRoles to User.
        rstmt = sa.select(grtable.c.id, grtable.c.name).where(
            sa.and_(
                grtable.c.namespace == admin_namespace,
                grtable.c.name.in_(("authenticated", "administrator")),
            )
        )

        try:
            rstmt_res = conn.execute(rstmt)
        except SQLAlchemyError as exc:
            raise RuntimeError("Could not execute fetch roles statement.") from exc

        roles = [
            dict(row._mapping)  # pylint: disable=protected-access
            for row in rstmt_res.all()
        ]
        if not roles:
            raise RuntimeError("Admin roles not fetched.")

        if len(roles) != 2:
            raise RuntimeError("Exactly two admin roles should have been fetched.")

        if not any(r["name"] == "authenticated" for r in roles):
            raise RuntimeError("Role not fetched: authenticated.")

        if not any(r["name"] == "administrator" for r in roles):
            raise RuntimeError("Role not fetched: administrator.")

        rmship_stmt = pg_insert(grmtable).values(
            [{"global_role_id": r["id"], "user_id": user_id} for r in roles]
        )
        rmship_stmt = rmship_stmt.on_conflict_do_nothing(
            index_elements=("global_role_id", "user_id")
        )

        try:
            conn.execute(rmship_stmt)
            log.info("Assigned roles to User (admin): authenticated, administrator.")
        except SQLAlchemyError as exc:
            raise RuntimeError(
                "Could not execute insert role memberships statement."
            ) from exc
    else:
        user_mapping = dict(checku._mapping)  # pylint: disable=protected-access

        # Verify username.
        if user_mapping["username"] != admin_username:
            raise ValueError("Admin username in DB does not match configured value.")

        # Verify email.
        if user_mapping["login_email"] != admin_login_email:
            raise ValueError("Admin login email in DB does not match configured value.")

        # Verify person id.
        if uuid.UUID(str(user_mapping["person_id"])) != person_id:
            raise ValueError("Admin person_id in DB does not match configured value.")

        # Verify person exists.
        checkp_stmt = sa.select(sa.literal(True)).where(ptable.c.id == person_id)
        try:
            checkp = conn.execute(checkp_stmt)
        except SQLAlchemyError as exc:
            raise RuntimeError("Could not execute fetch person statement.") from exc

        if not checkp.scalar_one_or_none():
            raise RuntimeError("The referenced Person row does not exist.")

        # Verify global roles:
        # Fetch roles.
        rstmt = sa.select(grtable.c.id, grtable.c.name).where(
            sa.and_(
                grtable.c.namespace == admin_namespace,
                grtable.c.name.in_(("authenticated", "administrator")),
            )
        )

        try:
            rstmt_res = conn.execute(rstmt)
        except SQLAlchemyError as exc:
            raise RuntimeError("Could not execute fetch roles statement.") from exc

        admin_roles = [
            dict(r._mapping)  # pylint: disable=protected-access
            for r in rstmt_res.all()
        ]

        if not admin_roles:
            raise RuntimeError("Admin roles not fetched.")

        if len(admin_roles) != 2:
            raise RuntimeError("Exactly two admin roles should have been fetched.")

        if not any(r["name"] == "authenticated" for r in admin_roles):
            raise RuntimeError("Role not fetched: authenticated.")

        if not any(r["name"] == "administrator" for r in admin_roles):
            raise RuntimeError("Role not fetched: administrator.")

        # Fetch role memberships.
        rmship_stmt = sa.select(grmtable.c.global_role_id).where(
            grmtable.c.user_id == user_mapping["id"],
        )

        try:
            rmship_stmt_res = conn.execute(rmship_stmt)
        except SQLAlchemyError as exc:
            raise RuntimeError(
                "Could not execute fetch role memberships statement."
            ) from exc

        role_mships = [r[0] for r in rmship_stmt_res.all()]

        if not role_mships:
            raise RuntimeError("Admin user has no role memberships.")

        # Do verification.
        for role in admin_roles:
            if role["id"] not in role_mships:
                raise RuntimeError(f"Admin user missing role: {role['name']}")


def downgrade() -> None:
    """Remove seeded admin user data."""
    if context.is_offline_mode():
        log.warning("Skipping admin user unseeding in offline mode.")
        return

    conn = op.get_bind()
    md = sa.MetaData(schema=_SCHEMA)

    try:
        ptable = sa.Table("admin_person", md, autoload_with=conn)
        utable = sa.Table("admin_user", md, autoload_with=conn)
        grmtable = sa.Table("admin_global_role_membership", md, autoload_with=conn)
    except NoSuchTableError as exc:
        raise RuntimeError(
            "Table(s) required for admin user unseeding do(es) not exist."
        ) from exc

    person_id = uuid.UUID("ab53b9a3-8cdc-4a2e-bbf2-352cea11edaa")

    checku_stmt = sa.select(utable).where(utable.c.person_id == person_id)
    try:
        user_row = conn.execute(checku_stmt).first()
    except SQLAlchemyError as exc:
        raise RuntimeError("Could not execute check user statement.") from exc

    if user_row is None:
        return

    user_mapping = dict(user_row._mapping)  # pylint: disable=protected-access

    rmship_stmt = sa.delete(grmtable).where(
        grmtable.c.user_id == user_mapping["id"],
    )
    try:
        conn.execute(rmship_stmt)
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Could not execute delete role memberships statement."
        ) from exc

    delete_user_stmt = sa.delete(utable).where(utable.c.id == user_mapping["id"])
    try:
        conn.execute(delete_user_stmt)
    except SQLAlchemyError as exc:
        raise RuntimeError("Could not execute delete user statement.") from exc

    person_ref_stmt = sa.select(sa.literal(True)).where(utable.c.person_id == person_id)
    try:
        has_refs = conn.execute(person_ref_stmt).first() is not None
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Could not execute person reference check statement."
        ) from exc

    if not has_refs:
        delete_person_stmt = sa.delete(ptable).where(ptable.c.id == person_id)
        try:
            conn.execute(delete_person_stmt)
        except SQLAlchemyError as exc:
            raise RuntimeError("Could not execute delete person statement.") from exc
