"""Unit tests for ACP nested navigation path planning."""

import unittest

from mugen.core.plugin.acp.utility.rgql.nav_filter_planner import plan_related_path
from mugen.core.utility.rgql.model import (
    EdmModel,
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)


class TestMugenAcpNavFilterPlanner(unittest.TestCase):
    """Covers nested to-one planning and validation branches."""

    def setUp(self) -> None:
        model = EdmModel()
        model.add_type(
            EdmType(
                name="NS.Department",
                kind="entity",
                properties={
                    "Id": EdmProperty("Id", TypeRef("Edm.Guid")),
                    "Name": EdmProperty("Name", TypeRef("Edm.String")),
                },
            )
        )
        model.add_type(
            EdmType(
                name="NS.Person",
                kind="entity",
                properties={
                    "Id": EdmProperty("Id", TypeRef("Edm.Guid")),
                    "FirstName": EdmProperty("FirstName", TypeRef("Edm.String")),
                    "Tags": EdmProperty(
                        "Tags",
                        TypeRef("Edm.String", is_collection=True),
                    ),
                    "Manager": EdmProperty("Manager", TypeRef("NS.Person")),
                },
                nav_properties={
                    "Department": EdmNavigationProperty(
                        name="Department",
                        target_type=TypeRef("NS.Department"),
                        source_fk="DepartmentId",
                    ),
                    "Children": EdmNavigationProperty(
                        name="Children",
                        target_type=TypeRef("NS.Person", is_collection=True),
                        target_fk="ParentId",
                    ),
                },
            )
        )
        model.add_type(
            EdmType(
                name="NS.User",
                kind="entity",
                properties={
                    "Id": EdmProperty("Id", TypeRef("Edm.Guid")),
                    "Name": EdmProperty("Name", TypeRef("Edm.String")),
                },
                nav_properties={
                    "Person": EdmNavigationProperty(
                        name="Person",
                        target_type=TypeRef("NS.Person"),
                        source_fk="PersonId",
                    ),
                    "BrokenNoFk": EdmNavigationProperty(
                        name="BrokenNoFk",
                        target_type=TypeRef("NS.Person"),
                    ),
                    "UnknownTarget": EdmNavigationProperty(
                        name="UnknownTarget",
                        target_type=TypeRef("NS.UnknownTarget"),
                        source_fk="UnknownTargetId",
                    ),
                },
            )
        )
        self.model = model
        self.table_map = {
            "NS.User": "admin_user",
            "NS.Person": "admin_person",
            "NS.Department": "admin_department",
        }

    def test_plan_related_path_success_cases(self) -> None:
        def resolver(type_name: str) -> str:
            return self.table_map[type_name]

        self.assertIsNone(
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Name",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )
        )

        one_hop = plan_related_path(
            base_type_name="NS.User",
            prop_path="Person/FirstName",
            model=self.model,
            table_resolver=resolver,
            max_nav_depth=4,
        )
        self.assertIsNotNone(one_hop)
        hops, terminal = one_hop
        self.assertEqual(len(hops), 1)
        self.assertEqual(hops[0].source_table, "admin_user")
        self.assertEqual(hops[0].target_table, "admin_person")
        self.assertEqual(terminal, "first_name")

        two_hop = plan_related_path(
            base_type_name="NS.User",
            prop_path="Person/Department/Name",
            model=self.model,
            table_resolver=resolver,
            max_nav_depth=4,
        )
        self.assertIsNotNone(two_hop)
        hops, terminal = two_hop
        self.assertEqual(len(hops), 2)
        self.assertEqual(hops[0].target_table, "admin_person")
        self.assertEqual(hops[1].target_table, "admin_department")
        self.assertEqual(terminal, "name")

    def test_plan_related_path_validation_errors(self) -> None:
        def resolver(type_name: str) -> str:
            return self.table_map[type_name]

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Person",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Person/Children/FirstName",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Person/Department/Name",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=1,
            )

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Person/Missing",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

    def test_plan_related_path_additional_validation_branches(self) -> None:
        def resolver(type_name: str) -> str:
            return self.table_map[type_name]

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.Missing",
                prop_path="Name",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.Person",
                prop_path="Children",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="BrokenNoFk/FirstName",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

        def resolver_with_unknown(type_name: str) -> str:
            if type_name == "NS.UnknownTarget":
                return "admin_unknown_target"
            return self.table_map[type_name]

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="UnknownTarget/FirstName",
                model=self.model,
                table_resolver=resolver_with_unknown,
                max_nav_depth=4,
            )

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Person/Department",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Person/FirstName/Extra",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

        self.assertIsNone(
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Name/Extra",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )
        )

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Person/Tags",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Person/Manager",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Person/NS.Person/FirstName",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )

        self.assertIsNone(
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Unknown/Path",
                model=self.model,
                table_resolver=resolver,
                max_nav_depth=4,
            )
        )

    def test_plan_related_path_table_resolver_failures(self) -> None:
        def raising_resolver(_type_name: str) -> str:
            raise RuntimeError("resolver blew up")

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Person/FirstName",
                model=self.model,
                table_resolver=raising_resolver,
                max_nav_depth=4,
            )

        def missing_table_resolver(type_name: str) -> str:
            if type_name == "NS.Person":
                return ""
            return self.table_map[type_name]

        with self.assertRaises(ValueError):
            plan_related_path(
                base_type_name="NS.User",
                prop_path="Person/FirstName",
                model=self.model,
                table_resolver=missing_table_resolver,
                max_nav_depth=4,
            )


if __name__ == "__main__":
    unittest.main()
