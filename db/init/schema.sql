CREATE TYPE action AS enum('allow', 'reject');

CREATE TABLE IF NOT EXISTS entries (
	id          serial  PRIMARY KEY,
	vmname      text    NOT NULL,
    comment     text    NOT NULL,
    source      text    NOT NULL,
    service     text    NOT NULL,
    action      action  NOT NULL
);

