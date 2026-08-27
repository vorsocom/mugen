"""Pure migration-planner checks kept outside the coverage-instrumented process."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class TestNormalizedBillingMigrationPlans(unittest.TestCase):
    """Verify resumable migration preflight decisions without a live database."""

    def test_meter_and_entitlement_planners(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script = textwrap.dedent("""
            from datetime import datetime, timezone
            import importlib
            import uuid

            meters_mod = importlib.import_module(
                "migrations.versions.4a8c1e6f2b9d_globalize_billing_meters"
            )
            definitions_mod = importlib.import_module(
                "migrations.versions.5b9d2f7a3c1e_normalize_billing_definitions"
            )

            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            first_id = uuid.uuid4()
            second_id = uuid.uuid4()
            tenant_one = uuid.uuid4()
            tenant_two = uuid.uuid4()
            compatible = [
                {
                    "id": first_id,
                    "tenant_id": tenant_one,
                    "created_at": now,
                    "updated_at": now,
                    "row_version": 2,
                    "code": " Shared.Meter ",
                    "unit": " Minute ",
                    "aggregation_mode": " SUM ",
                    "description": "canonical",
                    "is_active": False,
                    "attributes": None,
                },
                {
                    "id": second_id,
                    "tenant_id": tenant_two,
                    "created_at": now.replace(day=2),
                    "updated_at": now,
                    "row_version": 1,
                    "code": "shared.meter",
                    "unit": "minute",
                    "aggregation_mode": "sum",
                    "description": "duplicate",
                    "is_active": True,
                    "attributes": {},
                },
            ]
            canonical, mapping = meters_mod._meter_plan(compatible)
            assert len(canonical) == 1
            assert canonical[0]["id"] == first_id
            assert canonical[0]["code"] == "shared.meter"
            assert canonical[0]["is_active"] is True
            assert mapping == {first_id: first_id, second_id: first_id}

            invalid_meter_sets = [
                [{**compatible[0], "attributes": {"tenant_key": "review"}}],
                [compatible[0], {**compatible[1], "unit": "task"}],
                [{**compatible[0], "code": " "}],
                [{**compatible[0], "unit": "second"}],
                [{**compatible[0], "aggregation_mode": "average"}],
            ]
            for rows in invalid_meter_sets:
                try:
                    meters_mod._meter_plan(rows)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("unsafe meter inventory was accepted")

            meters_mod._validate_price_meter_contracts(
                [
                    {
                        "id": uuid.uuid4(),
                        "price_type": "metered",
                        "meter_code": "shared.meter",
                        "usage_unit": "minute",
                    },
                    {
                        "id": uuid.uuid4(),
                        "price_type": "recurring",
                        "meter_code": None,
                        "usage_unit": None,
                    },
                ],
                canonical,
            )
            invalid_prices = [
                {
                    "price_type": "metered",
                    "meter_code": "absent",
                    "usage_unit": "unit",
                },
                {
                    "price_type": "metered",
                    "meter_code": "shared.meter",
                    "usage_unit": "task",
                },
                {
                    "price_type": "recurring",
                    "meter_code": "shared.meter",
                    "usage_unit": "minute",
                },
            ]
            for price in invalid_prices:
                price["id"] = uuid.uuid4()
                try:
                    meters_mod._validate_price_meter_contracts([price], canonical)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("invalid Price meter contract was accepted")

            minute_id = uuid.uuid4()
            task_id = uuid.uuid4()
            meter_rows = [
                {
                    "id": minute_id,
                    "code": "valet.customer-inbox.minutes",
                    "is_active": True,
                },
                {
                    "id": task_id,
                    "code": "valet.customer-inbox.tasks",
                    "is_active": True,
                },
            ]
            price_id = uuid.uuid4()
            price = {
                "id": price_id,
                "price_type": "recurring",
                "interval_unit": "month",
                "interval_count": 1,
                "attributes": {
                    "included_usage": {"cim": 150, "cct": 2},
                    "label": "lite",
                },
            }
            rules = definitions_mod._entitlement_plan([price], meter_rows)
            assert len(rules) == 2
            assert {row["included_quantity"] for row in rules} == {2, 150}
            assert all(
                row["remaining_attributes"] == {"label": "lite"}
                for row in rules
            )
            assert definitions_mod._entitlement_plan([price], meter_rows) == rules

            invalid_entitlements = [
                {**price, "attributes": {"included_usage": []}},
                {**price, "price_type": "one_time"},
                {**price, "deleted_at": now},
                {**price, "attributes": {"included_usage": {"absent": 1}}},
                {**price, "attributes": {"included_usage": {"cim": True}}},
                {**price, "attributes": {"included_usage": {"cim": 1.5}}},
                {**price, "attributes": {"included_usage": {"cim": -1}}},
                {**price, "attributes": {"included_usage": {"cim": 1, "minutes": 1}}},
            ]
            for invalid in invalid_entitlements:
                try:
                    definitions_mod._entitlement_plan([invalid], meter_rows)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("invalid included_usage metadata was accepted")
            """)
        environment = os.environ.copy()
        environment["MUGEN_ALEMBIC_SCHEMA"] = "mugen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
