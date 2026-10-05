import asyncio
import time
from ..dao import dao
from ..dao.dao import fetch_all
from ....prompt_selector.tag_library import TagLibrary

_tags_cache = None
_tags_cache_time = 0
_tags_cache_revision = None
CACHE_DURATION = 300


def _library():
    return TagLibrary(dao.tags_db_path)


def _invalidate_cache():
    global _tags_cache, _tags_cache_time, _tags_cache_revision
    _tags_cache = None
    _tags_cache_time = 0
    _tags_cache_revision = None


async def _change(payload):
    result = await asyncio.to_thread(lambda: _library().update(payload))
    _invalidate_cache()
    return result


async def add_group_tag(text, desc, subgroup_id, color, g_uuid):
    await _change({'operation':'create','text':text,'desc':desc,'color':color,'g_uuid':g_uuid})


async def edit_group_tag(text, desc, id_index, color):
    identity = _library().legacy_identity('tag', id_index)
    await _change({'operation':'edit','t_uuid':identity,'text':text,'desc':desc,'color':color})


async def delete_group_tag(id_index):
    identity = _library().legacy_identity('tag', id_index)
    await _change({'operation':'delete','t_uuid':identity})


async def batch_delete_group_tags(id_indices):
    store = _library()
    items = [{'operation':'delete','t_uuid':store.legacy_identity('tag', index)} for index in id_indices]
    if items:
        await _change({'operation':'batch','items':items})


async def add_new_node_group(key, color):
    await _change({'entity':'group','operation':'create','name':key,'color':color})
    return {'code':200}


async def add_new_group(key, group_key, color, p_uuid):
    await _change({'entity':'subgroup','operation':'create','name':group_key,'color':color,'p_uuid':p_uuid})
    return {'code':200}


async def edit_node_group(id_index, new_key, new_color):
    identity = _library().legacy_identity('group', id_index)
    await _change({'entity':'group','operation':'edit','p_uuid':identity,'name':new_key,'color':new_color})
    return {'code':200}


async def edit_child_node_group(id_index, new_key, new_color):
    identity = _library().legacy_identity('subgroup', id_index)
    await _change({'entity':'subgroup','operation':'edit','g_uuid':identity,'name':new_key,'color':new_color})
    return {'code':200}


def delete_node_group(p_uuid):
    _library().update({'entity':'group','operation':'delete','p_uuid':p_uuid,'delete_contents':True})
    _invalidate_cache()


def delete_child_node_group(g_uuid):
    _library().update({'entity':'subgroup','operation':'delete','g_uuid':g_uuid,'delete_contents':True})
    _invalidate_cache()


async def _move(entity, id_index, reference_id_index, position):
    def change():
        store = _library()
        store.reorder(entity, store.legacy_identity(entity, id_index), store.legacy_identity(entity, reference_id_index), position)
    await asyncio.to_thread(change)
    _invalidate_cache()
    return {'info': 'Moved'}


async def move_tag(id_index, reference_id_index, position='before'):
    return await _move('tag', id_index, reference_id_index, position)


async def move_group(id_index, reference_id_index, position='before'):
    return await _move('group', id_index, reference_id_index, position)


async def move_subgroup(id_index, reference_id_index, position='before'):
    return await _move('subgroup', id_index, reference_id_index, position)


def run_sql_text(sql_array):
    try:
        _library().legacy_sql(sql_array)
        _invalidate_cache()
        return {'code':200,'message':'SQL执行成功'}
    except Exception as error:
        return {'code':500,'message':str(error)}


async def get_group_tags():
    """
    获取所有标签分组（带缓存）
    文件位置: app/server/prompt_api/tags_manager.py:231
    """
    global _tags_cache, _tags_cache_time, _tags_cache_revision

    # 检查缓存
    current_time = time.time()
    current_revision = await asyncio.to_thread(lambda: _library().revision())
    if _tags_cache and current_revision == _tags_cache_revision and (current_time - _tags_cache_time) < CACHE_DURATION:
        return _tags_cache

    # 缓存过期，执行查询
    query = """
        SELECT
            g.id_index as group_id, g.name as group_name, g.color as group_color,
            g.create_time as group_create_time, g.p_uuid as group_p_uuid,
            sg.id_index as subgroup_id, sg.name as subgroup_name, sg.color as subgroup_color,
            sg.create_time as subgroup_create_time, sg.g_uuid as subgroup_g_uuid, sg.p_uuid as subgroup_p_uuid,
            t.id_index as tag_id, t.text as tag_text, t.desc as tag_desc,
            t.color as tag_color, t.create_time as tag_create_time, t.g_uuid as tag_g_uuid
        FROM tag_groups g
        LEFT JOIN tag_subgroups sg ON g.p_uuid = sg.p_uuid
        LEFT JOIN tag_tags t ON sg.g_uuid = t.g_uuid
        ORDER BY g.create_time ASC, sg.create_time ASC, t.create_time DESC
    """
    data = await fetch_all("tags", query)

    # 使用字典存储结果，提高查找效率
    result = {}
    subgroups = {}

    for row in data:
        # 解包数据
        group_data = {
            "id_index": row[0],
            "name": row[1],
            "color": row[2],
            "create_time": row[3],
            "p_uuid": row[4],
            "groups": [],
        }

        subgroup_data = {
            "id_index": row[5],
            "name": row[6],
            "color": row[7],
            "create_time": row[8],
            "g_uuid": row[9],
            "p_uuid": row[10],
            "tags": [],
        }

        tag_data = (
            {
                "id_index": row[11],
                "text": row[12],
                "desc": row[13],
                "color": row[14],
                "create_time": row[15],
                "g_uuid": row[16],
            }
            if row[11]
            else None
        )

        # 处理组数据
        if group_data["p_uuid"] not in result:
            result[group_data["p_uuid"]] = group_data

        # 处理子组数据
        if subgroup_data["g_uuid"] and subgroup_data["g_uuid"] not in subgroups:
            subgroups[subgroup_data["g_uuid"]] = subgroup_data
            result[group_data["p_uuid"]]["groups"].append(subgroup_data)

        # 处理标签数据
        if tag_data and tag_data["g_uuid"] in subgroups:
            subgroups[tag_data["g_uuid"]]["tags"].append(tag_data)

    # 返回列表形式的结果
    result_list = list(result.values())

    # 更新缓存
    _tags_cache = result_list
    _tags_cache_time = current_time
    _tags_cache_revision = current_revision

    return result_list



async def get_group_tags_paginated(page=1, page_size=500):
    """
    分页获取标签分组
    """
    global _tags_cache, _tags_cache_time, _tags_cache_revision

    # 检查缓存
    current_time = time.time()
    current_revision = await asyncio.to_thread(lambda: _library().revision())
    if _tags_cache and current_revision == _tags_cache_revision and (current_time - _tags_cache_time) < CACHE_DURATION:
        # 从缓存中分页返回
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "data": _tags_cache[start:end],
            "page": page,
            "page_size": page_size,
            "total": len(_tags_cache),
            "total_pages": (len(_tags_cache) + page_size - 1) // page_size,
        }

    # 缓存过期，执行查询
    query = """
        SELECT
            g.id_index as group_id, g.name as group_name, g.color as group_color,
            g.create_time as group_create_time, g.p_uuid as group_p_uuid,
            sg.id_index as subgroup_id, sg.name as subgroup_name, sg.color as subgroup_color,
            sg.create_time as subgroup_create_time, sg.g_uuid as subgroup_g_uuid, sg.p_uuid as subgroup_p_uuid,
            t.id_index as tag_id, t.text as tag_text, t.desc as tag_desc,
            t.color as tag_color, t.create_time as tag_create_time, t.g_uuid as tag_g_uuid
        FROM tag_groups g
        LEFT JOIN tag_subgroups sg ON g.p_uuid = sg.p_uuid
        LEFT JOIN tag_tags t ON sg.g_uuid = t.g_uuid
        ORDER BY g.create_time ASC, sg.create_time ASC, t.create_time DESC
    """
    data = await fetch_all("tags", query)

    # 使用字典存储结果，提高查找效率
    result = {}
    subgroups = {}

    for row in data:
        # 解包数据
        group_data = {
            "id_index": row[0],
            "name": row[1],
            "color": row[2],
            "create_time": row[3],
            "p_uuid": row[4],
            "groups": [],
        }

        subgroup_data = {
            "id_index": row[5],
            "name": row[6],
            "color": row[7],
            "create_time": row[8],
            "g_uuid": row[9],
            "p_uuid": row[10],
            "tags": [],
        }

        tag_data = (
            {
                "id_index": row[11],
                "text": row[12],
                "desc": row[13],
                "color": row[14],
                "create_time": row[15],
                "g_uuid": row[16],
            }
            if row[11]
            else None
        )

        # 处理组数据
        if group_data["p_uuid"] not in result:
            result[group_data["p_uuid"]] = group_data

        # 处理子组数据
        if subgroup_data["g_uuid"] and subgroup_data["g_uuid"] not in subgroups:
            subgroups[subgroup_data["g_uuid"]] = subgroup_data
            result[group_data["p_uuid"]]["groups"].append(subgroup_data)

        # 处理标签数据
        if tag_data and tag_data["g_uuid"] in subgroups:
            subgroups[tag_data["g_uuid"]]["tags"].append(tag_data)

    # 返回列表形式的结果
    result_list = list(result.values())

    # 更新缓存
    _tags_cache = result_list
    _tags_cache_time = current_time
    _tags_cache_revision = current_revision

    # 分页返回
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "data": result_list[start:end],
        "page": page,
        "page_size": page_size,
        "total": len(result_list),
        "total_pages": (len(result_list) + page_size - 1) // page_size,
    }



async def get_groups_list():
    query = """
        SELECT
            g.id_index as group_id, g.name as group_name, g.color as group_color,
            g.create_time as group_create_time, g.p_uuid as group_p_uuid,
            sg.id_index as subgroup_id, sg.name as subgroup_name, sg.color as subgroup_color,
            sg.create_time as subgroup_create_time, sg.g_uuid as subgroup_g_uuid, sg.p_uuid as subgroup_p_uuid
        FROM tag_groups g
        LEFT JOIN tag_subgroups sg ON g.p_uuid = sg.p_uuid
        ORDER BY g.create_time ASC, sg.create_time ASC
    """
    data = await fetch_all("tags", query)

    # 使用字典存储结果，提高查找效率
    result = {}

    for row in data:
        # 解包数据
        group_data = {
            "id_index": row[0],
            "name": row[1],
            "color": row[2],
            "create_time": row[3],
            "p_uuid": row[4],
            "groups": [],
        }

        subgroup_data = {
            "id_index": row[5],
            "name": row[6],
            "color": row[7],
            "create_time": row[8],
            "g_uuid": row[9],
            "p_uuid": row[10],
        }

        # 处理组数据
        if group_data["p_uuid"] not in result:
            result[group_data["p_uuid"]] = group_data

        # 处理子组数据
        if subgroup_data["g_uuid"]:
            result[group_data["p_uuid"]]["groups"].append(subgroup_data)

    # 返回列表形式的结果
    return list(result.values())



async def get_tag_groups():
    """获取所有标签组"""
    query = """
        SELECT
            id_index, name, color, create_time, p_uuid
        FROM tag_groups
        ORDER BY create_time ASC
    """
    data = await fetch_all("tags", query)
    return [
        {
            "id_index": row[0],
            "name": row[1],
            "color": row[2],
            "create_time": row[3],
            "p_uuid": row[4],
        }
        for row in data
    ]



async def get_tag_subgroups(p_uuid):
    """根据p_uuid获取子组"""
    query = """
        SELECT
            id_index, name, color, create_time, g_uuid, p_uuid
        FROM tag_subgroups
        WHERE p_uuid = ?
        ORDER BY create_time ASC
    """
    data = await fetch_all("tags", query, (p_uuid,))
    return [
        {
            "id_index": row[0],
            "name": row[1],
            "color": row[2],
            "create_time": row[3],
            "g_uuid": row[4],
            "p_uuid": row[5],
        }
        for row in data
    ]



async def get_tag_tags(g_uuid):
    """根据g_uuid获取标签"""
    query = """
        SELECT
            id_index, text, desc, color, create_time, g_uuid
        FROM tag_tags
        WHERE g_uuid = ?
        ORDER BY create_time DESC
    """
    data = await fetch_all("tags", query, (g_uuid,))
    return [
        {
            "id_index": row[0],
            "text": row[1],
            "desc": row[2],
            "color": row[3],
            "create_time": row[4],
            "g_uuid": row[5],
        }
        for row in data
    ]



async def search_tags(keyword):
    """模糊查询tag_tags，按匹配度排序"""
    query = """
        SELECT
            t.id_index, t.text, t.desc, t.color, t.create_time, t.g_uuid, t.t_uuid,
            (CASE
                WHEN t.text LIKE ? THEN 3
                WHEN t.desc LIKE ? THEN 2
                WHEN t.text LIKE ? THEN 1
                WHEN t.desc LIKE ? THEN 0
                ELSE -1
            END) AS match_score,
            sg.name as subgroup_name, sg.p_uuid as subgroup_p_uuid,
            g.name as group_name, g.p_uuid as group_p_uuid
        FROM tag_tags t
        LEFT JOIN tag_subgroups sg ON t.g_uuid = sg.g_uuid
        LEFT JOIN tag_groups g ON sg.p_uuid = g.p_uuid
        WHERE t.text LIKE ? OR t.desc LIKE ? OR t.text LIKE ? OR t.desc LIKE ?
        ORDER BY match_score DESC, t.create_time DESC
        LIMIT 100
    """
    # 构建模糊查询条件
    exact_match = f"%{keyword}%"
    partial_match = f"%{keyword}%"

    data = await fetch_all(
        "tags",
        query,
        (
            exact_match,
            exact_match,
            partial_match,
            partial_match,
            exact_match,
            exact_match,
            partial_match,
            partial_match,
        ),
    )

    return [
        {
            "id_index": row[0],
            "text": row[1],
            "desc": row[2],
            "color": row[3],
            "create_time": row[4],
            "g_uuid": row[5],
            "t_uuid": row[6],
            "match_score": row[7],
            "where": f"{row[1]} > {row[8]} > {row[10]}" if row[8] and row[10] else "",
            "p_uuid": row[9] if row[9] else row[11],
        }
        for row in data
    ]

