#!/bin/bash

# Create test database alongside the main database (fire-and-forget)
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "CREATE DATABASE boxboxbox_test;" 2>/dev/null || true
