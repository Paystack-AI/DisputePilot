-- runs once, when the postgres volume is first created: the database pytest uses
-- (ASYNC_TEST_DB_URL); the main database comes from POSTGRES_DB
CREATE DATABASE disputepilot_test;
