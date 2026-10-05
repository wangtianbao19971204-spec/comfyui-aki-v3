CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );

CREATE TABLE tag_groups (
                id_index INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                color TEXT,
                create_time INTEGER,
                p_uuid TEXT(128)
            );

CREATE TABLE tag_subgroups (
                id_index INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                name TEXT,
                color TEXT,
                create_time INTEGER,
                p_uuid TEXT(128),
                g_uuid TEXT(128)
            );

CREATE TABLE tag_tags (
                id_index INTEGER PRIMARY KEY AUTOINCREMENT,
                subgroup_id INTEGER,
                text TEXT,
                desc TEXT,
                color TEXT,
                create_time INTEGER,
                t_uuid TEXT(128),
                g_uuid TEXT(128)
            );

CREATE TABLE update_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                update_at INTEGER
            );

CREATE TABLE workbench_tag_flags_meta (id INTEGER PRIMARY KEY, version INTEGER NOT NULL);

CREATE TABLE workbench_tag_folder_members (
            tag_uuid TEXT NOT NULL, g_uuid TEXT NOT NULL, PRIMARY KEY (tag_uuid, g_uuid));

CREATE TABLE workbench_tag_meta (tag_uuid TEXT PRIMARY KEY, data TEXT NOT NULL);

CREATE TABLE workbench_tag_revision (id INTEGER PRIMARY KEY, value INTEGER NOT NULL);

CREATE TABLE workbench_tag_string_flags (
            tag_uuid TEXT PRIMARY KEY, g_uuid TEXT NOT NULL DEFAULT '',
            commas INTEGER NOT NULL DEFAULT 0, suspect INTEGER NOT NULL DEFAULT 0,
            words INTEGER NOT NULL DEFAULT 0);

CREATE TABLE workbench_tag_text_revision (id INTEGER PRIMARY KEY, value INTEGER NOT NULL);

CREATE INDEX idx_tag_folder_members_g_uuid ON workbench_tag_folder_members(g_uuid);

CREATE UNIQUE INDEX idx_tag_groups_p_uuid ON tag_groups(p_uuid);

CREATE INDEX idx_tag_meta_favorite ON workbench_tag_meta(json_extract(data,'$.favorite'));

CREATE INDEX idx_tag_string_flags_group ON workbench_tag_string_flags(g_uuid);

CREATE UNIQUE INDEX idx_tag_subgroups_g_uuid ON tag_subgroups(g_uuid);

CREATE INDEX idx_tag_subgroups_p_uuid
            ON tag_subgroups(p_uuid);

CREATE INDEX idx_tag_tags_create_time
            ON tag_tags(create_time);

CREATE INDEX idx_tag_tags_g_uuid
            ON tag_tags(g_uuid);

CREATE UNIQUE INDEX idx_tag_tags_t_uuid ON tag_tags(t_uuid);

CREATE INDEX idx_tag_tags_text
            ON tag_tags(text);

CREATE INDEX workbench_tag_identity ON tag_tags(t_uuid);

CREATE TRIGGER workbench_tag_groups_delete AFTER DELETE ON tag_groups BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_groups_insert AFTER INSERT ON tag_groups BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_groups_update AFTER UPDATE ON tag_groups BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_members_delete
                AFTER DELETE ON workbench_tag_meta BEGIN
                DELETE FROM workbench_tag_folder_members WHERE tag_uuid = OLD.tag_uuid;
                
                END;

CREATE TRIGGER workbench_tag_members_insert
                AFTER INSERT ON workbench_tag_meta BEGIN
                DELETE FROM workbench_tag_folder_members WHERE tag_uuid = NEW.tag_uuid;
                INSERT OR IGNORE INTO workbench_tag_folder_members (tag_uuid, g_uuid) SELECT NEW.tag_uuid, value FROM json_each(json_extract(NEW.data,'$.folder_ids'));
                END;

CREATE TRIGGER workbench_tag_members_update
                AFTER UPDATE ON workbench_tag_meta BEGIN
                DELETE FROM workbench_tag_folder_members WHERE tag_uuid = NEW.tag_uuid;
                INSERT OR IGNORE INTO workbench_tag_folder_members (tag_uuid, g_uuid) SELECT NEW.tag_uuid, value FROM json_each(json_extract(NEW.data,'$.folder_ids'));
                END;

CREATE TRIGGER workbench_tag_string_flags_delete
                AFTER DELETE ON tag_tags BEGIN DELETE FROM workbench_tag_string_flags WHERE tag_uuid = OLD.t_uuid; END;

CREATE TRIGGER workbench_tag_string_flags_insert
                AFTER INSERT ON tag_tags BEGIN INSERT OR REPLACE INTO workbench_tag_string_flags (tag_uuid, g_uuid, commas, suspect, words) VALUES (NEW.t_uuid, COALESCE(NEW.g_uuid,''), (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),',',''))) + (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),'，',''))), ((length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),',',''))) + (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),'，',''))) >= 4 AND (instr(replace(replace(replace(replace(COALESCE(NEW.text,''),'，',','),' ',''),char(9),''),char(10),''), ',,') > 0 OR substr(replace(replace(replace(replace(COALESCE(NEW.text,''),'，',','),' ',''),char(9),''),char(10),''), 1, 1) = ',' OR substr(replace(replace(replace(replace(COALESCE(NEW.text,''),'，',','),' ',''),char(9),''),char(10),''), -1, 1) = ',') AND ((length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),',',''))) + (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),'，',''))) <= 11 OR instr(replace(replace(replace(replace(COALESCE(NEW.text,''),'，',','),' ',''),char(9),''),char(10),''), ',,,') > 0)), (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),',',''))) + (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),'，',''))) + 1); END;

CREATE TRIGGER workbench_tag_string_flags_update
                AFTER UPDATE ON tag_tags BEGIN INSERT OR REPLACE INTO workbench_tag_string_flags (tag_uuid, g_uuid, commas, suspect, words) VALUES (NEW.t_uuid, COALESCE(NEW.g_uuid,''), (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),',',''))) + (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),'，',''))), ((length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),',',''))) + (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),'，',''))) >= 4 AND (instr(replace(replace(replace(replace(COALESCE(NEW.text,''),'，',','),' ',''),char(9),''),char(10),''), ',,') > 0 OR substr(replace(replace(replace(replace(COALESCE(NEW.text,''),'，',','),' ',''),char(9),''),char(10),''), 1, 1) = ',' OR substr(replace(replace(replace(replace(COALESCE(NEW.text,''),'，',','),' ',''),char(9),''),char(10),''), -1, 1) = ',') AND ((length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),',',''))) + (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),'，',''))) <= 11 OR instr(replace(replace(replace(replace(COALESCE(NEW.text,''),'，',','),' ',''),char(9),''),char(10),''), ',,,') > 0)), (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),',',''))) + (length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),'，',''))) + 1); END;

CREATE TRIGGER workbench_tag_subgroups_delete AFTER DELETE ON tag_subgroups BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_subgroups_insert AFTER INSERT ON tag_subgroups BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_subgroups_update AFTER UPDATE ON tag_subgroups BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_tags_delete AFTER DELETE ON tag_tags BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_tags_insert AFTER INSERT ON tag_tags BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_tags_update AFTER UPDATE ON tag_tags BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_text_delete
                AFTER DELETE ON tag_tags BEGIN
                UPDATE workbench_tag_text_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_text_insert
                AFTER INSERT ON tag_tags BEGIN
                UPDATE workbench_tag_text_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_text_subgroup_delete
                AFTER DELETE ON tag_subgroups BEGIN
                UPDATE workbench_tag_text_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_text_subgroup_insert
                AFTER INSERT ON tag_subgroups BEGIN
                UPDATE workbench_tag_text_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_text_subgroup_update
                AFTER UPDATE ON tag_subgroups BEGIN
                UPDATE workbench_tag_text_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_tag_text_update
                AFTER UPDATE ON tag_tags BEGIN
                UPDATE workbench_tag_text_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_workbench_tag_meta_delete AFTER DELETE ON workbench_tag_meta BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_workbench_tag_meta_insert AFTER INSERT ON workbench_tag_meta BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;

CREATE TRIGGER workbench_workbench_tag_meta_update AFTER UPDATE ON workbench_tag_meta BEGIN UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END;
