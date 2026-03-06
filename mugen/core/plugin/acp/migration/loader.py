"""
Admin Control Plane (ACP) contributor loader used by runtime and Alembic.

This module provides a thin discovery + dispatch layer that:
- reads the host application's parsed `mugen_cfg` structure
- discovers enabled framework plugins
- imports each plugin's contributor module
- calls `contribute(...)` with both:
    - admin_namespace: derived from the admin plugin spec
    - plugin_namespace: derived from the contributing plugin spec

This design ensures:
- The host does not need to edit migrations to add new plugins.
- Downstream plugins can be enabled/disabled via config.
- All contributors share a uniform signature.

Configuration structure expected
--------------------------------
`mugen_cfg` must include, at minimum:

mugen_cfg["mugen"]["modules"]["core"]["extensions"]    -> list[dict]
mugen_cfg["mugen"]["modules"]["extensions"]            -> list[dict] (optional)

Each plugin dict is expected to contain:
- name: str
- namespace: str
- enabled: bool
- type: str (this loader only loads "fw")
- contrib: str (Python module path that exports a callable `contribute`)

Contributor contract
--------------------
Each contributor module must export:

    def contribute(
        registry: IAdminRegistry,
        *,
        admin_namespace: str,
        plugin_namespace: str
    ) -> None

The loader does not enforce additional parameters. If you need plugin-specific
configuration, extend the signature consistently across contributors and update
the loader accordingly.

Error behavior
--------------
- Raises RuntimeError if no admin plugin is found or multiple admin plugins exist.
- Raises ImportError / AttributeError / TypeError if contributor modules cannot
  be imported or do not expose a callable `contribute`.

Seeding gate
------------
ACP seeding itself is typically gated by the admin extension config (e.g.
`admin.seed_acp`) in the Alembic migration. This loader focuses only on contributor
discovery and invocation.
"""

from dataclasses import dataclass
from importlib import import_module
from typing import Callable

from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry

Contributor = Callable[..., None]


@dataclass(frozen=True)
class PluginSpec:
    """
    Minimal plugin specification used by ACP contributor loading.

    Attributes
    ----------
    namespace:
        Plugin namespace used for plugin-owned nouns/flags (and optionally roles).

    name:
        Plugin identifier (used to locate the 'admin' plugin).

    contrib:
        Importable Python module path that exports a `contribute` callable.
        Example: "myapp.plugins.billing.contrib"
    """

    token: str
    namespace: str
    name: str
    contrib: str  # "module.contrib_path"


def _plugin_identity(entry: dict) -> str:
    """Return the stable identity key used to collapse duplicate FW plugin specs."""
    token = str(entry.get("token", "")).strip()
    if token != "":
        return token

    name = str(entry.get("name", "")).strip()
    if name != "":
        return name

    raise KeyError("token")


def _import_callable(path: str) -> Contributor:
    """
    Import a contributor module and return its `contribute` callable.

    Parameters
    ----------
    path:
        Importable module path (not "module:function"). The module must define
        a top-level attribute named `contribute`.

    Returns
    -------
    Contributor:
        Callable contributor function.

    Raises
    ------
    ImportError:
        If the module cannot be imported.

    AttributeError:
        If the module does not define `contribute`.

    TypeError:
        If `contribute` exists but is not callable.
    """

    mod = import_module(path)
    fn = getattr(mod, "contribute")
    if not callable(fn):
        raise TypeError(f"{path} is not callable")
    return fn


def _load_enabled_framework_plugins(mugen_cfg: dict) -> list[PluginSpec]:
    """
    Load the enabled framework ("fw") plugin specs from the host config.

    This function searches:
    - core fw entries: mugen_cfg["mugen"]["modules"]["core"]["extensions"]
    - extensions: mugen_cfg["mugen"]["modules"]["extensions"] (if present)

    Filtering rules
    ---------------
    Only plugins that satisfy both are included:
    - enabled == True
    - type == "fw"

    Returns
    -------
    list[PluginSpec]:
        Plugin specs suitable for contributor invocation.

    Raises
    ------
    KeyError:
        If required config keys are missing.
    """
    out_by_token: dict[str, PluginSpec] = {}
    plugins = mugen_cfg["mugen"]["modules"]["core"].get("extensions", []) + mugen_cfg[
        "mugen"
    ]["modules"].get("extensions", [])
    for p in plugins:
        if not p.get("enabled", False) or p.get("type", "") != "fw":
            continue
        spec = PluginSpec(
            token=_plugin_identity(p),
            namespace=p["namespace"],
            name=p["name"],
            contrib=p["contrib"],
        )
        existing = out_by_token.get(spec.token)
        if existing is None:
            out_by_token[spec.token] = spec
            continue
        if existing != spec:
            raise RuntimeError(
                "Conflicting framework plugin configuration for token: "
                f"{spec.token!r}."
            )
    return list(out_by_token.values())


def contribute_all(registry: IAdminRegistry, *, mugen_cfg: dict) -> None:
    """
    Invoke `contribute(...)` for each enabled framework plugin.

    Workflow
    --------
    1) Discover enabled framework plugins via `_load_enabled_framework_plugins`.
    2) Identify the admin plugin; its namespace becomes the canonical `admin_namespace`
       passed to every contributor.
    3) For each enabled plugin:
       - import its contributor module
       - call contributor with:
           registry=registry
           admin_namespace=<admin plugin namespace>
           plugin_namespace=<that plugin's namespace>

    Parameters
    ----------
    registry:
        ACP registry to receive contributions.

    mugen_cfg:
        Parsed host configuration dictionary.

    Raises
    ------
    RuntimeError:
        If the admin plugin is missing or ambiguous (not exactly one).

    ImportError / AttributeError / TypeError:
        If any contributor cannot be imported or is not callable.
    """
    plugins = _load_enabled_framework_plugins(mugen_cfg)
    admin = [p for p in plugins if p.name == mugen_cfg["acp"]["plugin_name"]]

    if admin and len(admin) == 1:
        admin = admin[0]
        for spec in plugins:
            fn = _import_callable(spec.contrib)
            fn(
                registry,
                admin_namespace=admin.namespace,
                plugin_namespace=spec.namespace,
            )
    else:
        raise RuntimeError("admin plugin is required for ACP seeding.")
