"""Unit tests for RGQL expand helper utilities and validation branches."""

from dataclasses import dataclass
import unittest
from unittest.mock import patch

from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderBy,
    RelatedPathHop,
    RelatedScalarFilter,
    RelatedTextFilter,
    ScalarFilterOp,
    TextFilterOp,
)
from mugen.core.utility.rgql.model import (
    EdmModel,
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)
from mugen.core.utility.rgql.url_parser import ExpandItem
from mugen.core.gateway.storage.rdbms.rgql_adapter.rgql_expand import (
    ExpansionContext,
    _augment_query_columns_for_nested_expands,
    apply_to_filter_groups,
    apply_to_where,
    expand_navs_bulk,
    expand_navs_recursive,
    normalise_expand_levels,
)
from mugen.core.gateway.storage.rdbms.rgql_adapter.error import RGQLExpandError
from mugen.core.gateway.storage.rdbms.rgql_adapter.rgql_to_relational import RGQLToRelationalAdapter


@dataclass
class _Entity:
    id: int | None = 1
    owner_id: int | None = None


@dataclass
class _Child:
    id: int | None = None
    parent_id: int | None = None
    owner_id: int | None = None
    name: str | None = None
    secret: str | None = None


class _FixedAdapter:
    def __init__(self, result):
        self._result = result

    def build_relational_query(self, _opts, **_kwargs):
        return self._result


class _FakeNavService:
    def __init__(self, *, list_result=None, get_result=None, partition_result=None):
        self._list_result = list_result if list_result is not None else []
        self._get_result = get_result
        self._partition_result = partition_result if partition_result is not None else []
        self.last_list_kwargs = None
        self.last_get_kwargs = None
        self.last_partition_kwargs = None

    async def list(self, **kwargs):
        self.last_list_kwargs = kwargs
        return list(self._list_result)

    async def get(self, where, columns=None):
        self.last_get_kwargs = {"where": where, "columns": columns}
        return self._get_result

    async def list_partitioned_by_fk(
        self,
        *,
        fk_field,
        fk_values,
        columns,
        filter_groups,
        order_by,
        per_fk_limit,
        per_fk_offset,
    ):
        self.last_partition_kwargs = {
            "fk_field": fk_field,
            "fk_values": fk_values,
            "columns": columns,
            "filter_groups": filter_groups,
            "order_by": order_by,
            "per_fk_limit": per_fk_limit,
            "per_fk_offset": per_fk_offset,
        }
        return list(self._partition_result)


class TestMugenRgqlExpandHelpers(unittest.TestCase):
    """Covers synchronous helper functions in rgql_expand."""

    @staticmethod
    def _make_edm_type() -> EdmType:
        return EdmType(
            name="NS.Parent",
            kind="entity",
            nav_properties={
                "Owner": EdmNavigationProperty(
                    name="Owner",
                    target_type=TypeRef("NS.User", is_collection=False),
                    source_fk="OwnerId",
                ),
                "Children": EdmNavigationProperty(
                    name="Children",
                    target_type=TypeRef("NS.User", is_collection=True),
                    target_fk="ParentId",
                ),
            },
        )

    def test_apply_to_filter_groups_and_where(self) -> None:
        self.assertEqual(apply_to_filter_groups(None), [])

        created = apply_to_filter_groups(None, where={"tenant_id": "t1"})
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].where, {"tenant_id": "t1"})

        merged = apply_to_filter_groups(
            [FilterGroup(where={"status": "open"})],
            where={"tenant_id": "t1"},
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].where, {"status": "open", "tenant_id": "t1"})

        # Cover merge path where `where` is absent but scalar/text filters are present.
        merged_without_where = apply_to_filter_groups(
            [FilterGroup(where={"status": "open"})],
            scalars=[],
            texts=[],
        )
        self.assertEqual(len(merged_without_where), 1)
        self.assertEqual(merged_without_where[0].where, {"status": "open"})

        # Cover branch where where is absent but loop still runs.
        merged_with_scalar_only = apply_to_filter_groups(
            [FilterGroup(where={"status": "open"})],
            scalars=[],
            texts=[object()],
        )
        self.assertEqual(len(merged_with_scalar_only), 1)
        self.assertEqual(merged_with_scalar_only[0].where, {"status": "open"})

        related_group = FilterGroup(
            where={"status": "open"},
            related_text_filters=[
                RelatedTextFilter(
                    path_hops=[
                        RelatedPathHop(
                            source_table="admin_user",
                            source_field="person_id",
                            target_table="admin_person",
                            target_field="id",
                        )
                    ],
                    field="first_name",
                    op=TextFilterOp.CONTAINS,
                    value="a",
                )
            ],
            related_scalar_filters=[
                RelatedScalarFilter(
                    path_hops=[
                        RelatedPathHop(
                            source_table="admin_user",
                            source_field="person_id",
                            target_table="admin_person",
                            target_field="id",
                        )
                    ],
                    field="first_name",
                    op=ScalarFilterOp.EQ,
                    value="Ada",
                )
            ],
        )
        merged_related = apply_to_filter_groups(
            [related_group],
            where={"tenant_id": "t1"},
        )
        self.assertEqual(len(merged_related), 1)
        self.assertEqual(len(merged_related[0].related_text_filters), 1)
        self.assertEqual(len(merged_related[0].related_scalar_filters), 1)

        self.assertEqual(apply_to_where({"id": 1}, {}), {"id": 1})
        self.assertEqual(
            apply_to_where({"id": 1}, {"tenant_id": "t1"}),
            {"id": 1, "tenant_id": "t1"},
        )

    def test_normalise_expand_levels(self) -> None:
        self.assertEqual(normalise_expand_levels(None, 3), 3)
        self.assertEqual(normalise_expand_levels("max", 4), 4)
        self.assertEqual(normalise_expand_levels("MAX", 4), 4)
        self.assertEqual(normalise_expand_levels(99, 5), 5)
        self.assertEqual(normalise_expand_levels(-1, 5), 0)
        with self.assertRaises(ValueError):
            normalise_expand_levels("unsupported", 3)

    def test_augment_query_columns_for_nested_expands(self) -> None:
        edm_type = self._make_edm_type()

        self.assertIsNone(
            _augment_query_columns_for_nested_expands(
                edm_type=edm_type,
                expand_items=[ExpandItem(path="Owner")],
                query_columns=None,
            )
        )
        self.assertEqual(
            _augment_query_columns_for_nested_expands(
                edm_type=edm_type,
                expand_items=[],
                query_columns=["name"],
            ),
            ["name"],
        )

        cols = _augment_query_columns_for_nested_expands(
            edm_type=edm_type,
            expand_items=[
                ExpandItem(path="Owner"),
                ExpandItem(path="Children"),
                ExpandItem(path="Unknown"),
            ],
            query_columns=["name"],
        )
        self.assertIsNotNone(cols)
        self.assertIn("name", cols)
        self.assertIn("id", cols)
        self.assertIn("owner_id", cols)

        cols_already_present = _augment_query_columns_for_nested_expands(
            edm_type=edm_type,
            expand_items=[ExpandItem(path="Owner")],
            query_columns=["id", "owner_id"],
        )
        self.assertEqual(cols_already_present, ["id", "owner_id"])


class TestMugenRgqlExpandAsync(unittest.IsolatedAsyncioTestCase):
    """Covers async permission caching and validation-only expand branches."""

    @staticmethod
    def _make_model() -> EdmModel:
        model = EdmModel()
        parent = EdmType(
            name="NS.Parent",
            kind="entity",
            nav_properties={
                "Children": EdmNavigationProperty(
                    name="Children",
                    target_type=TypeRef("NS.Child", is_collection=True),
                    target_fk="ParentId",
                ),
                "Owner": EdmNavigationProperty(
                    name="Owner",
                    target_type=TypeRef("NS.Child", is_collection=False),
                    source_fk="OwnerId",
                ),
            },
        )
        child = EdmType(
            name="NS.Child",
            kind="entity",
            properties={
                "Id": EdmProperty(name="Id", type=TypeRef("Edm.Int64")),
                "ParentId": EdmProperty(name="ParentId", type=TypeRef("Edm.Int64")),
                "OwnerId": EdmProperty(name="OwnerId", type=TypeRef("Edm.Int64")),
                "Name": EdmProperty(name="Name", type=TypeRef("Edm.String")),
                "Secret": EdmProperty(
                    name="Secret",
                    type=TypeRef("Edm.String"),
                    redact=True,
                ),
            },
            nav_properties={
                "Owner": EdmNavigationProperty(
                    name="Owner",
                    target_type=TypeRef("NS.Child", is_collection=False),
                    source_fk="OwnerId",
                ),
            },
        )
        model.add_type(parent)
        model.add_type(child)
        return model

    @classmethod
    def _make_context(
        cls,
        *,
        adapter=None,
        serialization_provider=None,
        service_resolver=None,
        path_permission_provider=None,
        max_depth=5,
        allow_expand_wildcard=True,
        default_top=10,
        max_top=10,
        max_skip=10,
        max_select=10,
        max_orderby=10,
        max_expand_paths=10,
        max_filter_terms=10,
        default_where_provider=None,
    ) -> ExpansionContext:
        if adapter is None:
            adapter = _FixedAdapter(([], [], None, None))

        async def _allow(_edm_type, _path):
            return True

        if path_permission_provider is None:
            path_permission_provider = _allow

        if service_resolver is None:
            service_resolver = lambda _type_name: object()

        if default_where_provider is None:
            default_where_provider = lambda _type_name: {}

        if serialization_provider is None:
            serialization_provider = (
                lambda entity, _edm_type, _cols, _paths: {"Id": getattr(entity, "id", None)}
            )

        return ExpansionContext(
            model=cls._make_model(),
            adapter=adapter,
            serialization_provider=serialization_provider,
            service_resolver=service_resolver,
            path_permission_provider=path_permission_provider,
            max_depth=max_depth,
            allow_expand_wildcard=allow_expand_wildcard,
            default_top=default_top,
            max_top=max_top,
            max_skip=max_skip,
            max_select=max_select,
            max_orderby=max_orderby,
            max_expand_paths=max_expand_paths,
            max_filter_terms=max_filter_terms,
            default_where_provider=default_where_provider,
        )

    async def test_permission_cache(self) -> None:
        calls = {"count": 0}

        async def provider(_edm_type, _path):
            calls["count"] += 1
            return True

        ctx = self._make_context(path_permission_provider=provider)
        edm_type = ctx.model.get_type("NS.Parent")

        self.assertTrue(await ctx.permitted(edm_type, "Children"))
        self.assertTrue(await ctx.permitted(edm_type, "Children"))
        self.assertEqual(calls["count"], 1)

    async def test_expand_navs_recursive_early_branches(self) -> None:
        ctx = self._make_context()

        await expand_navs_recursive(
            root_entity=_Entity(id=1),
            ctx=ctx,
            expand_item=None,
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )
        await expand_navs_recursive(
            root_entity=_Entity(id=1),
            ctx=ctx,
            expand_item=ExpandItem(path="/"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

        with self.assertRaises(RGQLExpandError):
            await expand_navs_recursive(
                root_entity=_Entity(id=1),
                ctx=ctx,
                expand_item=ExpandItem(path="Children/Nested"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        await expand_navs_recursive(
            root_entity=_Entity(id=1),
            ctx=ctx,
            expand_item=ExpandItem(path="UnknownNav"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

        ctx_no_service = self._make_context(service_resolver=lambda _type_name: None)
        await expand_navs_recursive(
            root_entity=_Entity(id=1),
            ctx=ctx_no_service,
            expand_item=ExpandItem(path="Children"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

    async def test_expand_navs_recursive_validation_errors(self) -> None:
        # max orderby
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [OrderBy("x"), OrderBy("y")], 1, 0)),
            max_orderby=1,
        )
        with self.assertRaises(RGQLExpandError):
            await expand_navs_recursive(
                root_entity=_Entity(id=1),
                ctx=ctx,
                expand_item=ExpandItem(path="Children"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

    async def test_expand_navs_recursive_maps_adapter_value_error(self) -> None:
        class _FailingAdapter:
            def build_relational_query(self, _opts, **_kwargs):
                raise ValueError("bad nested filter")

        ctx = self._make_context(adapter=_FailingAdapter())
        with self.assertRaises(RGQLExpandError) as ex:
            await expand_navs_recursive(
                root_entity=_Entity(id=1),
                ctx=ctx,
                expand_item=ExpandItem(path="Children"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )
        self.assertEqual(ex.exception.args, (400, "bad nested filter"))

    async def test_expand_navs_recursive_collection_materializes_children(self) -> None:
        child_service = _FakeNavService(
            list_result=[
                _Child(id=101, parent_id=10, owner_id=7, name="Alpha", secret="x"),
                _Child(id=102, parent_id=10, owner_id=8, name="Beta", secret="y"),
            ]
        )
        services = {"NS.Child": child_service}
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], None, None)),
            service_resolver=lambda type_name: services.get(type_name),
            default_where_provider=lambda _type_name: {"is_deleted": False},
        )

        parent = _Entity(id=10)
        await expand_navs_recursive(
            root_entity=parent,
            ctx=ctx,
            expand_item=ExpandItem(
                path="Children",
                select=["Name"],
                expand=[ExpandItem(path="Owner")],
            ),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

        self.assertEqual(parent.children, [{"Name": "Alpha"}, {"Name": "Beta"}])  # type: ignore[attr-defined]
        self.assertIsNotNone(child_service.last_list_kwargs)
        self.assertEqual(child_service.last_list_kwargs["limit"], 10)
        self.assertEqual(child_service.last_list_kwargs["offset"], 0)
        self.assertIn("name", child_service.last_list_kwargs["columns"])
        self.assertIn("id", child_service.last_list_kwargs["columns"])
        self.assertIn("owner_id", child_service.last_list_kwargs["columns"])
        self.assertEqual(
            child_service.last_list_kwargs["filter_groups"][0].where,
            {"is_deleted": False, "parent_id": 10},
        )

    async def test_expand_navs_recursive_single_materializes_child(self) -> None:
        child_service = _FakeNavService(
            get_result=_Child(id=5, owner_id=99, name="Boss", secret="hidden")
        )
        services = {"NS.Child": child_service}
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], None, None)),
            service_resolver=lambda type_name: services.get(type_name),
            default_where_provider=lambda _type_name: {"is_deleted": False},
        )

        parent = _Entity(id=1, owner_id=5)
        await expand_navs_recursive(
            root_entity=parent,
            ctx=ctx,
            expand_item=ExpandItem(
                path="Owner",
                select=["Name"],
                expand=[ExpandItem(path="Owner")],
            ),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

        self.assertEqual(parent.owner, {"Name": "Boss"})  # type: ignore[attr-defined]
        self.assertEqual(
            child_service.last_get_kwargs["where"],
            {"id": 5, "is_deleted": False},
        )
        self.assertIn("name", child_service.last_get_kwargs["columns"])
        self.assertIn("id", child_service.last_get_kwargs["columns"])
        self.assertIn("owner_id", child_service.last_get_kwargs["columns"])

    async def test_expand_navs_recursive_single_missing_target_or_child(self) -> None:
        child_service = _FakeNavService(get_result=None)
        services = {"NS.Child": child_service}
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], None, None)),
            service_resolver=lambda type_name: services.get(type_name),
        )

        missing_fk_parent = _Entity(id=1, owner_id=None)
        await expand_navs_recursive(
            root_entity=missing_fk_parent,
            ctx=ctx,
            expand_item=ExpandItem(path="Owner"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )
        self.assertIsNone(child_service.last_get_kwargs)

        no_child_parent = _Entity(id=1, owner_id=55)
        await expand_navs_recursive(
            root_entity=no_child_parent,
            ctx=ctx,
            expand_item=ExpandItem(path="Owner"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )
        self.assertEqual(child_service.last_get_kwargs["where"], {"id": 55})
        self.assertFalse(hasattr(no_child_parent, "owner"))

        # top exceeds max
        ctx = self._make_context(adapter=_FixedAdapter(([], [], 11, 0)), max_top=10)
        with self.assertRaises(RGQLExpandError):
            await expand_navs_recursive(
                root_entity=_Entity(id=1),
                ctx=ctx,
                expand_item=ExpandItem(path="Children"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        # filter terms exceeded for single-valued path.
        child_service = _FakeNavService(get_result=_Child(id=5, name="Boss"))
        services = {"NS.Child": child_service}
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
            max_filter_terms=1,
            default_where_provider=lambda _type_name: {"is_deleted": False},
        )
        with self.assertRaises(RGQLExpandError):
            await expand_navs_recursive(
                root_entity=_Entity(id=1, owner_id=5),
                ctx=ctx,
                expand_item=ExpandItem(path="Owner"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        # skip exceeds max
        ctx = self._make_context(adapter=_FixedAdapter(([], [], 1, 11)), max_skip=10)
        with self.assertRaises(RGQLExpandError):
            await expand_navs_recursive(
                root_entity=_Entity(id=1),
                ctx=ctx,
                expand_item=ExpandItem(path="Children"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        # wildcard blocked
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            allow_expand_wildcard=False,
        )
        with self.assertRaises(RGQLExpandError):
            await expand_navs_recursive(
                root_entity=_Entity(id=1),
                ctx=ctx,
                expand_item=ExpandItem(path="Children", expand=[ExpandItem(path="*")]),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        # max expand paths exceeded
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            max_expand_paths=1,
        )
        with self.assertRaises(RGQLExpandError):
            await expand_navs_recursive(
                root_entity=_Entity(id=1),
                ctx=ctx,
                expand_item=ExpandItem(
                    path="Children",
                    expand=[ExpandItem(path="A"), ExpandItem(path="B")],
                ),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        # max select exceeded
        ctx = self._make_context(adapter=_FixedAdapter(([], [], 1, 0)), max_select=1)
        with self.assertRaises(RGQLExpandError):
            await expand_navs_recursive(
                root_entity=_Entity(id=1),
                ctx=ctx,
                expand_item=ExpandItem(path="Children", select=["Id", "Name"]),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        # filter terms exceeded for collection path
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            max_filter_terms=1,
            default_where_provider=lambda _type_name: {"is_deleted": False},
        )
        with self.assertRaises(RGQLExpandError):
            await expand_navs_recursive(
                root_entity=_Entity(id=1),
                ctx=ctx,
                expand_item=ExpandItem(path="Children"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

    async def test_expand_navs_recursive_additional_false_branches(self) -> None:
        child_service = _FakeNavService(
            list_result=[],
            get_result=_Child(id=9, owner_id=None, name=None, secret="hidden"),
        )
        services = {"NS.Child": child_service}
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
        )

        parent = _Entity(id=1)
        await expand_navs_recursive(
            root_entity=parent,
            ctx=ctx,
            expand_item=ExpandItem(path="Children"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )
        self.assertFalse(hasattr(parent, "children"))

        parent.owner_id = 9
        await expand_navs_recursive(
            root_entity=parent,
            ctx=ctx,
            expand_item=ExpandItem(path="Owner", select=["Secret"]),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )
        self.assertFalse(hasattr(parent, "owner"))

        # Ensure collection path executes child loop with no nested expands.
        child_service = _FakeNavService(
            list_result=[_Child(id=12, parent_id=1, name="Solo")]
        )
        services = {"NS.Child": child_service}
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
        )
        await expand_navs_recursive(
            root_entity=parent,
            ctx=ctx,
            expand_item=ExpandItem(path="Children"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )
        self.assertEqual(parent.children, [{"Id": 12, "ParentId": 1, "Name": "Solo"}])  # type: ignore[attr-defined]

        # Force defensive branch where collection filter groups are empty.
        with patch(
            "mugen.core.gateway.storage.rdbms.rgql_adapter.rgql_expand.apply_to_filter_groups",
            return_value=[],
        ):
            await expand_navs_recursive(
                root_entity=parent,
                ctx=ctx,
                expand_item=ExpandItem(path="Children"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

    async def test_expand_navs_bulk_early_and_validation_branches(self) -> None:
        ctx = self._make_context()

        await expand_navs_bulk(
            root_entities=[],
            ctx=ctx,
            expand_item=ExpandItem(path="Children"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

        with self.assertRaises(RGQLExpandError):
            await expand_navs_bulk(
                root_entities=[_Entity(id=1)],
                ctx=ctx,
                expand_item=ExpandItem(path="Children/Nested"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        await expand_navs_bulk(
            root_entities=[_Entity(id=1)],
            ctx=ctx,
            expand_item=ExpandItem(path="UnknownNav"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

        ctx_no_service = self._make_context(service_resolver=lambda _type_name: None)
        await expand_navs_bulk(
            root_entities=[_Entity(id=1)],
            ctx=ctx_no_service,
            expand_item=ExpandItem(path="Children"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

        ctx = self._make_context(
            adapter=_FixedAdapter(([], [OrderBy("x"), OrderBy("y")], 1, 0)),
            max_orderby=1,
        )
        with self.assertRaises(RGQLExpandError):
            await expand_navs_bulk(
                root_entities=[_Entity(id=1)],
                ctx=ctx,
                expand_item=ExpandItem(path="Children"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

    async def test_expand_navs_bulk_maps_adapter_value_error(self) -> None:
        class _FailingAdapter:
            def build_relational_query(self, _opts, **_kwargs):
                raise ValueError("bad nested orderby")

        ctx = self._make_context(adapter=_FailingAdapter())
        with self.assertRaises(RGQLExpandError) as ex:
            await expand_navs_bulk(
                root_entities=[_Entity(id=1)],
                ctx=ctx,
                expand_item=ExpandItem(path="Children"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )
        self.assertEqual(ex.exception.args, (400, "bad nested orderby"))

    async def test_expand_navs_bulk_collection_materializes_children(self) -> None:
        child_service = _FakeNavService(
            partition_result=[
                _Child(id=201, parent_id=10, owner_id=7, name="One"),
                _Child(id=202, parent_id=11, owner_id=8, name="Two"),
            ]
        )
        services = {"NS.Child": child_service}
        serialize_calls = []

        def serializer(entity, _edm_type, cols, paths):
            serialize_calls.append((entity.id, tuple(cols or []), frozenset(paths)))
            return {"Name": entity.name}

        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], None, None)),
            service_resolver=lambda type_name: services.get(type_name),
            serialization_provider=serializer,
            default_where_provider=lambda _type_name: {"is_deleted": False},
        )

        roots = [_Entity(id=10), _Entity(id=11)]
        await expand_navs_bulk(
            root_entities=roots,
            ctx=ctx,
            expand_item=ExpandItem(
                path="Children",
                select=["Name"],
                expand=[ExpandItem(path="Owner")],
            ),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

        self.assertEqual(roots[0].children, [{"Name": "One"}])  # type: ignore[attr-defined]
        self.assertEqual(roots[1].children, [{"Name": "Two"}])  # type: ignore[attr-defined]

        self.assertEqual(child_service.last_partition_kwargs["fk_field"], "parent_id")
        self.assertEqual(child_service.last_partition_kwargs["fk_values"], [10, 11])
        self.assertIn("name", child_service.last_partition_kwargs["columns"])
        self.assertIn("parent_id", child_service.last_partition_kwargs["columns"])
        self.assertIn("id", child_service.last_partition_kwargs["columns"])
        self.assertEqual(
            child_service.last_partition_kwargs["filter_groups"][0].where,
            {"is_deleted": False},
        )
        self.assertEqual(len(serialize_calls), 2)

    async def test_expand_navs_bulk_single_materializes_children(self) -> None:
        child_service = _FakeNavService(
            list_result=[
                _Child(id=5, owner_id=99, name="BossA"),
                _Child(id=6, owner_id=98, name="BossB"),
            ]
        )
        services = {"NS.Child": child_service}

        def serializer(entity, _edm_type, _cols, _paths):
            return {"Name": entity.name}

        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], None, None)),
            service_resolver=lambda type_name: services.get(type_name),
            serialization_provider=serializer,
            default_where_provider=lambda _type_name: {"is_deleted": False},
        )

        roots = [_Entity(id=1, owner_id=5), _Entity(id=2, owner_id=6), _Entity(id=3)]
        await expand_navs_bulk(
            root_entities=roots,
            ctx=ctx,
            expand_item=ExpandItem(
                path="Owner",
                select=["Name"],
                expand=[ExpandItem(path="Owner")],
            ),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

        self.assertEqual(roots[0].owner, {"Name": "BossA"})  # type: ignore[attr-defined]
        self.assertEqual(roots[1].owner, {"Name": "BossB"})  # type: ignore[attr-defined]
        self.assertFalse(hasattr(roots[2], "owner"))

        self.assertIn("name", child_service.last_list_kwargs["columns"])
        self.assertIn("id", child_service.last_list_kwargs["columns"])
        self.assertIn("owner_id", child_service.last_list_kwargs["columns"])

        scalar_filters = child_service.last_list_kwargs["filter_groups"][0].scalar_filters
        self.assertEqual(len(scalar_filters), 1)
        self.assertEqual(scalar_filters[0].op, ScalarFilterOp.IN)
        self.assertEqual(scalar_filters[0].value, [5, 6])

        ctx = self._make_context(adapter=_FixedAdapter(([], [], 11, 0)), max_top=10)
        with self.assertRaises(RGQLExpandError):
            await expand_navs_bulk(
                root_entities=[_Entity(id=1)],
                ctx=ctx,
                expand_item=ExpandItem(path="Children"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

    async def test_expand_navs_bulk_collection_additional_edges(self) -> None:
        child_service = _FakeNavService(
            partition_result=[_Child(id=301, parent_id=10, owner_id=77, name="Kid")]
        )
        services = {"NS.Child": child_service}

        # No parent ids -> early return.
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
        )
        await expand_navs_bulk(
            root_entities=[_Entity(id=None)],
            ctx=ctx,
            expand_item=ExpandItem(path="Children"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )
        self.assertIsNone(child_service.last_partition_kwargs)

        # Wildcard blocked in bulk.
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
            allow_expand_wildcard=False,
        )
        with self.assertRaises(RGQLExpandError):
            await expand_navs_bulk(
                root_entities=[_Entity(id=10)],
                ctx=ctx,
                expand_item=ExpandItem(path="Children", expand=[ExpandItem(path="*")]),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        # Max expand paths exceeded in bulk.
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
            max_expand_paths=1,
        )
        with self.assertRaises(RGQLExpandError):
            await expand_navs_bulk(
                root_entities=[_Entity(id=10)],
                ctx=ctx,
                expand_item=ExpandItem(
                    path="Children",
                    expand=[ExpandItem(path="A"), ExpandItem(path="B")],
                ),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        # Max select exceeded in bulk.
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
            max_select=1,
        )
        with self.assertRaises(RGQLExpandError):
            await expand_navs_bulk(
                root_entities=[_Entity(id=10)],
                ctx=ctx,
                expand_item=ExpandItem(path="Children", select=["Id", "Name"]),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        # Max filter terms exceeded in collection path.
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
            max_filter_terms=0,
            default_where_provider=lambda _type_name: {"is_deleted": False},
        )
        with self.assertRaises(RGQLExpandError):
            await expand_navs_bulk(
                root_entities=[_Entity(id=10)],
                ctx=ctx,
                expand_item=ExpandItem(path="Children"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        # Force column-augmentation fallback branches for parent_fk/id.
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
        )
        roots = [_Entity(id=10), _Entity(id=11)]
        with patch(
            "mugen.core.gateway.storage.rdbms.rgql_adapter.rgql_expand._augment_query_columns_for_nested_expands",
            return_value=["name"],
        ):
            await expand_navs_bulk(
                root_entities=roots,
                ctx=ctx,
                expand_item=ExpandItem(
                    path="Children",
                    select=["Name"],
                    expand=[ExpandItem(path="Owner")],
                ),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        self.assertIn("parent_id", child_service.last_partition_kwargs["columns"])
        self.assertIn("id", child_service.last_partition_kwargs["columns"])
        self.assertFalse(hasattr(roots[1], "children"))

        # Query columns left as None.
        await expand_navs_bulk(
            root_entities=roots,
            ctx=ctx,
            expand_item=ExpandItem(path="Children"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )
        self.assertIsNone(child_service.last_partition_kwargs["columns"])

        # Query columns include parent_fk already, so no append branch.
        await expand_navs_bulk(
            root_entities=roots,
            ctx=ctx,
            expand_item=ExpandItem(path="Children", select=["ParentId"]),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )
        self.assertEqual(child_service.last_partition_kwargs["columns"], ["parent_id"])

        # Cover false branch where nested expands are absent.
        await expand_navs_bulk(
            root_entities=roots,
            ctx=ctx,
            expand_item=ExpandItem(path="Children", select=["Name"]),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

    async def test_expand_navs_bulk_single_additional_edges(self) -> None:
        child_service = _FakeNavService(
            list_result=[_Child(id=42, owner_id=42, name="Owner")]
        )
        services = {"NS.Child": child_service}

        # No target ids -> early return.
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
        )
        await expand_navs_bulk(
            root_entities=[_Entity(id=1, owner_id=None)],
            ctx=ctx,
            expand_item=ExpandItem(path="Owner"),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )
        self.assertIsNone(child_service.last_list_kwargs)

        # Max filter terms exceeded in single path.
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
            max_filter_terms=0,
            default_where_provider=lambda _type_name: {"is_deleted": False},
        )
        with self.assertRaises(RGQLExpandError):
            await expand_navs_bulk(
                root_entities=[_Entity(id=1, owner_id=42)],
                ctx=ctx,
                expand_item=ExpandItem(path="Owner"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        # Query columns should add id when select is present without nested expand.
        ctx = self._make_context(
            adapter=_FixedAdapter(([], [], 1, 0)),
            service_resolver=lambda type_name: services.get(type_name),
            serialization_provider=lambda entity, _edm_type, _cols, _paths: {
                "Id": entity.id,
                "Name": entity.name,
            },
        )
        roots = [_Entity(id=1, owner_id=42), _Entity(id=2, owner_id=404)]
        await expand_navs_bulk(
            root_entities=roots,
            ctx=ctx,
            expand_item=ExpandItem(path="Owner", select=["Name"]),
            current_type_name="NS.Parent",
            depth=0,
            levels_remaining=1,
        )

        self.assertIn("id", child_service.last_list_kwargs["columns"])
        self.assertEqual(roots[0].owner, {"Id": 42, "Name": "Owner"})  # type: ignore[attr-defined]
        self.assertFalse(hasattr(roots[1], "owner"))

        # Force defensive branch where single-path filter groups are empty.
        with patch(
            "mugen.core.gateway.storage.rdbms.rgql_adapter.rgql_expand.apply_to_filter_groups",
            return_value=[],
        ):
            await expand_navs_bulk(
                root_entities=[_Entity(id=1, owner_id=42)],
                ctx=ctx,
                expand_item=ExpandItem(path="Owner"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )

        ctx = self._make_context(adapter=_FixedAdapter(([], [], 1, 11)), max_skip=10)
        with self.assertRaises(RGQLExpandError):
            await expand_navs_bulk(
                root_entities=[_Entity(id=1)],
                ctx=ctx,
                expand_item=ExpandItem(path="Children"),
                current_type_name="NS.Parent",
                depth=0,
                levels_remaining=1,
            )


if __name__ == "__main__":
    unittest.main()
