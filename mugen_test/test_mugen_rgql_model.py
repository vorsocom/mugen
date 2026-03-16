"""Unit tests for RGQL metadata model helpers."""

import unittest

from mugen.core.utility.rgql.model import (
    EdmModel,
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    EntitySet,
    TypeRef,
)


class TestMugenRgqlModel(unittest.TestCase):
    """Covers model registration, lookup, and key configuration paths."""

    def test_typeref_element_for_collection_and_single_value(self) -> None:
        collection = TypeRef("NS.Customer", is_collection=True)
        single = TypeRef("NS.Customer", is_collection=False)

        self.assertEqual(collection.element(), TypeRef("NS.Customer", False))
        self.assertIs(single.element(), single)

    def test_edmtype_property_and_navigation_helpers(self) -> None:
        prop = EdmProperty(name="Name", type=TypeRef("Edm.String"), redact=True)
        nav = EdmNavigationProperty(name="Orders", target_type=TypeRef("NS.Order", True))
        edm_type = EdmType(
            name="NS.Customer",
            kind="entity",
            properties={"Name": prop},
            nav_properties={"Orders": nav},
        )

        self.assertIs(edm_type.find_property("Name"), prop)
        self.assertIsNone(edm_type.find_property("Missing"))
        self.assertIs(edm_type.find_nav_property("Orders"), nav)
        self.assertIsNone(edm_type.find_nav_property("Missing"))
        self.assertTrue(edm_type.property_redacted("Name"))
        self.assertFalse(edm_type.property_redacted("Missing"))

    def test_model_type_and_entity_set_registration_and_lookup(self) -> None:
        model = EdmModel()
        customer_type = EdmType(
            name="NS.Customer",
            kind="entity",
            properties={"Id": EdmProperty(name="Id", type=TypeRef("Edm.Guid"))},
        )
        customers = EntitySet(name="Customers", type=TypeRef("NS.Customer", True))

        model.add_type(customer_type)
        model.add_entity_set(customers)

        self.assertIs(model.get_type("NS.Customer"), customer_type)
        self.assertIs(model.try_get_type("NS.Customer"), customer_type)
        self.assertIsNone(model.try_get_type("NS.Missing"))
        self.assertIs(model.get_entity_set("Customers"), customers)
        self.assertIs(model.try_get_entity_set("Customers"), customers)
        self.assertIsNone(model.try_get_entity_set("Missing"))

    def test_model_lookup_errors_include_name(self) -> None:
        model = EdmModel()
        with self.assertRaisesRegex(KeyError, "Unknown EDM type"):
            model.get_type("NS.Missing")
        with self.assertRaisesRegex(KeyError, "Unknown entity set"):
            model.get_entity_set("Missing")

    def test_set_entity_keys_success_and_validation_errors(self) -> None:
        model = EdmModel()
        customer_type = EdmType(
            name="NS.Customer",
            kind="entity",
            properties={
                "Id": EdmProperty(name="Id", type=TypeRef("Edm.Guid")),
                "TenantId": EdmProperty(name="TenantId", type=TypeRef("Edm.Guid")),
            },
        )
        complex_type = EdmType(name="NS.Address", kind="complex")
        model.add_type(customer_type)
        model.add_type(complex_type)

        model.set_entity_keys("NS.Customer", "TenantId", "Id")
        self.assertEqual(customer_type.key_properties, ("TenantId", "Id"))

        with self.assertRaisesRegex(ValueError, "entity types"):
            model.set_entity_keys("NS.Address", "Id")

        with self.assertRaisesRegex(ValueError, "is not a property"):
            model.set_entity_keys("NS.Customer", "Missing")
