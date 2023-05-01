DROP TABLE IF EXISTS app_user;
DROP TABLE IF EXISTS pair;
DROP TABLE IF EXISTS price_history;
DROP TABLE IF EXISTS asset;
DROP TABLE IF EXISTS trade;

CREATE TABLE app_user (
    id_user SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    surname TEXT NOT NULL,
    date_of_birth DATE NOT NULL CHECK (date_of_birth <= now())
);

CREATE TABLE pair (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE price_history (
    symbol_id REFERENCES pair(symbol),
    date DATE NOT NULL (date <= now()),
    price DECIMAL NOT NULL CHECK (price >= 0),
    PRIMARY KEY (symbol_id, date)
);

CREATE TABLE asset (
    user_id INTEGER REFERENCES app_user(id_user),
    symbol_id TEXT REFERENCES pair(symbol),
    amount DECIMAL NOT NULL,
    PRIMARY KEY (user_id, symbol_id)
);

CREATE TABLE trade (
    id_trade SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES app_user(id_user)
    symbol_id TEXT REFERENCES pair(symbol)
    type TEXT NOT NULL,
    strategy TEXT NOT NULL,
    RR DECIMAL NOT NULL,
    target DECIMAL NOT NULL,
    date DATE NOT NULL (date <= now()),
    duration TEXT NOT NULL,
    TP INTEGER NOT NULL,
    PNL TEXT NOT NULL
);


GRANT ALL ON DATABASE sem2023_saraz TO alanm WITH GRANT OPTION;
GRANT ALL ON SCHEMA public TO alanm WITH GRANT OPTION;
GRANT ALL ON ALL TABLES IN SCHEMA public TO alanm WITH GRANT OPTION;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO alanm WITH GRANT OPTION;
GRANT CONNECT ON DATABASE sem2023_saraz TO javnost;
GRANT USAGE ON SCHEMA public TO javnost;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO javnost;

-- dodatne pravice za uporabo aplikacije

GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO javnost;
GRANT INSERT ON app_user TO javnost;
GRANT INSERT ON trade TO javnost;