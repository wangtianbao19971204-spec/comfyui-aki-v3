CREATE TABLE collect_history (
                id_index INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT,
                name TEXT,
                color TEXT,
                create_time INTEGER,
                is_deleted INTEGER DEFAULT 0
            );

CREATE TABLE history (
                id_index INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT,
                name TEXT,
                color TEXT,
                create_time INTEGER,
                is_deleted INTEGER DEFAULT 0
            );

CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );
