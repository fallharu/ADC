CREATE TABLE Video (
        video_id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL UNIQUE,
        upload_datetime TEXT NOT NULL,
        fps REAL,
        duration REAL,
        source_path TEXT
    , location_point INTEGER NOT NULL DEFAULT 0, recorded_date TEXT)