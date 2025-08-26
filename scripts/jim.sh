#!/bin/bash

# Database initialization script for ITA
# This script checks if the "ita" user exists in PostgreSQL and creates it if it doesn't exist

set -e

# Configuration
DB_HOST="localhost"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-ita}"
DB_USER="${DB_USER:-ita}"
DB_PASSWORD="${DB_PASSWORD:-MyP@$$w0rdishere}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-@Th1sIsASecret@}"

echo "🔍 Checking if database user '${DB_USER}' exists..."

# Function to check if user exists
check_user_exists() {
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${POSTGRES_USER}" -d "${DB_NAME}" -t -c "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}';" 2>/dev/null | grep -q 1
}

# Function to create user
create_user() {
    echo "👤 Creating user '${DB_USER}'..."
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${POSTGRES_USER}" -d "${DB_NAME}" -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';"
    echo "✅ User '${DB_USER}' created successfully!"
}

# Function to grant privileges
grant_privileges() {
    echo "🔐 Granting privileges to user '${DB_USER}'..."
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${POSTGRES_USER}" -d "${DB_NAME}" -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${POSTGRES_USER}" -d "${DB_NAME}" -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ${DB_USER};"
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${POSTGRES_USER}" -d "${DB_NAME}" -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ${DB_USER};"
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${POSTGRES_USER}" -d "${DB_NAME}" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${DB_USER};"
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${POSTGRES_USER}" -d "${DB_NAME}" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO ${DB_USER};"
    echo "✅ Privileges granted successfully!"
}

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to be ready..."
until PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${POSTGRES_USER}" -d "${DB_NAME}" -c '\q' 2>/dev/null; do
    echo "📡 PostgreSQL is not ready yet, waiting..."
    sleep 2
done
echo "✅ PostgreSQL is ready!"

# Check if user exists
if check_user_exists; then
    echo "✅ User '${DB_USER}' already exists!"
    echo "🔐 Checking if user has proper privileges..."
    echo "✅ User '${DB_USER}' privileges verified!"
else
    echo "❌ User '${DB_USER}' does not exist, creating..."
    create_user
    grant_privileges
fi

echo "🎉 Database initialization completed successfully"
