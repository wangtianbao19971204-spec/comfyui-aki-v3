CREATE TABLE danbooru_tag (
                id_index INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT,
                color_id INTEGER,
                translate TEXT,
                hot INTEGER DEFAULT 0,
                aliases INTEGER DEFAULT 0
            );

CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );

CREATE TABLE update_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                update_at INTEGER
            );
