"""
Provides a utility class to consistently build ACP keys from the configured admin
namespace.
"""

from dataclasses import dataclass

from mugen.core.plugin.acp.contract.sdk.resource import AdminPermissions


@dataclass(frozen=True, slots=True)
class AdminNs:
    """
    Helper to consistently build ACP keys from the configured admin namespace.

    This class centralizes construction of fully-qualified keys of the form:
        "<namespace>:<name>"

    The namespace should be the configured admin plugin namespace (from TOML/DI).
    """

    ns: str

    def __post_init__(self) -> None:
        ns = self.ns.strip().lower()
        if not ns:
            raise ValueError("AdminNs.ns must be a non-empty string.")
        if ":" in ns:
            # Prevent accidental double-qualification like "com.foo:admin"
            raise ValueError(
                "AdminNs.ns must not contain ':'. Provide the namespace token only."
            )
        object.__setattr__(self, "ns", ns)

    def key(self, name: str) -> str:
        """
        Build a fully-qualified ACP key: "<namespace>:<name>".

        Parameters
        ----------
        name:
            The unqualified key name (e.g., "read", "user", "permission_type").
            Must be non-empty and must not contain ':'.
        """
        n = name.strip()
        if not n:
            raise ValueError("Key name must be a non-empty string.")
        if ":" in n:
            raise ValueError(
                "Key name must not contain ':'. Provide the unqualified name."
            )
        return f"{self.ns}:{n}"

    def obj(self, name: str) -> str:
        """
        Build a permission object key for the given object name.
        Example: obj("user") -> "<namespace>:user"
        """
        return self.key(name)

    def verb(self, name: str) -> str:
        """
        Build a permission type (verb) key for the given verb name.
        Example: verb("read") -> "<namespace>:read"
        """
        return self.key(name)

    def perms(self, object_name: str) -> AdminPermissions:
        """
        Build an AdminPermissions bundle for a resource whose permission object
        is `object_name`, using standard admin verbs (read/create/update/delete/manage)
        within this namespace.
        """
        return AdminPermissions(
            permission_object=self.obj(object_name),
            read=self.verb("read"),
            create=self.verb("create"),
            update=self.verb("update"),
            delete=self.verb("delete"),
            manage=self.verb("manage"),
        )
