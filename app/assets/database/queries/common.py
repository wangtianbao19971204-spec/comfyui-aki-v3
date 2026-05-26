"""Shared utilities for database query modules."""

import os
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

import sqlalchemy as sa
from sqlalchemy import exists

import folder_paths
from app.assets.database.models import AssetReference, AssetReferenceMeta, AssetReferenceTag
from app.assets.helpers import normalize_tags

MAX_BIND_PARAMS = 800

# Mirrors app.model_manager.MODEL_FOLDER_BLACKLIST: these names are bootstrapped
# into folder_names_and_paths by core, but /api/experiment/models does not expose
# them as model folders. Keep this local to avoid reintroducing the asset query
# package initialization cycle from importing service/model-manager code here.
_NON_MODEL_FOLDER_NAMES = frozenset({"configs", "custom_nodes"})


def calculate_rows_per_statement(cols: int) -> int:
    """Calculate how many rows can fit in one statement given column count."""
    return max(1, MAX_BIND_PARAMS // max(1, cols))


def iter_chunks(seq, n: int):
    """Yield successive n-sized chunks from seq."""
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def iter_row_chunks(rows: list[dict], cols_per_row: int) -> Iterable[list[dict]]:
    """Yield chunks of rows sized to fit within bind param limits."""
    if not rows:
        return
    yield from iter_chunks(rows, calculate_rows_per_statement(cols_per_row))


def build_visible_owner_clause(owner_id: str) -> sa.sql.ClauseElement:
    """Build owner visibility predicate for reads.

    Owner-less rows are visible to everyone.
    """
    owner_id = (owner_id or "").strip()
    if owner_id == "":
        return AssetReference.owner_id == ""
    return AssetReference.owner_id.in_(["", owner_id])


def build_prefix_like_conditions(
    prefixes: list[str],
) -> list[sa.sql.ColumnElement]:
    """Build case-exact conditions for matching file paths under directory prefixes."""
    conds = []
    for p in prefixes:
        base = os.path.abspath(p)
        if not base.endswith(os.sep):
            base += os.sep
        conds.append(sa.func.substr(AssetReference.file_path, 1, len(base)) == base)
    return conds


def _get_comfy_model_folders() -> list[tuple[str, list[str]]]:
    """Return registered model folder names and roots without importing services.

    This intentionally stays local to the query layer to avoid importing
    ``app.assets.services`` from ``app.assets.database.queries.common``, which
    creates a package initialization cycle.
    """
    targets: list[tuple[str, list[str]]] = []
    for name, values in folder_paths.folder_names_and_paths.items():
        if name in _NON_MODEL_FOLDER_NAMES:
            continue
        paths, _exts = values[0], values[1]
        if paths:
            targets.append((name, paths))
    return targets


def apply_asset_path_filters(
    stmt: sa.sql.Select,
    asset_type: str | None = None,
    model_folder: str | None = None,
) -> sa.sql.Select:
    """Filter references using their real filesystem/root registration context."""
    if asset_type is None and model_folder is None:
        return stmt
    if model_folder and asset_type != "model":
        raise ValueError("model_folder can only be used with asset_type=model")

    registered_model_folders = _get_comfy_model_folders()
    prefixes: list[str] = []
    exclude_prefixes: list[str] = []
    if model_folder:
        for folder_name, paths in registered_model_folders:
            if folder_name == model_folder:
                prefixes.extend(paths)
                break
        if not prefixes:
            return stmt.where(sa.false())

        target_bases = [os.path.abspath(path) for path in prefixes]
        for folder_name, paths in registered_model_folders:
            if folder_name == model_folder:
                continue
            for path in paths:
                path_abs = os.path.abspath(path)
                if any(
                    Path(path_abs).is_relative_to(target_base)
                    and path_abs != target_base
                    for target_base in target_bases
                ):
                    exclude_prefixes.append(path)
    elif asset_type == "model":
        for _folder_name, paths in registered_model_folders:
            prefixes.extend(paths)
    elif asset_type == "input":
        prefixes = [folder_paths.get_input_directory()]
    elif asset_type == "output":
        prefixes = [folder_paths.get_output_directory()]
    elif asset_type == "temp":
        prefixes = [folder_paths.get_temp_directory()]

    conditions = build_prefix_like_conditions(prefixes)
    if not conditions:
        return stmt.where(sa.false())

    clause = sa.or_(*conditions)
    if asset_type in {"input", "output", "temp"}:
        model_prefixes = [
            path for _folder_name, paths in registered_model_folders for path in paths
        ]
        model_conditions = build_prefix_like_conditions(model_prefixes)
        if model_conditions:
            clause = sa.and_(clause, sa.not_(sa.or_(*model_conditions)))
    elif exclude_prefixes:
        exclude_conditions = build_prefix_like_conditions(exclude_prefixes)
        if exclude_conditions:
            clause = sa.and_(clause, sa.not_(sa.or_(*exclude_conditions)))

    return stmt.where(clause)


def apply_tag_filters(
    stmt: sa.sql.Select,
    include_tags: Sequence[str] | None = None,
    exclude_tags: Sequence[str] | None = None,
) -> sa.sql.Select:
    """include_tags: every tag must be present; exclude_tags: none may be present."""
    include_tags = normalize_tags(include_tags)
    exclude_tags = normalize_tags(exclude_tags)

    if include_tags:
        for tag_name in include_tags:
            stmt = stmt.where(
                exists().where(
                    (AssetReferenceTag.asset_reference_id == AssetReference.id)
                    & (AssetReferenceTag.tag_name == tag_name)
                )
            )

    if exclude_tags:
        stmt = stmt.where(
            ~exists().where(
                (AssetReferenceTag.asset_reference_id == AssetReference.id)
                & (AssetReferenceTag.tag_name.in_(exclude_tags))
            )
        )
    return stmt


def apply_metadata_filter(
    stmt: sa.sql.Select,
    metadata_filter: dict | None = None,
) -> sa.sql.Select:
    """Apply filters using asset_reference_meta projection table."""
    if not metadata_filter:
        return stmt

    def _exists_for_pred(key: str, *preds) -> sa.sql.ClauseElement:
        return sa.exists().where(
            AssetReferenceMeta.asset_reference_id == AssetReference.id,
            AssetReferenceMeta.key == key,
            *preds,
        )

    def _exists_clause_for_value(key: str, value) -> sa.sql.ClauseElement:
        if value is None:
            return sa.not_(
                sa.exists().where(
                    AssetReferenceMeta.asset_reference_id == AssetReference.id,
                    AssetReferenceMeta.key == key,
                )
            )

        if isinstance(value, bool):
            return _exists_for_pred(key, AssetReferenceMeta.val_bool == bool(value))
        if isinstance(value, (int, float, Decimal)):
            num = value if isinstance(value, Decimal) else Decimal(str(value))
            return _exists_for_pred(key, AssetReferenceMeta.val_num == num)
        if isinstance(value, str):
            return _exists_for_pred(key, AssetReferenceMeta.val_str == value)
        return _exists_for_pred(key, AssetReferenceMeta.val_json == value)

    for k, v in metadata_filter.items():
        if isinstance(v, list):
            ors = [_exists_clause_for_value(k, elem) for elem in v]
            if ors:
                stmt = stmt.where(sa.or_(*ors))
        else:
            stmt = stmt.where(_exists_clause_for_value(k, v))
    return stmt
