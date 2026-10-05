"""Contextual facet counts over the library's existing reviewed row order."""
from .semantic_taxonomy import CLASS_LABELS, FACET_CLASS_MAP, SUBCATEGORY_PARENTS, semantic_themes, subcategory_owner
from .semantic_refinements import REFINEMENT_NODES


def row_mask(positions, size):
    packed = bytearray((size + 7) // 8)
    for position in positions:
        packed[position >> 3] |= 1 << (position & 7)
    return int.from_bytes(packed, 'little')


def sub_identity(value):
    owner, separator, label = value.partition('::')
    if separator and owner in CLASS_LABELS:
        return owner, label
    return SUBCATEGORY_PARENTS.get(value) or SUBCATEGORY_PARENTS.get(value.split('/', 1)[0]), value


def filter_group(axis, value):
    if axis in ('theme', 'facet'):
        return 'theme'
    if axis == 'sub':
        owner, label = sub_identity(value)
        return 'sub:' + (owner or label)
    if axis == 'detail':
        node = REFINEMENT_NODES.get(value)
        return 'detail:' + (node['parent'] if node else value)
    return 'sub:person_count'


def build_filter_masks(rows):
    size = len(rows)
    width = (size + 7) // 8
    buffers = {}
    for position, row in enumerate(rows):
        semantic = row[0]['_semantic']
        keys = {('theme', value) for value in semantic_themes(semantic)}
        keys.update(('count', value) for value in semantic.get('count_markers') or [])
        subcategories = semantic.get('subcategories') or []
        for label in subcategories:
            owner = subcategory_owner(semantic, label)
            parts = label.split('/')
            for end in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:end])
                keys.add(('sub', prefix))
                if owner:
                    keys.add(('sub', owner + '::' + prefix))
        for identity in semantic.get('refinements') or []:
            node = REFINEMENT_NODES.get(identity)
            if node and any(label == node['parent'] or label.startswith(node['parent'] + '/') for label in subcategories):
                keys.add(('detail', identity))
        for key in keys:
            packed = buffers.get(key)
            if packed is None:
                packed = buffers[key] = bytearray(width)
            packed[position >> 3] |= 1 << (position & 7)
    return {'size': size, 'all': (1 << size) - 1,
            'values': {key: int.from_bytes(value, 'little') for key, value in buffers.items()}}


def filter_mask(index, axis, value):
    if axis == 'facet':
        return index['values'].get(('theme', FACET_CLASS_MAP.get(value, value)), 0)
    if axis == 'theme' and value == 'style_quality':
        return index['values'].get(('theme', 'style_medium'), 0) | index['values'].get(('theme', 'quality_detail'), 0)
    return index['values'].get((axis, value), 0)


def conditional_filter_counts(index, base, filters, mode, pool):
    """ANY ignores the candidate's group; ALL retains its existing conditions.

    Selecting a child replaces its explicit parent, while returning to a parent
    removes that parent's selected children. Count those same transitions.
    """
    selected = [(axis, value, filter_group(axis, value), filter_mask(index, axis, value))
                for axis, values in filters.items() for value in values]
    options = [('theme', value) for value in pool.get('theme', {})]
    options += [('sub', pool.get('subcategory_values', {}).get(value, value))
                for values in pool.get('subcategory', {}).values() for value in values]
    options += [('count', value) for value in pool.get('count', {})]
    options += [('detail', node['id']) for children in pool.get('refinements', {}).values() for node in children]
    result = {'theme': {}, 'subcategory': {}, 'count': {}, 'detail': {}, 'mode': mode}
    # Several hundred candidates share the same excluded groups or parent.
    contexts = {}
    for axis, value in options:
        group = filter_group(axis, value)
        parent = REFINEMENT_NODES[value]['parent'] if axis == 'detail' else sub_identity(value)[1] if axis == 'sub' else None
        context_key = (axis, group, parent)
        if context_key not in contexts:
            groups = {}
            for selected_axis, selected_value, selected_group, mask in selected:
                if mode != 'all' and selected_group == group:
                    continue
                if axis == 'detail' and selected_axis == 'sub' and selected_value in (parent, REFINEMENT_NODES[value]['owner'] + '::' + parent):
                    continue
                if axis == 'sub' and selected_axis == 'detail' and selected_group == 'detail:' + parent:
                    continue
                if selected_group not in groups:
                    groups[selected_group] = mask
                elif mode == 'all':
                    groups[selected_group] &= mask
                else:
                    groups[selected_group] |= mask
            context = base
            for mask in groups.values():
                context &= mask
            contexts[context_key] = context
        result['subcategory' if axis == 'sub' else axis][value] = (contexts[context_key] & filter_mask(index, axis, value)).bit_count()
    return result
